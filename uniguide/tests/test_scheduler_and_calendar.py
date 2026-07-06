"""Tests for the deterministic tool logic behind the scheduler and calendar
agents/tools. Neither Gemini nor real Google Calendar OAuth is involved here:
scheduler is pure Python, and the calendar tool is exercised with an injected
fake service object.
"""

from uniguide.agents.scheduler import build_scheduler
from uniguide.models.plan import SemesterPlan
from uniguide.models.student import StudentProfile
from uniguide.tools.calendar_tool import _semester_start_date, create_semester_events_tool
from uniguide.tools.db_tool import write_student_profile
from uniguide.tools.scheduler_tool import build_semester_plan_tool

# Matches what every _semester_start_date(1, ...) assertion below expects —
# create_semester_events_tool now reads start_year/start_season from the
# student's own profile rather than a global constant.
_TEST_START_YEAR = 2024
_TEST_START_SEASON = "winter"


def _course(course_id, credits, semester_offered, prerequisites_met=True, relevance_score=0.9):
    return {
        "course_id": course_id,
        "title": course_id,
        "credits": credits,
        "relevance_score": relevance_score,
        "rationale": "fits your interests",
        "semester_offered": semester_offered,
        "prerequisites_met": prerequisites_met,
    }


def _write_test_profile(student_id="s1"):
    write_student_profile(
        StudentProfile(
            student_id=student_id,
            name="Test Student",
            program="Test Program",
            semesters_completed=0,
            start_year=_TEST_START_YEAR,
            start_season=_TEST_START_SEASON,
        )
    )


def test_build_semester_plan_respects_credit_cap_and_semester_offered():
    candidates = [
        _course("A", 6, [1, 3]),
        _course("B", 6, [1, 3]),
        _course("C", 6, [1, 3]),
        _course("D", 6, [1, 3]),
        _course("E", 6, [1, 3]),
        _course("F", 6, [2, 4]),
    ]

    result = build_semester_plan_tool(
        student_id="s1",
        credits_remaining=12,
        completed_course_ids=[],
        candidate_courses=candidates,
        current_semester=1,
        max_credits_per_semester=12,
    )

    assert result["success"] is True
    plan = result["semester_plan"]
    assert len(plan["semesters"]) == 1  # 12 credits needed, 12-credit cap -> done in one semester
    for block in plan["semesters"]:
        assert block["total_credits"] <= 12
    scheduled_ids = {c["course_id"] for block in plan["semesters"] for c in block["courses"]}
    assert "F" not in scheduled_ids  # only offered in even slots, not needed once credits_remaining is met
    assert plan["total_planned_credits"] >= 12


def test_build_semester_plan_skips_unmet_prerequisites():
    candidates = [_course("A", 6, [1], prerequisites_met=False)]

    result = build_semester_plan_tool(
        student_id="s1",
        credits_remaining=6,
        completed_course_ids=[],
        candidate_courses=candidates,
        current_semester=1,
    )

    assert result["success"] is False


def test_build_semester_plan_excludes_already_completed_courses():
    candidates = [_course("A", 6, [1]), _course("B", 6, [1])]

    result = build_semester_plan_tool(
        student_id="s1",
        credits_remaining=6,
        completed_course_ids=["A"],
        candidate_courses=candidates,
        current_semester=1,
    )

    assert result["success"] is True
    scheduled_ids = {c["course_id"] for block in result["semester_plan"]["semesters"] for c in block["courses"]}
    assert scheduled_ids == {"B"}


def test_scheduler_agent_constructs_with_bound_tool():
    scheduler = build_scheduler(
        student_id="s1",
        credits_remaining=12,
        completed_course_ids=[],
        candidate_courses=[_course("A", 6, [1])],
        current_semester=1,
    )

    assert scheduler.output_schema is SemesterPlan
    assert scheduler.output_key == "semester_plan"
    assert [t.__name__ for t in scheduler.tools] == ["schedule_courses_tool"]
    assert scheduler.tools[0]() == build_semester_plan_tool(
        student_id="s1",
        credits_remaining=12,
        completed_course_ids=[],
        candidate_courses=[_course("A", 6, [1])],
        current_semester=1,
    )


class _FakeExecute:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeEvents:
    def __init__(self):
        self.inserted = []
        self.patched = []
        self.list_calls = []
        self._counter = 0

    def insert(self, calendarId, body):
        self._counter += 1
        event_id = f"evt-{self._counter}"
        self.inserted.append((calendarId, body))
        return _FakeExecute({"id": event_id})

    def patch(self, calendarId, eventId, body):
        self.patched.append((calendarId, eventId, body))
        return _FakeExecute({"id": eventId})

    def list(self, **kwargs):
        # Drift-recovery lookup always misses in tests — local DB is the
        # source of truth being exercised here, not live Calendar drift.
        self.list_calls.append(kwargs)
        return _FakeExecute({"items": []})


class _FakeCalendarService:
    def __init__(self):
        self._events = _FakeEvents()

    def events(self):
        return self._events


def _pin_today(monkeypatch, calendar_module, day):
    monkeypatch.setattr(calendar_module, "_today", lambda: day)


def test_create_semester_events_tool_fills_in_event_ids(monkeypatch):
    import uniguide.tools.calendar_tool as calendar_module
    from datetime import date

    _pin_today(monkeypatch, calendar_module, date(2024, 9, 1))  # before semester 1 starts
    _write_test_profile()

    fake_service = _FakeCalendarService()
    plan = {
        "student_id": "s1",
        "semesters": [
            {
                "semester_number": 1,
                "total_credits": 6,
                "calendar_event_ids": [],
                "courses": [_course("A", 6, [1])],
            }
        ],
        "total_planned_credits": 6,
        "graduation_semester": 1,
    }

    result = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)

    assert result["success"] is True
    block = result["semester_plan"]["semesters"][0]
    assert block["calendar_event_ids"] == ["evt-1"]
    assert result["results"] == [
        {"course_id": "A", "status": "created", "calendar_event_id": "evt-1", "note": None}
    ]
    assert len(fake_service._events.inserted) == 1
    _, body = fake_service._events.inserted[0]
    assert body["start"]["date"] == _semester_start_date(1, _TEST_START_YEAR, _TEST_START_SEASON).isoformat()
    assert body["extendedProperties"]["private"]["uniguide_course_id"] == "A"


