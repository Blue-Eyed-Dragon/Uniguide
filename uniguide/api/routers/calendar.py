"""Calendar sync endpoint.

Reuses tools/calendar_tool.py's service-account auth as-is, no new auth code.
Every call here — regardless of which student — writes to the one calendar
that's been shared with the service account (settings.google_calendar_id).
Fine for a single-demo-user hackathon; does not give each student their own
calendar. A real multi-user deployment would need per-student OAuth instead.
"""

from fastapi import APIRouter, HTTPException

from uniguide.api.schemas import PlanResponse
from uniguide.models.plan import SemesterPlan
from uniguide.tools.calendar_tool import create_semester_events_tool
from uniguide.tools.db_tool import (
    read_latest_semester_plan,
    read_latest_semester_plan_id,
    write_semester_plan,
)

router = APIRouter(tags=["calendar"])


@router.post("/students/{student_id}/plan/sync-calendar", response_model=PlanResponse)
def sync_calendar(student_id: str) -> PlanResponse:
    plan = read_latest_semester_plan(student_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No semester plan to sync yet.")

    plan_id = read_latest_semester_plan_id(student_id)
    result = create_semester_events_tool(plan.model_dump(), plan_id=plan_id)
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["error"])

    # No update-in-place exists in db_tool.py — writing persists a new plan
    # row with calendar_event_ids filled in, same append-only pattern
    # agents/orchestrator.py's run_pipeline already uses.
    synced_plan = SemesterPlan.model_validate(result["semester_plan"])
    write_semester_plan(synced_plan)
    return PlanResponse(plan=synced_plan)
