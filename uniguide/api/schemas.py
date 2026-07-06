"""API-only response shapes that combine existing models/ types — not
duplicating them, just composing what the dashboard needs in one response.
"""

from datetime import date

from pydantic import BaseModel

from uniguide.models.plan import SemesterPlan
from uniguide.models.student import ProfileAnalysis, StudentProfile


class StudentDashboardResponse(BaseModel):
    profile: StudentProfile
    analysis: ProfileAnalysis
    current_semester: int
    current_semester_start_date: date


class PlanResponse(BaseModel):
    plan: SemesterPlan | None


class ChatContextResponse(BaseModel):
    profile: StudentProfile | None
    semester_plan: SemesterPlan | None


class ChatRequest(BaseModel):
    message: str
    # Generated fresh by the frontend on every page load (not persisted client-side),
    # so a browser refresh starts a new conversation instead of resuming the last one.
    # Omit it (e.g. calling the API directly) to fall back to the one persistent
    # per-student session uniguide/chat.py's CLI also uses.
    session_token: str | None = None


class ChatResponse(BaseModel):
    reply: str
