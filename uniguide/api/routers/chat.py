"""Chat endpoints for the Student Guide overlay.

`chat/context` is a real, non-LLM endpoint (same read_student_profile /
read_latest_semester_plan calls dashboard.py uses) so the frontend can pick
planning-mode vs follow-up-mode framing without spending any Groq/Gemini
tokens.

`POST /chat` drives the real `concierge` agent via ADK's Runner, using
`run_async`/the session service's native async methods directly (a FastAPI
route is already async and doesn't need chat.py's asyncio.run() bridge for a
sync CLI context). The web chat gets its own session per browser page load
(`body.session_token`, generated client-side) rather than reusing
uniguide/chat.py's fixed `chat-{student_id}` CLI session, since a web page
refresh should start a fresh conversation instead of resuming one that could
be arbitrarily old.

The concierge's tools read student_id from ToolContext.session.user_id (see
agents/concierge.py) rather than trusting an LLM-supplied argument, so
Runner.run_async(user_id=student_id, ...) below is what actually authenticates
every tool call in the conversation — no priming/reminder text needed.
"""

from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from fastapi import APIRouter

from uniguide.agents.concierge import concierge
from uniguide.api.schemas import ChatContextResponse, ChatRequest, ChatResponse
from uniguide.config import settings
from uniguide.tools.db_tool import read_latest_semester_plan, read_student_profile

router = APIRouter(tags=["chat"])

APP_NAME = "uniguide"

_session_service: DatabaseSessionService | None = None
_runner: Runner | None = None


def _get_runner() -> tuple[DatabaseSessionService, Runner]:
    """Lazily build one long-lived session service + runner for the process,
    same as chat.py does for its CLI session (avoids reopening the async
    sqlite engine on every request).
    """
    global _session_service, _runner
    if _runner is None:
        async_db_url = settings.database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
        _session_service = DatabaseSessionService(db_url=async_db_url)
        _runner = Runner(app_name=APP_NAME, agent=concierge, session_service=_session_service)
    return _session_service, _runner


@router.get("/students/{student_id}/chat/context", response_model=ChatContextResponse)
def get_chat_context(student_id: str) -> ChatContextResponse:
    profile = read_student_profile(student_id)
    plan = read_latest_semester_plan(student_id)
    return ChatContextResponse(profile=profile, semester_plan=plan)


@router.post("/students/{student_id}/chat", response_model=ChatResponse)
async def post_chat(student_id: str, body: ChatRequest) -> ChatResponse:
    session_service, runner = _get_runner()
    session_id = f"chat-{student_id}-{body.session_token}" if body.session_token else f"chat-{student_id}"

    existing = await session_service.get_session(app_name=APP_NAME, user_id=student_id, session_id=session_id)
    if existing is None:
        await session_service.create_session(app_name=APP_NAME, user_id=student_id, session_id=session_id)

    message = types.Content(role="user", parts=[types.Part(text=body.message)])
    reply_text = ""
    async for event in runner.run_async(user_id=student_id, session_id=session_id, new_message=message):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    reply_text = part.text

    return ChatResponse(reply=reply_text)
