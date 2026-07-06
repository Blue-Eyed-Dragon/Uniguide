from datetime import datetime, timezone

from sqlalchemy import ForeignKey, JSON, UniqueConstraint, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from uniguide.config import settings


class Base(DeclarativeBase):
    pass


class StudentProfileORM(Base):
    __tablename__ = "student_profiles"

    student_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    program: Mapped[str]
    semesters_completed: Mapped[int]
    start_year: Mapped[int] = mapped_column(default=2024)
    start_season: Mapped[str] = mapped_column(default="winter")
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)

    grades: Mapped[list["GradeORM"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    plans: Mapped[list["SemesterPlanORM"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class GradeORM(Base):
    __tablename__ = "grades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("student_profiles.student_id"))
    course_id: Mapped[str]
    course_title: Mapped[str]
    ects: Mapped[int]
    grade: Mapped[float]
    semester: Mapped[int | None] = mapped_column(nullable=True)

    student: Mapped["StudentProfileORM"] = relationship(back_populates="grades")


class SemesterPlanORM(Base):
    __tablename__ = "semester_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("student_profiles.student_id"))
    total_planned_credits: Mapped[int]
    graduation_semester: Mapped[int]
    created_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

    student: Mapped["StudentProfileORM"] = relationship(back_populates="plans")
    blocks: Mapped[list["SemesterBlockORM"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class SemesterBlockORM(Base):
    __tablename__ = "semester_blocks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("semester_plans.id"))
    semester_number: Mapped[int]
    total_credits: Mapped[int]
    calendar_event_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    plan: Mapped["SemesterPlanORM"] = relationship(back_populates="blocks")
    courses: Mapped[list["PlannedCourseORM"]] = relationship(
        back_populates="block", cascade="all, delete-orphan"
    )


class PlannedCourseORM(Base):
    __tablename__ = "planned_courses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    block_id: Mapped[int] = mapped_column(ForeignKey("semester_blocks.id"))
    course_id: Mapped[str]
    title: Mapped[str]
    credits: Mapped[int]
    relevance_score: Mapped[float]
    rationale: Mapped[str]
    semester_offered: Mapped[list[int]] = mapped_column(JSON, default=list)
    prerequisites_met: Mapped[bool]
    mandatory: Mapped[bool] = mapped_column(default=False)
    link: Mapped[str] = mapped_column(default="")
    day_of_week: Mapped[str | None] = mapped_column(nullable=True)
    start_time: Mapped[str | None] = mapped_column(nullable=True)
    end_time: Mapped[str | None] = mapped_column(nullable=True)

    block: Mapped["SemesterBlockORM"] = relationship(back_populates="courses")


class CalendarEventRecordORM(Base):
    """Idempotency record for one course's synced calendar event, keyed on
    (student_id, course_id) — independent of any particular plan row, since
    plans are append-only and re-syncing an unchanged course across plan
    regenerations must resolve to this same row, not a new event.
    """

    __tablename__ = "calendar_event_records"
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_calendar_record_student_course"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("student_profiles.student_id"))
    course_id: Mapped[str]
    plan_id: Mapped[int] = mapped_column(ForeignKey("semester_plans.id"))
    calendar_event_id: Mapped[str]
    start_date: Mapped[str]  # ISO date
    end_date: Mapped[str]  # ISO date
    day_of_week: Mapped[str | None] = mapped_column(nullable=True)
    start_time: Mapped[str | None] = mapped_column(nullable=True)
    end_time: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="active")


engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
