"""Manual smoke test for the full pipeline (course_recommender -> scheduler,
with profile_analysis computed directly from DB-stored grades). Makes real
LLM calls via the ADK agents (Groq by default, per LLM_PROVIDER), so it needs
GROQ_API_KEY (and GEMINI_API_KEY, for embeddings) set in uniguide/.env and
will take a few seconds per agent turn.

Usage (from the uniguide/ directory, venv active):
    python run_demo.py
"""

import json

from uniguide import runner

DATA_DIR_PROFILE = "data/sample_profile.json"
DATA_DIR_TRANSCRIPT = "data/sample_transcript.pdf"

print("=== Returning student (seeded from sample profile + transcript) ===")
result = runner.run(
    student_id="demo-student-001",
    current_semester=3,
    interests=["mlops"],
    seed_profile_path=DATA_DIR_PROFILE,
    seed_transcript_path=DATA_DIR_TRANSCRIPT,
)
print(json.dumps(result, indent=2))

print("\n=== Fresh student (no seed data, never seen before) ===")
result = runner.run(
    student_id="demo-student-new",
    current_semester=1,
    interests=["machine learning", "statistics"],
)
print(json.dumps(result, indent=2))
