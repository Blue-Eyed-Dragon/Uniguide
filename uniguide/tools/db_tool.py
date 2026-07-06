"""ADK tools: read/write StudentProfile and SemesterPlan against SQLite.

Converts between the Pydantic I/O schemas (models/) that agents pass around
and the SQLAlchemy ORM tables (db/database.py) that persist them.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from uniguide.db.database import (
    CalendarEventRecordORM,
    GradeORM,
    PlannedCourseORM,
    SemesterBlockORM,
    SemesterPlanORM,
    SessionLocal,
    StudentProfileORM,
)
from uniguide.models.calendar import CalendarEventRecord
from uniguide.models.course import CourseRecommendation
from uniguide.models.plan import SemesterBlock, SemesterPlan
from uniguide.models.student import Grade, StudentProfile


def write_student_profile(profile: StudentProfile) -> None:
    """Upsert a StudentProfile (and its grades) into the DB."""
    with SessionLocal() as session:
        existing = session.get(StudentProfileORM, profile.student_id)
        if existing:
            session.delete(existing)
            session.flush()

        session.add(
            StudentProfileORM(
                student_id=profile.student_id,
                name=profile.name,
                program=profile.program,
                semesters_completed=profile.semesters_completed,
                start_year=profile.start_year,
                start_season=profile.start_season,
                interests=profile.interests,
                grades=[
                    GradeORM(
                        course_id=g.course_id,
                        course_title=g.course_title,
                        ects=g.ects,
                        grade=g.grade,
                        semester=g.semester,
                    )
                    for g in profile.grades
                ],
            )
        )
        session.commit()


def read_student_profile(student_id: str) -> StudentProfile | None:
    with SessionLocal() as session:
        orm_profile = session.get(
            StudentProfileORM,
            student_id,
            options=[selectinload(StudentProfileORM.grades)],
        )
        if orm_profile is None:
            return None

        return StudentProfile(
            student_id=orm_profile.student_id,
            name=orm_profile.name,
            program=orm_profile.program,
            semesters_completed=orm_profile.semesters_completed,
            start_year=orm_profile.start_year,
            start_season=orm_profile.start_season,
            interests=orm_profile.interests,
            grades=[
                Grade(
                    course_id=g.course_id,
                    course_title=g.course_title,
                    ects=g.ects,
                    grade=g.grade,
                    semester=g.semester,
                )
                for g in orm_profile.grades
            ],
        )


def load_or_init_profile(student_id: str, current_semester: int) -> tuple[StudentProfile, bool]:
    """Returns (profile, is_fresh_student).

    Reads the student's profile from the DB. If no row exists at all (never
    synced), fabricates a placeholder profile with empty grades so a
    never-before-seen student_id still produces a valid fresher plan.
    """
    profile = read_student_profile(student_id)
    if profile is not None:
        return profile, False

    return (
        StudentProfile(
            student_id=student_id,
            name="(new student)",
            program="(unspecified)",
            semesters_completed=max(current_semester - 1, 0),
            start_year=date.today().year,
            start_season="winter",
            grades=[],
            interests=[],
        ),
        True,
    )


def write_semester_plan(plan: SemesterPlan) -> int:
    """Persist a SemesterPlan. Returns the new plan's DB id."""
    with SessionLocal() as session:
        orm_plan = SemesterPlanORM(
            student_id=plan.student_id,
            total_planned_credits=plan.total_planned_credits,
            graduation_semester=plan.graduation_semester,
            blocks=[
                SemesterBlockORM(
                    semester_number=block.semester_number,
                    total_credits=block.total_credits,
                    calendar_event_ids=block.calendar_event_ids,
                    courses=[
                        PlannedCourseORM(
                            course_id=c.course_id,
                            title=c.title,
                            credits=c.credits,
                            relevance_score=c.relevance_score,
                            rationale=c.rationale,
                            semester_offered=c.semester_offered,
                            prerequisites_met=c.prerequisites_met,
                            mandatory=c.mandatory,
                            link=c.link,
                            day_of_week=c.day_of_week,
                            start_time=c.start_time,
                            end_time=c.end_time,
                        )
                        for c in block.courses
                    ],
                )
                for block in plan.semesters
            ],
        )
        session.add(orm_plan)
        session.commit()
        return orm_plan.id


