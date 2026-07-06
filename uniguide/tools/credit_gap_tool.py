"""ADK tool: compute completed vs remaining ECTS for a student from the DB."""

from sqlalchemy import select

from uniguide.config import settings
from uniguide.db.database import GradeORM, SessionLocal


def credit_gap_tool(student_id: str) -> dict:
    """Return completed/remaining ECTS credits for the given student.

    Args:
        student_id: the student's ID as stored via db_tool.write_student_profile.

    Returns:
        dict with credits_completed, credits_remaining, degree_total_ects.
    """
    with SessionLocal() as session:
        grades = session.scalars(
            select(GradeORM).where(GradeORM.student_id == student_id)
        ).all()

    credits_completed = sum(g.ects for g in grades)
    credits_remaining = max(settings.degree_total_ects - credits_completed, 0)

    return {
        "student_id": student_id,
        "credits_completed": credits_completed,
        "credits_remaining": credits_remaining,
        "degree_total_ects": settings.degree_total_ects,
    }
