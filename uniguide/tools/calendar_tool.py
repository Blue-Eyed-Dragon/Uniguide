"""ADK tool: create Google Calendar events for a student's semester plan.

settings.google_service_account_file can hold either kind of Google
credentials JSON, detected from its own contents (see get_calendar_service):
- a service-account key -> no browser/OAuth consent, works headlessly from a
  web server, but the calendar must be shared with that key's client_email
  ahead of time (see .env.example).
- an OAuth client-secret file -> needs a one-time interactive browser consent
  (google_auth_oauthlib's run_local_server), after which the resulting
  refreshable token is cached next to the credentials file so later calls
  (including from the web server) are headless too.

Idempotency/conflict logic (create_semester_events_tool):
- CalendarEventRecord (db_tool.py, keyed on student_id+course_id, not on any
  particular plan row — plans are append-only, so re-syncing an unchanged
  course across plan regenerations must resolve to the same event, never
  create a duplicate) is the primary source of truth for "already scheduled."
- Each event is tagged with extendedProperties.private so a live Calendar
  events().list(privateExtendedProperty=...) lookup can recover the same
  event if the local record was ever lost (DB/Calendar drift).
- Courses whose whole semester window has already ended relative to today
  are skipped ("skipped_expired") rather than (re)created; a sync that lands
  mid-semester anchors the first occurrence at today instead of backfilling
  already-past class sessions.
- Two of the *same* student's own UniGuide-tracked courses that overlap in
  day/time get created but reported as "conflict_flagged" (a local DB check,
  no extra Calendar API call) rather than silently double-booked. Conflicts
  against external, non-UniGuide events are out of scope.

If credentials are missing/unrecognized or an API call fails outright, this
degrades to {"success": False, "error": ...} instead of crashing the
pipeline, so the CLI can still print an unsynced plan. Calendar sync itself
is always a manual, user-triggered action (the dashboard's "Sync to
Calendar" button / POST .../plan/sync-calendar, or the CLI's --sync-calendar
flag) — nothing here calls this automatically.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from tenacity import retry, stop_after_attempt, wait_exponential

from uniguide.config import settings
from uniguide.models.calendar import CalendarEventRecord
from uniguide.tools.db_tool import (
    get_calendar_event_record,
    list_active_calendar_event_records,
    read_student_profile,
    upsert_calendar_event_record,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}

_api_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), reraise=True)


def _today() -> date:
    """A seam so tests can pin "today" instead of depending on wall-clock
    date (which would otherwise make semester-expiry tests flaky/stale)."""
    return date.today()


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _semester_start_date(semester_number: int, start_year: int, start_season: str) -> date:
    """Semester 1 starts at this student's own start_year/start_season —
    settings.winter_start_month_day or summer_start_month_day (global,
    deliberately no year) applied to their start_year (per-student). Each
    later semester starts 6 months after that (winter/summer cycle).
    """
    month_day = settings.winter_start_month_day if start_season == "winter" else settings.summer_start_month_day
    month, day = (int(part) for part in month_day.split("-"))
    start = date(start_year, month, day)
    return _add_months(start, (semester_number - 1) * 6)


def _first_occurrence(anchor: date, day_of_week: str) -> date:
    """The first date on/after anchor that falls on day_of_week."""
    target = _WEEKDAYS[day_of_week]
    return anchor + timedelta(days=(target - anchor.weekday()) % 7)


def _time_ranges_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return a_start < b_end and b_start < a_end


def _date_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def _conflicts_with_record(course: dict, start: date, end: date, record: CalendarEventRecord) -> bool:
    day_of_week = course.get("day_of_week")
    start_time = course.get("start_time")
    end_time = course.get("end_time")
    if not (day_of_week and start_time and end_time and record.day_of_week and record.start_time and record.end_time):
        return False
    if day_of_week != record.day_of_week:
        return False
    if not _date_ranges_overlap(start, end, record.start_date, record.end_date):
        return False
    return _time_ranges_overlap(start_time, end_time, record.start_time, record.end_time)


def _event_body(course: dict, semester_start: date, semester_end: date, student_id: str, today: date) -> dict:
    """A recurring weekly event at the course's actual class time, spanning
    the semester. Courses with no fixed weekly meeting (day_of_week/
    start_time/end_time empty — e.g. thesis entries) fall back to a single
    all-day marker event on the semester's start date. Tagged with
    extendedProperties.private so it's identifiable as UniGuide-owned
    directly from the Calendar API, independent of our local DB.
    """
    summary = f"{course['course_id']}: {course['title']}"
    description = course["rationale"]
    extended_properties = {
        "private": {"uniguide_course_id": course["course_id"], "uniguide_student_id": student_id}
    }

    day_of_week = course.get("day_of_week")
    start_time = course.get("start_time")
    end_time = course.get("end_time")
    if not (day_of_week and start_time and end_time):
        end = semester_start + timedelta(days=1)
        return {
            "summary": summary,
            "description": description,
            "start": {"date": semester_start.isoformat()},
            "end": {"date": end.isoformat()},
            "extendedProperties": extended_properties,
        }

    # Anchor the first occurrence at today instead of semester_start if the
    # sync happens mid-semester, so we don't backfill already-past sessions.
    anchor = max(semester_start, today)
    first = _first_occurrence(anchor, day_of_week)
    start_dt = datetime.combine(first, datetime.strptime(start_time, "%H:%M").time())
    end_dt = datetime.combine(first, datetime.strptime(end_time, "%H:%M").time())

    if anchor == semester_start:
        recurrence = f"RRULE:FREQ=WEEKLY;COUNT={settings.semester_length_weeks}"
    else:
        # Anchor shifted forward — COUNT would now overrun the semester's
        # real end, so cap with UNTIL instead (end-of-day on semester_end).
        recurrence = f"RRULE:FREQ=WEEKLY;UNTIL={semester_end.strftime('%Y%m%d')}T235959Z"

    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": settings.calendar_timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": settings.calendar_timezone},
        "recurrence": [recurrence],
        "extendedProperties": extended_properties,
    }


def _service_account_creds(key_path: Path):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(str(key_path), scopes=SCOPES)


def _oauth_creds(key_path: Path):
    """Load a cached user token next to key_path if there is one (refreshing
    it if expired); otherwise run a one-time interactive browser consent and
    cache the result, so every later call — including from the web server —
    can be headless.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = key_path.with_name(key_path.stem + ".token.json")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(key_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return creds


def get_calendar_service():
    """Build an authenticated Google Calendar API client from
    settings.google_service_account_file, whichever kind of Google
    credentials JSON it turns out to hold:
    - {"type": "service_account", ...} -> _service_account_creds (headless).
    - {"installed": {...}} or {"web": {...}} -> _oauth_creds (one-time
      interactive consent, then a cached refreshable token).

    Raises:
        FileNotFoundError: if settings.google_service_account_file is unset or doesn't exist.
        ValueError: if the file doesn't match either known credentials shape.
    """
    from googleapiclient.discovery import build

    if not settings.google_service_account_file:
        raise FileNotFoundError("GOOGLE_SERVICE_ACCOUNT_FILE is not set.")

    key_path = Path(settings.google_service_account_file)
    if not key_path.exists():
        raise FileNotFoundError(f"Google credentials file not found: {key_path}")

    raw = json.loads(key_path.read_text())
    if raw.get("type") == "service_account":
        creds = _service_account_creds(key_path)
    elif "installed" in raw or "web" in raw:
        creds = _oauth_creds(key_path)
    else:
        raise ValueError(
            f"{key_path} doesn't look like a service-account key or an OAuth client-secret file."
        )

    return build("calendar", "v3", credentials=creds)


@_api_retry
def _insert_event(service, body: dict) -> dict:
    return service.events().insert(calendarId=settings.google_calendar_id, body=body).execute()


@_api_retry
def _patch_event(service, event_id: str, body: dict) -> dict:
    return service.events().patch(calendarId=settings.google_calendar_id, eventId=event_id, body=body).execute()


@_api_retry
def _list_events(service, **kwargs) -> dict:
    return service.events().list(**kwargs).execute()


def _find_existing_event(service, student_id: str, course_id: str, start: date, end: date) -> str | None:
    """A second, self-describing way to detect a UniGuide-owned event
    directly from the Calendar API (via extendedProperties), independent of
    our local CalendarEventRecord table — recovers from local DB/Calendar
    drift instead of creating a duplicate.
    """
    response = _list_events(
        service,
        calendarId=settings.google_calendar_id,
        timeMin=datetime.combine(start, datetime.min.time()).isoformat() + "Z",
        timeMax=datetime.combine(end, datetime.min.time()).isoformat() + "Z",
        privateExtendedProperty=[f"uniguide_student_id={student_id}", f"uniguide_course_id={course_id}"],
        singleEvents=False,
    )
    items = response.get("items", [])
    return items[0]["id"] if items else None


def create_semester_events_tool(semester_plan: dict, plan_id: int, calendar_service=None) -> dict:
    """Create/update one Google Calendar event per planned course and return
    the plan with each SemesterBlock's calendar_event_ids filled in, plus a
    per-course CalendarSyncResult-shaped status report.

    Args:
        semester_plan: a SemesterPlan-shaped dict.
        plan_id: the DB id of the plan row being synced (bookkeeping only —
            CalendarEventRecord is keyed on student_id+course_id, not this).
        calendar_service: an already-built Calendar API client; if omitted,
            one is built via get_calendar_service() (requires credentials).

    Returns:
        {"success": True, "semester_plan": {...with calendar_event_ids...},
        "results": [{"course_id", "status", "calendar_event_id", "note"}, ...]}
        on success, or {"success": False, "error": "...", "semester_plan":
        semester_plan} (unmodified) if auth or an API call fails outright.
    """
    try:
        service = calendar_service or get_calendar_service()
    except Exception:
        logger.exception("Calendar auth failed")
        return {
            "success": False,
            "error": "Calendar authentication failed. Check the server's Google Calendar configuration.",
            "semester_plan": semester_plan,
        }

    student_id = semester_plan["student_id"]
    profile = read_student_profile(student_id)
    if profile is None:
        return {
            "success": False,
            "error": f"No student profile found for {student_id!r} — can't resolve their start_year/start_season.",
            "semester_plan": semester_plan,
        }

    today = _today()
    updated_blocks = []
    results = []

    for block in semester_plan["semesters"]:
        start = _semester_start_date(block["semester_number"], profile.start_year, profile.start_season)
        end = start + timedelta(weeks=settings.semester_length_weeks)
        event_ids = []

        for course in block["courses"]:
            course_id = course["course_id"]
            existing = get_calendar_event_record(student_id, course_id)

            if end < today:
                if existing and existing.status == "active":
                    upsert_calendar_event_record(existing.model_copy(update={"status": "expired"}))
                results.append(
                    {"course_id": course_id, "status": "skipped_expired", "calendar_event_id": None, "note": None}
                )
                continue

            schedule_changed = existing is not None and (
                existing.day_of_week != course.get("day_of_week")
                or existing.start_time != course.get("start_time")
                or existing.end_time != course.get("end_time")
                or existing.start_date != start
                or existing.end_date != end
            )

            if existing and existing.status == "active" and not schedule_changed:
                event_ids.append(existing.calendar_event_id)
                results.append(
                    {
                        "course_id": course_id,
                        "status": "already_scheduled",
                        "calendar_event_id": existing.calendar_event_id,
                        "note": None,
                    }
                )
                continue

            body = _event_body(course, start, end, student_id, today)
            try:
                if existing and existing.status == "active" and schedule_changed:
                    updated = _patch_event(service, existing.calendar_event_id, body)
                    event_id, status, note = updated["id"], "updated", None
                else:
                    found_id = _find_existing_event(service, student_id, course_id, start, end)
                    if found_id:
                        event_id = found_id
                        status = "already_scheduled"
                        note = "recovered from Calendar — local record was missing"
                    else:
                        conflict = next(
                            (
                                r
                                for r in list_active_calendar_event_records(student_id)
                                if r.course_id != course_id and _conflicts_with_record(course, start, end, r)
                            ),
                            None,
                        )
                        created = _insert_event(service, body)
                        event_id = created["id"]
                        status = "conflict_flagged" if conflict else "created"
                        note = f"overlaps with {conflict.course_id}, review manually" if conflict else None
            except Exception:
                logger.exception("Failed to sync calendar event for course %s", course_id)
                return {
                    "success": False,
                    "error": f"Failed to sync the calendar event for {course_id}. Check server logs for details.",
                    "semester_plan": semester_plan,
                }

            event_ids.append(event_id)
            results.append({"course_id": course_id, "status": status, "calendar_event_id": event_id, "note": note})
            upsert_calendar_event_record(
                CalendarEventRecord(
                    student_id=student_id,
                    course_id=course_id,
                    plan_id=plan_id,
                    calendar_event_id=event_id,
                    start_date=start,
                    end_date=end,
                    day_of_week=course.get("day_of_week"),
                    start_time=course.get("start_time"),
                    end_time=course.get("end_time"),
                    status="active",
                )
            )

        updated_blocks.append({**block, "calendar_event_ids": event_ids})

    return {
        "success": True,
        "semester_plan": {**semester_plan, "semesters": updated_blocks},
        "results": results,
    }
