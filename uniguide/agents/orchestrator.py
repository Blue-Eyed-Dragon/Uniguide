"""Orchestrator — wires Profile Analyst -> Course Recommender -> Scheduler
(-> Calendar) into one pipeline that produces and persists a SemesterPlan.

Each specialist runs as its own ADK Runner turn (own fresh in-memory
session), so one agent's tool-calling context doesn't leak into another's.
The hand-off between steps is plain Python data (the dict each agent stores
under its output_key), passed forward directly rather than re-serialized
through the model — see agents.scheduler for why that matters for the
candidate-course list specifically.
"""

from datetime import date

from google.adk.agents import BaseAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from uniguide.agents.course_recommender import course_recommender
from uniguide.agents.scheduler import build_scheduler
from uniguide.db.database import init_db
from uniguide.ingestion.catalog_ingestor import DEFAULT_CATALOG_PATH, load_courses
from uniguide.ingestion.transcript_parser import (
    analyze_grades,
    derive_semesters_completed,
    extract_grades_from_pdf,
)
from uniguide.models.plan import SemesterPlan
from uniguide.models.student import PlanningQuestionnaire, StudentProfile
from uniguide.tools.calendar_tool import create_semester_events_tool
from uniguide.tools.db_tool import (
    load_or_init_profile,
    read_student_profile,
    write_semester_plan,
    write_student_profile,
)

APP_NAME = "uniguide"


def _run_agent_turn(agent: BaseAgent, prompt: str, user_id: str) -> dict:
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(app_name=APP_NAME, user_id=user_id)
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    message = types.Content(role="user", parts=[types.Part(text=prompt)])

    for _ in runner.run(user_id=user_id, session_id=session.id, new_message=message):
        pass

    updated = session_service.get_session_sync(
        app_name=APP_NAME, user_id=user_id, session_id=session.id
    )
    if not updated or agent.output_key not in updated.state:
        raise RuntimeError(f"'{agent.name}' did not produce '{agent.output_key}' in session state.")
    return updated.state[agent.output_key]


def sync_transcript(
    student_id: str,
    pdf_path: str,
    name: str | None = None,
    program: str | None = None,
) -> StudentProfile:
    """Populate/update this student's DB row from a transcript PDF.

    Stand-in for a real university SIS sync: overwrites the student's grades
    with what's freshly extracted from the PDF (raw per-course rows, not the
    aggregate ProfileAnalysis), so `analyze_grades` can be recomputed later
    against a possibly-updated catalog/threshold without re-parsing the PDF.
    """
    init_db()
    existing = read_student_profile(student_id)
    grades = extract_grades_from_pdf(pdf_path)

    profile = StudentProfile(
        student_id=student_id,
        name=name or (existing.name if existing else student_id),
        program=program or (existing.program if existing else "(unspecified)"),
        semesters_completed=existing.semesters_completed if existing else 0,
        start_year=existing.start_year if existing else date.today().year,
        start_season=existing.start_season if existing else "winter",
        grades=grades,
        interests=existing.interests if existing else [],
    )
    write_student_profile(profile)
    return profile


