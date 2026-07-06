"""Concierge agent — one continuous chat that both builds a student's
semester plan conversationally and answers follow-up questions about it.

Unlike profile_analyst/course_recommender/scheduler, this agent has no
output_schema: its replies are free-form conversational text. Rather than
invoking those 3 agents as nested Runner calls (untested, risks nested
session-service/event-loop interaction), this agent gets direct tool access
to the same deterministic building blocks they wrap — scheduler_tool's
build_semester_plan_tool is plain Python with no LLM inside it, so calling
it here is equivalent to going through the "scheduler agent," not a new
risk — and does the picking/reasoning course_recommender used to do itself,
inline in its own conversational turn. See uniguide.chat for how this agent
is run with a persistent (DatabaseSessionService-backed) session instead of
the InMemorySessionService the other three agents use.
"""

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.tools import ToolContext

from uniguide.agents.course_recommender import search_courses_tool
from uniguide.config import agent_model
from uniguide.ingestion.catalog_ingestor import DEFAULT_CATALOG_PATH, load_courses
from uniguide.ingestion.transcript_parser import analyze_grades, derive_semesters_completed
from uniguide.models.plan import SemesterPlan
from uniguide.tools.calendar_tool import create_semester_events_tool
from uniguide.tools.credit_gap_tool import credit_gap_tool as _credit_gap_tool
from uniguide.tools.db_tool import (
    load_or_init_profile,
    read_latest_semester_plan,
    read_latest_semester_plan_id,
    read_student_profile,
    write_semester_plan,
    write_student_profile,
)
from uniguide.tools.scheduler_tool import build_semester_plan_tool

INSTRUCTION = """\
You are UniGuide's course-planning concierge — one continuous chat that both
builds a student's semester plan and answers follow-up questions about it.

FIRST, check whether this student already has a plan: call
`get_student_context_tool`. If `semester_plan` is null, you're in planning
mode; if it already has a plan, default to follow-up mode (below) unless the
student explicitly asks for a new/updated plan.

PLANNING MODE (no plan yet, or the student wants a new one):
1. Figure out which semester you're planning for and what to focus on —
   don't re-ask for information already in front of you:
   - `get_student_context_tool`'s response includes `suggested_next_semester`
     (the student's next semester based on their stored progress). If the
     student says anything like "my next/upcoming semester" or doesn't name
     a specific semester number, use `suggested_next_semester` directly —
     do not ask them to confirm or restate it. Only ask for a semester
     number if they're asking about a *different* semester than their next
     one (e.g. "plan two semesters ahead").
   - If the student already stated any interest or focus area in their
     message (e.g. "based on my interest in statistics"), treat that as
     given — use it, don't ask them to repeat or add to it before
     proceeding. It's fine to mention you can add more later; it is not
     fine to withhold building the plan pending an answer to "anything
     else?" A short back-and-forth is fine for genuinely missing info, but
     never re-ask for something already answered in the same message.
   - Full-degree vs. upcoming-semester-only is the one thing worth asking
     about if not already stated, since it changes the plan's scope
     significantly — default to "no" (upcoming semester only) if the
     student doesn't have an opinion after one ask, don't block on it.
2. Call `set_planning_context_tool` with what you gathered.
3. Using the returned weak_subjects/strong_subjects plus their interests,
   call `search_courses_tool` (you may call it more than once, once per weak
   subject or interest) to find candidate courses, excluding
   completed_course_ids. Merge and de-duplicate results by course_id.
4. For each course you decide to recommend, build a CourseRecommendation-
   shaped dict: `credits` = the tool's `ects` (same number, renamed). Keep
   `relevance_score`, `prerequisites_met`, `link`, `mandatory`, `day_of_week`,
   `start_time`, and `end_time` exactly as returned by the tool — do not
   invent or adjust them (the last three may be empty/null for courses with
   no fixed weekly class time, e.g. thesis entries). Write a 1-2 sentence
   `rationale` tied to this specific student's weak subjects, interests, or
   progression — not a generic course description. Don't recommend a course
   whose prerequisites_met is false unless no better-fitting alternative
   exists, and say so in the rationale.
5. Call `schedule_and_save_plan_tool` with your candidate list and whether
   they asked to plan their whole remaining degree.
6. Present the result conversationally, semester by semester: course code +
   title, ECTS, whether it's required, your rationale, and the enrollment
   link. If plan_full_degree was False, mention they can ask for their whole
   remaining degree to be planned too.

FOLLOW-UP MODE (plan already exists): answer questions ("why not X sooner",
"what electives are left", "how many credits do I still need") using
`get_student_context_tool`, `credit_gap_tool`, and `search_courses_tool`.
Ground every answer in these tools, not guesses.

CALENDAR SYNC: only call `sync_calendar_tool` when the student explicitly
asks, in that message, to add/sync their plan to their calendar (e.g. "add
this to my calendar", "sync my plan"). Never call it proactively — not right
after building or updating a plan, not as a suggested next step you carry
out yourself. After calling it, summarize the real per-course outcomes
conversationally (created, already on the calendar, updated, flagged as
conflicting with another course, or skipped because that semester's already
over) — don't just say "done."

Keep responses conversational and concise — a few sentences or a short list,
not a long report — except when presenting a freshly generated plan (step
6), where a clear semester-by-semester breakdown is appropriate.
"""


