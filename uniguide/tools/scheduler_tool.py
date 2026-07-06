"""Deterministic semester scheduling: greedily place CourseRecommendations
into future semesters, respecting a per-semester credit cap and the course
catalog's semester-offered rotation.

Catalog `semester_offered` values are slots 1-4 within TU Dortmund's
4-semester Master's cycle (odd = winter, even = summer). Those slots repeat
every year, so a course offered in slot 2 is also available in absolute
semester 6, 10, etc. — `(semester_number - 1) % 4 + 1` maps an absolute
semester number onto its slot, so a student taking longer than 4 semesters
still gets access to every offered course.
"""

from pydantic import ValidationError

from uniguide.config import settings
from uniguide.models.course import CourseRecommendation


def _offered_slot(semester_number: int) -> int:
    return (semester_number - 1) % 4 + 1


def build_semester_plan_tool(
    student_id: str,
    credits_remaining: int,
    completed_course_ids: list[str],
    candidate_courses: list[dict],
    current_semester: int,
    max_credits_per_semester: int | None = None,
) -> dict:
    """Greedily schedule candidate courses (ranked, highest relevance_score
    first) into semesters starting at current_semester.

    Args:
        student_id: the student's ID.
        credits_remaining: ECTS still needed to graduate (from ProfileAnalysis).
        completed_course_ids: course_ids the student has already completed.
        candidate_courses: CourseRecommendation-shaped dicts (course_id,
            title, credits, relevance_score, rationale, semester_offered,
            prerequisites_met), pre-ranked by relevance_score descending.
        current_semester: the next semester number to plan (e.g.
            semesters_completed + 1).
        max_credits_per_semester: overrides settings.max_credits_per_semester.

    Returns:
        {"success": True, "semester_plan": {student_id, semesters: [...],
        total_planned_credits, graduation_semester}}, or {"success": False,
        "error": "..."} if no eligible course could be scheduled at all.
    """
    try:
        # candidate_courses may come straight from an LLM tool call (concierge
        # builds this dict itself, unlike course_recommender's schema-validated
        # output) — normalize through CourseRecommendation so a malformed/
        # incomplete dict fails clearly here instead of crashing below with a
        # raw KeyError.
        normalized_courses = [CourseRecommendation.model_validate(c).model_dump() for c in candidate_courses]
    except ValidationError as e:
        return {
            "success": False,
            "error": f"candidate_courses did not match the expected CourseRecommendation shape: {e}",
        }

    cap = max_credits_per_semester or settings.max_credits_per_semester
    remaining = credits_remaining
    already_taken = set(completed_course_ids)
    pool = [c for c in normalized_courses if c["course_id"] not in already_taken]

    semesters = []
    semester_number = current_semester
    max_semesters_to_try = 12  # safety cutoff against an unschedulable pool

    while remaining > 0 and pool and (semester_number - current_semester) < max_semesters_to_try:
        slot = _offered_slot(semester_number)
        block_courses = []
        block_credits = 0

        for course in list(pool):
            if slot not in course["semester_offered"]:
                continue
            if not course["prerequisites_met"]:
                continue
            if block_credits + course["credits"] > cap:
                continue
            block_courses.append(course)
            block_credits += course["credits"]
            pool.remove(course)
            remaining -= course["credits"]
            if remaining <= 0:
                break

        if block_courses:
            semesters.append(
                {
                    "semester_number": semester_number,
                    "courses": block_courses,
                    "total_credits": block_credits,
                    "calendar_event_ids": [],
                }
            )

        semester_number += 1

    if not semesters:
        return {
            "success": False,
            "error": "No eligible candidate courses could be scheduled for the requested semesters.",
        }

    total_planned_credits = sum(block["total_credits"] for block in semesters)

    return {
        "success": True,
        "semester_plan": {
            "student_id": student_id,
            "semesters": semesters,
            "total_planned_credits": total_planned_credits,
            "graduation_semester": semesters[-1]["semester_number"],
        },
    }
