from typing import Literal

from pydantic import BaseModel


class Grade(BaseModel):
    course_id: str
    course_title: str
    ects: int
    grade: float
    semester: int | None = None


class StudentProfile(BaseModel):
    student_id: str
    name: str
    program: str
    semesters_completed: int
    # The real calendar year/term this student's semester 1 began — per-
    # student, since two students can start in different years and/or
    # different terms. Combined with settings.winter_start_month_day /
    # summer_start_month_day (global, no year) to compute a real date for
    # any of their semester numbers — see tools/calendar_tool.py::_semester_start_date.
    start_year: int
    start_season: Literal["winter", "summer"]
    grades: list[Grade] = []
    interests: list[str] = []


class ProfileAnalysis(BaseModel):
    credits_completed: int
    credits_remaining: int
    completed_course_ids: list[str]
    weak_subjects: list[str]  # tags where grade < threshold
    strong_subjects: list[str]
    gpa: float | None


class PlanningQuestionnaire(BaseModel):
    student_id: str
    current_semester: int  # semester being planned for
    interests: list[str] = []  # merged (union) into the stored profile's interests
    target_credits_per_semester: int | None = None  # overrides settings.max_credits_per_semester
    plan_full_degree: bool = False  # fill remaining semesters with the whole catalog, not just LLM picks
