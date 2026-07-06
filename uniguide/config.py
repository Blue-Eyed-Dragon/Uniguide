import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # comma-separated, any number of keys, tried in order as fallback. Accepts
    # either GEMINI_API_KEYS (plural, preferred) or GEMINI_API_KEY in the .env file.
    gemini_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GEMINI_API_KEYS", "GEMINI_API_KEY")
    )
    embedding_provider: str = "gemini"  # "gemini" or "local" (sentence-transformers)
    local_embedding_model: str = "all-MiniLM-L6-v2"
    gemini_model: str = "gemini-3.5-flash"

    # Which LLM backs the ADK agents (profile_analyst, course_recommender, scheduler).
    # "groq" (default), "gemini", or "claude" (fallbacks for local testing when the
    # Groq/Gemini free-tier quota is exhausted). Embeddings always use Gemini
    # regardless of this setting, since neither Claude nor Groq has an embeddings endpoint.
    llm_provider: str = "groq"
    anthropic_api_key: str | None = None
    claude_model: str = "claude-haiku-4-5"
    # comma-separated, any number of keys, tried in order as fallback. Accepts
    # either GROQ_API_KEYS (plural, preferred) or GROQ_API_KEY in the .env file.
    groq_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("GROQ_API_KEYS", "GROQ_API_KEY")
    )
    # llama-3.3-70b-versatile, not a reasoning model like qwen/deepseek-r1-distill —
    # those emit a `reasoning_content` field on assistant turns that Groq's own API
    # then rejects when ADK replays it back as conversation history on the next turn.
    groq_model: str = "llama-3.3-70b-versatile"

    # Either a service-account key JSON (Google Cloud Console -> IAM & Admin ->
    # Service Accounts -> Keys — no browser/OAuth flow, the calendar must be
    # shared with the key's client_email) or an OAuth client-secret JSON
    # (Google Cloud Console -> Credentials -> OAuth client ID -> Desktop app —
    # needs a one-time interactive consent, then caches a refreshable token).
    # tools/calendar_tool.py detects which kind this is from the file's own
    # contents. Provide these via the .env variables `GOOGLE_SERVICE_ACCOUNT_FILE`
    # (or the older `GOOGLE_OAUTH_CLIENT_SECRETS_FILE` name) and `GOOGLE_CALENDAR_ID`
    # instead of hardcoding defaults here.
    google_service_account_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_OAUTH_CLIENT_SECRETS_FILE"),
    )
    google_calendar_id: str | None = Field(
        default=None, validation_alias=AliasChoices("GOOGLE_CALENDAR_ID")
    )
    # TU Dortmund's fixed term-start month/day — global, deliberately no year
    # here. Each student's actual semester 1 date is winter_start_month_day
    # or summer_start_month_day of *their own* StudentProfile.start_year
    # (see tools/calendar_tool.py::_semester_start_date); semester numbers
    # alternate winter/summer every 6 months from there.
    winter_start_month_day: str = "10-01"
    summer_start_month_day: str = "04-01"
    semester_length_weeks: int = 14  # how many weekly occurrences a class's calendar event recurs for
    calendar_timezone: str = "Europe/Berlin"  # TU Dortmund's timezone; used for recurring class event times

    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'uniguide.db'}"
    chroma_persist_dir: str = str(BASE_DIR / "data" / "chroma")

    degree_total_ects: int = 120
    weak_grade_threshold: float = 2.7
    max_credits_per_semester: int = 30


settings = Settings()


def gemini_api_keys() -> list[str]:
    """The GEMINI_API_KEY setting, split on commas (any number of fallback keys)."""
    if not settings.gemini_api_key:
        return []
    return [key.strip() for key in settings.gemini_api_key.split(",") if key.strip()]


def groq_api_keys() -> list[str]:
    """The GROQ_API_KEY setting, split on commas (any number of fallback keys)."""
    if not settings.groq_api_key:
        return []
    return [key.strip() for key in settings.groq_api_key.split(",") if key.strip()]


if settings.gemini_api_key:
    # google-genai's Client reads the key straight from os.environ; pydantic-settings
    # only populates the Settings object, so export it for that SDK to find.
    os.environ.setdefault("GEMINI_API_KEY", gemini_api_keys()[0])

if settings.anthropic_api_key:
    # litellm/anthropic's SDK likewise reads straight from os.environ.
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

if settings.groq_api_key:
    # litellm's Groq integration likewise reads straight from os.environ.
    os.environ.setdefault("GROQ_API_KEY", groq_api_keys()[0])


def _gemini_candidates() -> list:
    """One LiteLlm candidate per configured Gemini key, each with its own key
    bound via the `api_key` kwarg (not the shared GEMINI_API_KEY env var), so
    they can be tried independently as fallbacks."""
    from google.adk.models.lite_llm import LiteLlm

    return [
        LiteLlm(model=f"gemini/{settings.gemini_model}", api_key=key, num_retries=3)
        for key in gemini_api_keys()
    ]


def _groq_candidates() -> list:
    """One LiteLlm candidate per configured Groq key, mirroring _gemini_candidates()."""
    from google.adk.models.lite_llm import LiteLlm

    return [
        LiteLlm(model=f"groq/{settings.groq_model}", api_key=key, num_retries=3)
        for key in groq_api_keys()
    ]


def agent_model():
    """The model value ADK LlmAgents should be constructed with.

    settings.llm_provider picks the primary backend: "groq" (default),
    "gemini", or "claude". The default "groq" chain falls back through every
    configured Groq key (GROQ_API_KEYS, comma-separated), then every
    configured Gemini key (GEMINI_API_KEYS, comma-separated), if a call fails
    for any reason (invalid/expired key, exhausted free-tier quota, etc.) —
    see uniguide.llm_fallback.FallbackLlm. Only once every candidate has
    failed does the agent turn actually error out.
    """
    from google.adk.models.lite_llm import LiteLlm

    from uniguide.llm_fallback import FallbackLlm

    # LiteLLM retries transient errors (e.g. a free-tier per-minute rate
    # limit) with backoff before giving up on a given candidate.
    if settings.llm_provider == "claude":
        return LiteLlm(model=f"anthropic/{settings.claude_model}", num_retries=3)
    if settings.llm_provider == "gemini":
        candidates = _gemini_candidates()
        return candidates[0] if len(candidates) == 1 else FallbackLlm(candidates)

    # Default "groq": every configured Groq key, then every configured Gemini key, in order.
    candidates = [*_groq_candidates(), *_gemini_candidates()]
    return candidates[0] if len(candidates) == 1 else FallbackLlm(candidates)
