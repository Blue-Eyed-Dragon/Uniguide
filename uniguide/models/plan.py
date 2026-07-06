from datetime import date

from pydantic import BaseModel

from uniguide.models.course import CourseRecommendation


class SemesterBlock(BaseModel):
    semester_number: int
    courses: list[CourseRecommendation]
    total_credits: int
    calendar_event_ids: list[str] = []
    # Not persisted — computed and filled in only at API-response time (see
    # api/routers/dashboard.py) from the same per-student start_year/
    # start_season + semester_length_weeks math tools/calendar_tool.py uses
    # for sync, so the frontend never has to duplicate that date logic itself.
    start_date: date | None = None
    end_date: date | None = None


class SemesterPlan(BaseModel):
    student_id: str
    semesters: list[SemesterBlock]
    total_planned_credits: int
    graduation_semester: int
