from datetime import date
from typing import Literal

from pydantic import BaseModel


class CalendarEventRecord(BaseModel):
    """Local source of truth for "have we already scheduled this course's
    calendar event," independent of which plan version last confirmed it —
    keyed on (student_id, course_id), not on a plan id, since plans are
    append-only and re-syncing an unchanged course across regenerations
    should never create a duplicate event.
    """

    student_id: str
    course_id: str
    plan_id: int  # which plan row last confirmed/touched this event (bookkeeping only)
    calendar_event_id: str
    start_date: date
    end_date: date
    day_of_week: str | None
    start_time: str | None
    end_time: str | None
    status: Literal["active", "cancelled", "expired"]


class CalendarSyncResult(BaseModel):
    course_id: str
    status: Literal["created", "already_scheduled", "updated", "conflict_flagged", "skipped_expired"]
    calendar_event_id: str | None
    note: str | None = None
