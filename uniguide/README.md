# 🎓 UniGuide

**An AI multi-agent course-planning concierge.** UniGuide turns a student's transcript
and interests into a personalized, semester-by-semester degree plan — then pushes it
straight to their Google Calendar, all through one continuous conversation.

Kaggle "5-Day AI Agents Intensive" submission.

## Built with

| Package | What it's for |
|---|---|
| **Google ADK** | Multi-agent orchestration — defines the `concierge` agent, its tools, and session/conversation state. |
| **LiteLLM** | Swappable LLM backend — the same agent code runs on Groq, Gemini, or Claude, with automatic fallback across keys/providers. |
| **ChromaDB** | Vector search over the course catalog — powers semantic "find courses relevant to this student" retrieval. |
| **FastAPI** | The web backend serving the dashboard + chat to the React frontend. |
| **Google Calendar API** (`google-api-python-client`) | Pushes a generated plan to a real calendar as recurring weekly class events. |

## What the agent does in the frontend

Opening a student's dashboard shows a **"Student Guide"** button that opens a chat
panel — this is the `concierge` agent, running as one continuous conversation for
that student (their identity is bound to the chat session itself, never something
they type, so the agent can never be tricked into acting as a different student).

**If the student has no plan yet**, the agent walks them through building one:
1. It asks which semester they're planning for and what they want to focus on —
   but it doesn't interrogate blindly. It already knows the student's actual academic
   progress (derived from their real grade records, not guesswork), so if they just
   say "plan my next semester," it uses that automatically instead of asking them to
   repeat information it already has.
2. It searches the course catalog for options that fit their stated interests and
   weak subjects, excluding anything they've already completed or don't yet meet the
   prerequisites for.
3. For each course it recommends, it writes a short, specific reason tied to *that
   student* — not a generic course blurb.
4. It schedules the picks into semesters under a credit-load cap, and presents the
   result conversationally: course by course, with credits, whether it's required,
   the reasoning, and the enrollment link.

**If a plan already exists**, the agent switches to answering follow-up questions —
"why not X sooner," "what electives are left," "how many credits do I still need" —
always grounded in the same real data, never a guess.

**Calendar sync only happens when the student explicitly asks for it in the chat**
(e.g. "add this to my calendar"). The agent checks the student's actual last message
for that intent before doing anything — it will never sync proactively, not even
right after building a plan. Once it does sync, it reports back honestly per course:
newly created, already on the calendar, updated, flagged as conflicting with another
class, or skipped because that semester's already over — never just "done."

## Quick start

```bash
cd uniguide
cp .env.example .env   # fill in API keys (see comments in the file)
uv venv && uv pip install -r requirements.txt
```

```bash
uvicorn uniguide.api.main:app --reload --port 8000   # backend — from the repo root
cd frontend && npm install && npm run dev             # frontend — separate terminal
```

Open `http://localhost:5173/students/<student_id>`.