def get_student_context_tool(tool_context: ToolContext) -> dict:
    """Look up this student's stored profile and most recent semester plan.

    Returns:
        {"profile": {...} | None, "semester_plan": {...} | None,
        "suggested_next_semester": int} — profile/semester_plan may be None
        if nothing has been planned for this student yet.
        suggested_next_semester is derived from the student's actual grade
        records (derive_semesters_completed), not from the profile's stored
        semesters_completed alone — that field can be stale/wrong if an
        earlier conversation stated a lower semester, so this is the
        authoritative number. Use this instead of asking the student for a
        semester number when they just want "my next/upcoming semester."
    """
    student_id = tool_context.session.user_id
    profile = read_student_profile(student_id)
    plan = read_latest_semester_plan(student_id)
    grade_floor = derive_semesters_completed(profile.grades) if profile else 0
    suggested = max(profile.semesters_completed, grade_floor) + 1 if profile else 1
    return {
        "profile": profile.model_dump() if profile else None,
        "semester_plan": plan.model_dump() if plan else None,
        "suggested_next_semester": suggested,
    }


def set_planning_context_tool(
    current_semester: int, interests: list[str], tool_context: ToolContext
) -> dict:
    """Load (or initialize) this student's profile, merge in their stated
    interests and target semester, persist it, and return their current
    academic standing. Call this before searching for candidate courses.

    Args:
        current_semester: the semester they're planning for.
        interests: what they want to focus on this planning session (may be empty).

    Returns:
        {"is_fresh_student": bool, "profile_analysis": {credits_completed,
        credits_remaining, completed_course_ids, weak_subjects,
        strong_subjects, gpa}}.
    """
    student_id = tool_context.session.user_id
    profile, is_fresh = load_or_init_profile(student_id, current_semester)
    profile.interests = sorted(set(profile.interests) | set(interests))
    # Never let a stated/defaulted current_semester regress progress below
    # what the student's actual grade records already prove — see
    # derive_semesters_completed.
    grade_floor = derive_semesters_completed(profile.grades)
    profile.semesters_completed = max(current_semester - 1, grade_floor, 0)
    write_student_profile(profile)

    catalog = load_courses(DEFAULT_CATALOG_PATH)
    analysis = analyze_grades(profile.grades, catalog=catalog)
    return {"is_fresh_student": is_fresh, "profile_analysis": analysis.model_dump()}


def schedule_and_save_plan_tool(
    current_semester: int,
    candidate_courses: list[dict],
    tool_context: ToolContext,
    max_credits_per_semester: int | None = None,
    plan_full_degree: bool = False,
) -> dict:
    """Schedule the given candidate courses into semesters and persist the
    resulting plan. Call this after set_planning_context_tool and after
    gathering candidate_courses via search_courses_tool.

    Args:
        current_semester: the semester being planned for.
        candidate_courses: CourseRecommendation-shaped dicts you've picked
            (course_id, title, credits, relevance_score, rationale,
            semester_offered, prerequisites_met, link, mandatory).
        max_credits_per_semester: overrides the default ECTS cap per semester.
        plan_full_degree: if True, fill in the rest of the degree with
            remaining catalog courses (mandatory ones first) beyond your
            picks, so the plan covers all remaining credits, not just your
            personalized picks.

    Returns:
        Same shape as tools.scheduler_tool.build_semester_plan_tool, plus
        "plan_id" on success.
    """
    student_id = tool_context.session.user_id
    profile = read_student_profile(student_id)
    if profile is None:
        return {"success": False, "error": "No profile found — call set_planning_context_tool first."}

    catalog = load_courses(DEFAULT_CATALOG_PATH)
    analysis = analyze_grades(profile.grades, catalog=catalog)

    candidates = candidate_courses
    if plan_full_degree:
        completed = set(analysis.completed_course_ids)
        already_considered = completed | {c["course_id"] for c in candidate_courses}
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
        candidates = candidate_courses + remaining

    result = build_semester_plan_tool(
        student_id=student_id,
        credits_remaining=analysis.credits_remaining,
        completed_course_ids=analysis.completed_course_ids,
        candidate_courses=candidates,
        current_semester=current_semester,
        max_credits_per_semester=max_credits_per_semester,
    )
    if result["success"]:
        plan_id = write_semester_plan(SemesterPlan.model_validate(result["semester_plan"]))
        result["plan_id"] = plan_id
    return result


