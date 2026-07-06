"""Interactive, persistent chat with the concierge agent.

Usage: python -m uniguide.chat --student-id ID

Unlike the 3-agent pipeline (agents.orchestrator), which uses a fresh
InMemorySessionService per call, this uses DatabaseSessionService pointed at
the same uniguide.db, keyed by a deterministic session_id per student — so
re-running this command resumes the same conversation instead of starting
over. DatabaseSessionService only exposes async session methods (no
*_sync convenience wrappers like InMemorySessionService has), so the
one-time session lookup/creation below goes through asyncio.run(); the
per-turn Runner.run() call is a plain sync generator regardless of which
session service backs it.
"""

import asyncio

import click
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from uniguide.agents.concierge import concierge
from uniguide.config import settings
from uniguide.db.database import init_db

APP_NAME = "uniguide"


def _get_or_create_session(session_service: DatabaseSessionService, student_id: str, session_id: str):
    async def _resolve():
        existing = await session_service.get_session(
            app_name=APP_NAME, user_id=student_id, session_id=session_id
        )
        if existing is not None:
            return existing, False
        created = await session_service.create_session(
            app_name=APP_NAME, user_id=student_id, session_id=session_id
        )
        return created, True

    return asyncio.run(_resolve())


@click.command()
@click.option("--student-id", required=True, help="The student's ID.")
def chat(student_id: str) -> None:
    """Chat with the concierge agent about this student's stored plan."""
    init_db()
    # DatabaseSessionService uses SQLAlchemy's async engine, which needs an async
    # driver (aiosqlite) — our own app DB (db/database.py) intentionally stays on
    # the sync sqlite:/// scheme, so only swap the scheme for this session store.
    async_db_url = settings.database_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    session_service = DatabaseSessionService(db_url=async_db_url)
    session_id = f"chat-{student_id}"

    _, is_new = _get_or_create_session(session_service, student_id, session_id)
    click.echo("New conversation started." if is_new else "Resuming your earlier conversation.")

    runner = Runner(app_name=APP_NAME, agent=concierge, session_service=session_service)

    def _send(text: str) -> None:
        message = types.Content(role="user", parts=[types.Part(text=text)])
        reply_text = ""
        for event in runner.run(user_id=student_id, session_id=session_id, new_message=message):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        reply_text = part.text
        click.echo(f"concierge> {reply_text}")

    if is_new:
        _send("Hello, I'd like to plan my courses.")

    click.echo("Ask about your plan (type 'exit' or 'quit' to leave).")
    while True:
        try:
            user_input = click.prompt("you", prompt_suffix="> ")
        except (EOFError, click.exceptions.Abort):
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break

        _send(user_input)


if __name__ == "__main__":
    chat()
