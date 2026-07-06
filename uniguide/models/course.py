from pydantic import BaseModel


class Course(BaseModel):
    course_id: str
    title: str
    description: str
    ects: int
    tags: list[str] = []
    semester_offered: list[int] = []
    prerequisites: list[str] = []
    mandatory: bool = False
    link: str = ""
    # Weekly meeting slot, e.g. "Mon" 09:00-11:00. None for courses with no
    # fixed class time (thesis/independent-study entries like DS701/DS702).
    day_of_week: str | None = None
    start_time: str | None = None  # "HH:MM", 24h
    end_time: str | None = None  # "HH:MM", 24h


class CourseRecommendation(BaseModel):
    course_id: str
    title: str
    credits: int
    relevance_score: float  # 0-1, from RAG
    rationale: str  # LLM-generated explanation
    semester_offered: list[int]
    prerequisites_met: bool
    link: str = ""
    mandatory: bool = False
    day_of_week: str | None = None
    start_time: str | None = None  # "HH:MM", 24h
    end_time: str | None = None  # "HH:MM", 24h