def test_create_semester_events_tool_creates_recurring_event_for_scheduled_course(monkeypatch):
    from datetime import date, datetime

    import uniguide.tools.calendar_tool as calendar_module

    _pin_today(monkeypatch, calendar_module, date(2024, 9, 1))  # before semester 1 starts
    _write_test_profile()

    fake_service = _FakeCalendarService()
    course = _course("A", 6, [1])
    course["day_of_week"] = "Wed"
    course["start_time"] = "10:00"
    course["end_time"] = "12:00"
    plan = {
        "student_id": "s1",
        "semesters": [
            {
                "semester_number": 1,
                "total_credits": 6,
                "calendar_event_ids": [],
                "courses": [course],
            }
        ],
        "total_planned_credits": 6,
        "graduation_semester": 1,
    }

    result = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)

    assert result["success"] is True
    _, body = fake_service._events.inserted[0]
    assert body["start"]["dateTime"].endswith("T10:00:00")
    assert body["end"]["dateTime"].endswith("T12:00:00")
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;COUNT=14"]
    event_date = datetime.fromisoformat(body["start"]["dateTime"]).date()
    assert event_date.weekday() == 2  # Wednesday
    assert event_date >= _semester_start_date(1, _TEST_START_YEAR, _TEST_START_SEASON)


def test_create_semester_events_tool_degrades_gracefully_without_credentials(tmp_path, monkeypatch):
    from uniguide.config import settings

    monkeypatch.setattr(settings, "google_service_account_file", str(tmp_path / "missing.json"))

    plan = {"student_id": "s1", "semesters": [], "total_planned_credits": 0, "graduation_semester": 1}

    result = create_semester_events_tool(plan, plan_id=1)

    assert result["success"] is False
    assert "error" in result
    assert result["semester_plan"] == plan


def test_create_semester_events_tool_is_idempotent_on_resync(monkeypatch):
    import uniguide.tools.calendar_tool as calendar_module
    from datetime import date

    _pin_today(monkeypatch, calendar_module, date(2024, 9, 1))
    _write_test_profile()

    fake_service = _FakeCalendarService()
    plan = {
        "student_id": "s1",
        "semesters": [
            {
                "semester_number": 1,
                "total_credits": 6,
                "calendar_event_ids": [],
                "courses": [_course("A", 6, [1])],
            }
        ],
        "total_planned_credits": 6,
        "graduation_semester": 1,
    }

    first = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)
    second = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)

    assert first["success"] is True and second["success"] is True
    assert len(fake_service._events.inserted) == 1  # no duplicate created on re-sync
    assert second["results"] == [
        {"course_id": "A", "status": "already_scheduled", "calendar_event_id": "evt-1", "note": None}
    ]
    assert second["semester_plan"]["semesters"][0]["calendar_event_ids"] == ["evt-1"]


def test_create_semester_events_tool_skips_expired_semester(monkeypatch):
    import uniguide.tools.calendar_tool as calendar_module
    from datetime import date

    _pin_today(monkeypatch, calendar_module, date(2026, 1, 1))  # long after semester 1 ends
    _write_test_profile()

    fake_service = _FakeCalendarService()
    plan = {
        "student_id": "s1",
        "semesters": [
            {
                "semester_number": 1,
                "total_credits": 6,
                "calendar_event_ids": [],
                "courses": [_course("A", 6, [1])],
            }
        ],
        "total_planned_credits": 6,
        "graduation_semester": 1,
    }

    result = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)

    assert result["success"] is True
    assert fake_service._events.inserted == []
    assert result["results"] == [
        {"course_id": "A", "status": "skipped_expired", "calendar_event_id": None, "note": None}
    ]
    assert result["semester_plan"]["semesters"][0]["calendar_event_ids"] == []


def test_create_semester_events_tool_flags_conflict_between_own_courses(monkeypatch):
    import uniguide.tools.calendar_tool as calendar_module
    from datetime import date

    _pin_today(monkeypatch, calendar_module, date(2024, 9, 1))
    _write_test_profile()

    fake_service = _FakeCalendarService()
    course_a = _course("A", 6, [1])
    course_a["day_of_week"] = "Wed"
    course_a["start_time"] = "10:00"
    course_a["end_time"] = "12:00"
    course_b = _course("B", 6, [1])
    course_b["day_of_week"] = "Wed"
    course_b["start_time"] = "11:00"  # overlaps course_a's 10:00-12:00
    course_b["end_time"] = "13:00"
    plan = {
        "student_id": "s1",
        "semesters": [
            {
                "semester_number": 1,
                "total_credits": 12,
                "calendar_event_ids": [],
                "courses": [course_a, course_b],
            }
        ],
        "total_planned_credits": 12,
        "graduation_semester": 1,
    }

    result = create_semester_events_tool(plan, plan_id=1, calendar_service=fake_service)

    assert result["success"] is True
    statuses = {r["course_id"]: r["status"] for r in result["results"]}
    assert statuses == {"A": "created", "B": "conflict_flagged"}
    assert len(fake_service._events.inserted) == 2  # still created, just flagged
    conflict_note = next(r["note"] for r in result["results"] if r["course_id"] == "B")
    assert "A" in conflict_note
