"""FastAPI app for the UniGuide web frontend.

Run from the repo root (same convention as `python -m uniguide.chat`):
    uvicorn uniguide.api.main:app --reload

Routers are split by whether they touch the LLM: `routers.dashboard` is
pure DB reads (safe to hit regardless of Groq/Gemini quota), `routers.chat`
and `routers.calendar` are LLM/OAuth-dependent.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uniguide.api.routers import calendar, chat, dashboard
from uniguide.db.database import init_db
from uniguide.db.schema_check import check_schema_up_to_date

# Vite's default dev server origin.
DEV_FRONTEND_ORIGINS = ["http://localhost:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    check_schema_up_to_date()
    yield


app = FastAPI(title="UniGuide API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