def credit_gap_tool(tool_context: ToolContext) -> dict:
    """Return completed/remaining ECTS credits for the current student.

    Returns:
        dict with credits_completed, credits_remaining, degree_total_ects.
    """
    return _credit_gap_tool(tool_context.session.user_id)


CALENDAR_SYNC_KEYWORDS = ("calendar", "sync", "ical", "google cal")


def _last_user_message_text(tool_context: ToolContext) -> str:
    """The literal text of the most recent user-authored turn, read straight
    from session history rather than trusting the model's own account of
    what was said — see sync_calendar_tool for why this matters.
    """
    for event in reversed(tool_context.session.events):
        content = getattr(event, "content", None)
        if content and content.role == "user" and content.parts:
            return " ".join(p.text for p in content.parts if p.text)
    return ""


def sync_calendar_tool(tool_context: ToolContext) -> dict:
    """Push the student's current semester plan to Google Calendar. Only
    call this when the student has explicitly asked for it in this message
    — never proactively.

    As a second, code-level check (not just this instruction), this also
    requires the student's actual last message to contain real calendar-sync
    intent wording — read from session history, not taken on the model's
    word — so a prompt injection planted in catalog course text couldn't
    talk the model into triggering a sync the student never asked for.

    Idempotent and date-aware (uniguide.tools.calendar_tool): re-syncing an
    already-synced course is a no-op, courses whose semester has already
    ended are skipped, and two of the student's own courses that overlap in
    time still get created but flagged as a conflict rather than silently
    double-booked.

    Returns:
        {"success": True, "semester_plan": {...}, "results": [{"course_id",
        "status", "calendar_event_id", "note"}, ...]} — one status per
        course (created/already_scheduled/updated/conflict_flagged/
        skipped_expired) — or {"success": False, "error": "..."} if there's
        no plan yet, the request wasn't clearly asked for, or the Calendar
        API call fails.
    """
    last_message = _last_user_message_text(tool_context).lower()
    if not any(keyword in last_message for keyword in CALENDAR_SYNC_KEYWORDS):
        return {
            "success": False,
            "error": "Calendar sync must be explicitly requested by the student — ask them to confirm first.",
        }

    student_id = tool_context.session.user_id
    plan = read_latest_semester_plan(student_id)
    if plan is None:
        return {"success": False, "error": "No semester plan to sync yet."}

    plan_id = read_latest_semester_plan_id(student_id)
    result = create_semester_events_tool(plan.model_dump(), plan_id=plan_id)
    if result["success"]:
        # Append-only, same pattern api/routers/calendar.py::sync_calendar
        # uses — persist so calendar_event_ids are saved on the latest plan row.
        write_semester_plan(SemesterPlan.model_validate(result["semester_plan"]))
    return result


# DatabaseSessionService persists every turn forever, so a long-running chat
# would otherwise replay the *entire* history into the model on every call —
# unbounded token growth, eventually blowing past the context window. This
# caps what actually gets sent, keeping only the most recent exchanges (a
# "turn" here is 2+ Content entries — user message, any tool call/response
# pairs, and the model's reply — so this is a token budget, not an exact
# turn count).
MAX_HISTORY_CONTENTS = 20


def _limit_history_window(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    contents = llm_request.contents
    if len(contents) <= MAX_HISTORY_CONTENTS:
        return None

    cutoff = len(contents) - MAX_HISTORY_CONTENTS
    # Don't cut mid-turn: a function_response with no preceding function_call
    # (or a lone model reply with no user message before it) confuses the
    # model, so advance to the next real user message before truncating.
    while cutoff < len(contents) and not (
        contents[cutoff].role == "user" and contents[cutoff].parts and contents[cutoff].parts[0].text
    ):
        cutoff += 1

    if cutoff < len(contents):
        llm_request.contents[:] = contents[cutoff:]
    return None


concierge = LlmAgent(
    name="concierge",
    model=agent_model(),
    description="Conversationally builds a student's semester plan and answers follow-up questions.",
    instruction=INSTRUCTION,
    tools=[
        get_student_context_tool,
        set_planning_context_tool,
        search_courses_tool,
        schedule_and_save_plan_tool,
        credit_gap_tool,
        sync_calendar_tool,
    ],
    before_model_callback=_limit_history_window,
)
