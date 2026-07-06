"""Non-LLM dashboard endpoints — pure DB reads via existing tools/db_tool.py,
tools/credit_gap_tool.py, and ingestion/transcript_parser.py functions.
Safe to hit regardless of Groq/Gemini quota.
"""

from datetime import timedelta

from fastapi import APIRouter, HTTPException

from uniguide.api.schemas import PlanResponse, StudentDashboardResponse
from uniguide.config import settings
from uniguide.ingestion.catalog_ingestor import DEFAULT_CATALOG_PATH, load_courses
from uniguide.ingestion.transcript_parser import analyze_grades
from uniguide.tools.calendar_tool import _semester_start_date
from uniguide.tools.credit_gap_tool import credit_gap_tool
from uniguide.tools.db_tool import read_latest_semester_plan, read_student_profile

router = APIRouter(tags=["dashboard"])


@router.get("/students/{student_id}", response_model=StudentDashboardResponse)
def get_student(student_id: str) -> StudentDashboardResponse:
    profile = read_student_profile(student_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No student found for id {student_id!r}")

    catalog = load_courses(DEFAULT_CATALOG_PATH)
    analysis = analyze_grades(profile.grades, catalog=catalog)
    current_semester = profile.semesters_completed + 1

    return StudentDashboardResponse(
        profile=profile,
        analysis=analysis,
        current_semester=current_semester,
        current_semester_start_date=_semester_start_date(current_semester, profile.start_year, profile.start_season),
    )


@router.get("/students/{student_id}/plan", response_model=PlanResponse)
def get_student_plan(student_id: str) -> PlanResponse:
    plan = read_latest_semester_plan(student_id)
    if plan is not None:
        profile = read_student_profile(student_id)
        for block in plan.semesters:
            block.start_date = _semester_start_date(block.semester_number, profile.start_year, profile.start_season)
            block.end_date = block.start_date + timedelta(weeks=settings.semester_length_weeks)
    return PlanResponse(plan=plan)


@router.get("/students/{student_id}/credit-gap")
def get_credit_gap(student_id: str) -> dict:
    return credit_gap_tool(student_id)
