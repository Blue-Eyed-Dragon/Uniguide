"""Profile Analyst agent — transcript PDF -> ProfileAnalysis.

Wraps `tools.pdf_parse_tool` (deterministic extraction + credit/GPA math) behind
an LlmAgent so it fits the same agent pipeline as course_recommender and
scheduler. The LLM's job is orchestration, not arithmetic: it calls the parse
tool, then must return the tool's `profile_analysis` fields unchanged as its
structured output — the credit/GPA/weak-subject numbers must stay exactly as
computed by transcript_parser.analyze_grades, not re-derived by the model.
"""

from google.adk.agents import LlmAgent

from uniguide.config import agent_model
from uniguide.ingestion.catalog_ingestor import DEFAULT_CATALOG_PATH, load_courses
from uniguide.models.student import ProfileAnalysis
from uniguide.tools.pdf_parse_tool import pdf_parse_tool

INSTRUCTION = """\
You analyze a student's academic transcript PDF and report their current
academic standing.

Given a transcript PDF path, call `parse_transcript_tool` with that path.

- If it returns success=True, return its `profile_analysis` fields exactly as
  given — do not recompute credits, GPA, or weak/strong subjects yourself.
- If it returns success=False, explain the error is a parse failure and that
  the caller should fall back to manual profile entry; report all-zero /
  empty fields in that case (credits_completed=0, credits_remaining equal to
  the full degree total, empty subject and course-id lists, gpa=null).
"""


def parse_transcript_tool(pdf_path: str) -> dict:
    """Extract a ProfileAnalysis from a transcript PDF, tagging courses against
    the full course catalog so weak/strong subjects can be computed.

    Args:
        pdf_path: path to the transcript (Notenspiegel) PDF.

    Returns:
        Same shape as `tools.pdf_parse_tool.pdf_parse_tool`.
    """
    catalog = load_courses(DEFAULT_CATALOG_PATH)
    return pdf_parse_tool(pdf_path, catalog=catalog)


profile_analyst = LlmAgent(
    name="profile_analyst",
    model=agent_model(),
    description="Extracts a structured academic profile from a transcript PDF.",
    instruction=INSTRUCTION,
    tools=[parse_transcript_tool],
    output_schema=ProfileAnalysis,
    output_key="profile_analysis",
)
