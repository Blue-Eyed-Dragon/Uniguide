"""Thin entrypoint: run the full orchestration pipeline from a planning
questionnaire, optionally seeding the DB from a profile JSON / transcript PDF
first. Kept separate from cli.py so the pipeline can be driven from tests or
a notebook without going through Click/Rich.
"""

import json
from pathlib import Path

from uniguide.agents.orchestrator import run_pipeline, sync_transcript
from uniguide.models.student import PlanningQuestionnaire, StudentProfile
from uniguide.tools.db_tool import read_student_profile, write_student_profile


def run(
    student_id: str,
    current_semester: int,
    interests: list[str] | None = None,
    target_credits_per_semester: int | None = None,
    plan_full_degree: bool = False,
    seed_profile_path: str | Path | None = None,
    seed_transcript_path: str | Path | None = None,
    sync_calendar: bool = False,
) -> dict:
    """Optionally seed this student's DB row (as if the university had just
    synced their record), then run the pipeline from a planning questionnaire.
    See agents.orchestrator.run_pipeline for the return shape.
    """
    if seed_transcript_path:
        sync_transcript(student_id, str(seed_transcript_path))

    if seed_profile_path:
        profile_data = json.loads(Path(seed_profile_path).read_text(encoding="utf-8"))
        profile_data["student_id"] = student_id
        existing = read_student_profile(student_id)
        if existing:
            profile_data.setdefault("grades", [g.model_dump() for g in existing.grades])
            profile_data.setdefault("start_year", existing.start_year)
            profile_data.setdefault("start_season", existing.start_season)
        else:
            profile_data.setdefault("start_year", 2024)
            profile_data.setdefault("start_season", "winter")
        write_student_profile(StudentProfile.model_validate(profile_data))

    questionnaire = PlanningQuestionnaire(
        student_id=student_id,
        current_semester=current_semester,
        interests=interests or [],
        target_credits_per_semester=target_credits_per_semester,
        plan_full_degree=plan_full_degree,
    )
    return run_pipeline(questionnaire, sync_calendar=sync_calendar)