def read_latest_semester_plan(student_id: str) -> SemesterPlan | None:
    with SessionLocal() as session:
        orm_plan = session.scalars(
            select(SemesterPlanORM)
            .where(SemesterPlanORM.student_id == student_id)
            .order_by(SemesterPlanORM.id.desc())
            .options(
                selectinload(SemesterPlanORM.blocks).selectinload(SemesterBlockORM.courses)
            )
        ).first()
        if orm_plan is None:
            return None

        return SemesterPlan(
            student_id=orm_plan.student_id,
            total_planned_credits=orm_plan.total_planned_credits,
            graduation_semester=orm_plan.graduation_semester,
            semesters=[
                SemesterBlock(
                    semester_number=block.semester_number,
                    total_credits=block.total_credits,
                    calendar_event_ids=block.calendar_event_ids,
                    courses=[
                        CourseRecommendation(
                            course_id=c.course_id,
                            title=c.title,
                            credits=c.credits,
                            relevance_score=c.relevance_score,
                            rationale=c.rationale,
                            semester_offered=c.semester_offered,
                            prerequisites_met=c.prerequisites_met,
                            mandatory=c.mandatory,
                            link=c.link,
                            day_of_week=c.day_of_week,
                            start_time=c.start_time,
                            end_time=c.end_time,
                        )
                        for c in block.courses
                    ],
                )
                for block in orm_plan.blocks
            ],
        )


def read_latest_semester_plan_id(student_id: str) -> int | None:
    with SessionLocal() as session:
        return session.scalars(
            select(SemesterPlanORM.id)
            .where(SemesterPlanORM.student_id == student_id)
            .order_by(SemesterPlanORM.id.desc())
        ).first()


def get_calendar_event_record(student_id: str, course_id: str) -> CalendarEventRecord | None:
    with SessionLocal() as session:
        orm_record = session.scalars(
            select(CalendarEventRecordORM).where(
                CalendarEventRecordORM.student_id == student_id,
                CalendarEventRecordORM.course_id == course_id,
            )
        ).first()
        if orm_record is None:
            return None

        return CalendarEventRecord(
            student_id=orm_record.student_id,
            course_id=orm_record.course_id,
            plan_id=orm_record.plan_id,
            calendar_event_id=orm_record.calendar_event_id,
            start_date=orm_record.start_date,
            end_date=orm_record.end_date,
            day_of_week=orm_record.day_of_week,
            start_time=orm_record.start_time,
            end_time=orm_record.end_time,
            status=orm_record.status,
        )


def list_active_calendar_event_records(student_id: str) -> list[CalendarEventRecord]:
    """Every non-cancelled/non-expired record for this student — used to
    locally flag time-overlap conflicts between two of the student's own
    UniGuide-tracked courses without an extra Calendar API call.
    """
    with SessionLocal() as session:
        orm_records = session.scalars(
            select(CalendarEventRecordORM).where(
                CalendarEventRecordORM.student_id == student_id,
                CalendarEventRecordORM.status == "active",
            )
        ).all()

        return [
            CalendarEventRecord(
                student_id=r.student_id,
                course_id=r.course_id,
                plan_id=r.plan_id,
                calendar_event_id=r.calendar_event_id,
                start_date=r.start_date,
                end_date=r.end_date,
                day_of_week=r.day_of_week,
                start_time=r.start_time,
                end_time=r.end_time,
                status=r.status,
            )
            for r in orm_records
        ]


def upsert_calendar_event_record(record: CalendarEventRecord) -> None:
    """Insert or update the (student_id, course_id)-keyed idempotency row."""
    with SessionLocal() as session:
        existing = session.scalars(
            select(CalendarEventRecordORM).where(
                CalendarEventRecordORM.student_id == record.student_id,
                CalendarEventRecordORM.course_id == record.course_id,
            )
        ).first()

        if existing:
            existing.plan_id = record.plan_id
            existing.calendar_event_id = record.calendar_event_id
            existing.start_date = record.start_date.isoformat()
            existing.end_date = record.end_date.isoformat()
            existing.day_of_week = record.day_of_week
            existing.start_time = record.start_time
            existing.end_time = record.end_time
            existing.status = record.status
        else:
            session.add(
                CalendarEventRecordORM(
                    student_id=record.student_id,
                    course_id=record.course_id,
                    plan_id=record.plan_id,
                    calendar_event_id=record.calendar_event_id,
                    start_date=record.start_date.isoformat(),
                    end_date=record.end_date.isoformat(),
                    day_of_week=record.day_of_week,
                    start_time=record.start_time,
                    end_time=record.end_time,
                    status=record.status,
                )
            )
        session.commit()


def delete_calendar_event_records(student_id: str) -> int:
    """Delete every idempotency row for this student. Only clears our local
    bookkeeping — does not touch the actual Calendar events; pair with a
    real deletion (e.g. delete_agent_calendar_events.py) so the two stay in
    sync, otherwise a later sync would see stale "active" rows pointing at
    events that no longer exist.

    Returns:
        The number of rows deleted.
    """
    with SessionLocal() as session:
        orm_records = session.scalars(
            select(CalendarEventRecordORM).where(CalendarEventRecordORM.student_id == student_id)
        ).all()
        for orm_record in orm_records:
            session.delete(orm_record)
        session.commit()
        return len(orm_records)