def run_pipeline(
    questionnaire: PlanningQuestionnaire,
    sync_calendar: bool = False,
) -> dict:
    """Run the full pipeline for one student and persist the resulting plan.

    Academic history (grades, completed courses) is read from the DB, not
    re-derived from a transcript on every call — see `sync_transcript` for
    how that data gets into the DB in the first place. The student's only
    input here is the planning questionnaire (semester + interests).

    Args:
        questionnaire: which semester the student is planning for, plus
            their stated interests/credit-load preference for this session.
        sync_calendar: if True, also create Google Calendar events for the
            resulting plan (requires OAuth credentials; degrades gracefully
            to an unsynced plan if that fails).

    Returns:
        On success: {"success": True, "is_fresh_student": bool,
        "profile_analysis": {...}, "course_recommendations": [...],
        "semester_plan": {...}, "plan_id": int, "calendar_synced": bool,
        "calendar_error": str | None}.
        On failure: {"success": False, "stage": "...", "error": "..."}.
    """
    init_db()
    profile, is_fresh = load_or_init_profile(
        questionnaire.student_id, questionnaire.current_semester
    )
    profile.interests = sorted(set(profile.interests) | set(questionnaire.interests))
    # Never let a stated current_semester regress progress below what the
    # student's actual grade records already prove — see
    # derive_semesters_completed.
    grade_floor = derive_semesters_completed(profile.grades)
    profile.semesters_completed = max(questionnaire.current_semester - 1, grade_floor, 0)

    catalog = load_courses(DEFAULT_CATALOG_PATH)
    profile_analysis = analyze_grades(profile.grades, catalog=catalog).model_dump()

    query = (
        f"Student weak subjects: {', '.join(profile_analysis['weak_subjects']) or 'none'}. "
        f"Interests: {', '.join(profile.interests) or 'none specified'}. "
        f"Completed course ids: {', '.join(profile_analysis['completed_course_ids']) or 'none'}."
    )
    course_recommendations = _run_agent_turn(
        course_recommender, query, user_id=profile.student_id
    )
    if not course_recommendations:
        return {
            "success": False,
            "stage": "course_recommender",
            "error": "No course recommendations produced.",
        }

    scheduler_candidates = course_recommendations
    if questionnaire.plan_full_degree:
        # Fill in the rest of the degree deterministically (no extra LLM call —
        # every remaining catalog course not already picked by course_recommender,
        # mandatory ones first) so the scheduler can place a genuinely complete plan.
        completed = set(profile_analysis["completed_course_ids"])
        already_considered = completed | {c["course_id"] for c in course_recommendations}
        remaining = [
            {
                "course_id": c.course_id,
                "title": c.title,
                "credits": c.ects,
                "relevance_score": 0.3,
                "rationale": "Included to complete your remaining degree requirements.",
                "semester_offered": c.semester_offered,
                "prerequisites_met": all(p in completed for p in c.prerequisites),
                "link": c.link,
                "mandatory": c.mandatory,
                "day_of_week": c.day_of_week,
                "start_time": c.start_time,
                "end_time": c.end_time,
            }
            for c in catalog
            if c.course_id not in already_considered
        ]
        remaining.sort(key=lambda c: (not c["mandatory"], c["course_id"]))
        scheduler_candidates = course_recommendations + remaining

    scheduler = build_scheduler(
        student_id=profile.student_id,
        credits_remaining=profile_analysis["credits_remaining"],
        completed_course_ids=profile_analysis["completed_course_ids"],
        candidate_courses=scheduler_candidates,
        current_semester=questionnaire.current_semester,
        max_credits_per_semester=questionnaire.target_credits_per_semester,
    )
    semester_plan = _run_agent_turn(
        scheduler, "Schedule my recommended courses.", user_id=profile.student_id
    )
    if not semester_plan:
        return {"success": False, "stage": "scheduler", "error": "No semester plan produced."}

    plan_id = write_semester_plan(SemesterPlan.model_validate(semester_plan))
    write_student_profile(profile)

    calendar_synced = False
    calendar_error = None
    if sync_calendar:
        calendar_result = create_semester_events_tool(semester_plan, plan_id=plan_id)
        if calendar_result["success"]:
            semester_plan = calendar_result["semester_plan"]
            calendar_synced = True
            # Append-only, same pattern as api/routers/calendar.py::sync_calendar —
            # re-persist so calendar_event_ids are saved on the latest plan row.
            plan_id = write_semester_plan(SemesterPlan.model_validate(semester_plan))
        else:
            calendar_error = calendar_result["error"]

    return {
        "success": True,
        "is_fresh_student": is_fresh,
        "plan_full_degree": questionnaire.plan_full_degree,
        "profile_analysis": profile_analysis,
        "course_recommendations": course_recommendations,
        "semester_plan": semester_plan,
        "plan_id": plan_id,
        "calendar_synced": calendar_synced,
        "calendar_error": calendar_error,
    }
