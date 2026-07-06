"""Tests for the deterministic tool logic behind the two LlmAgents.

These do not call Gemini (no GEMINI_API_KEY needed / configured in CI) — they
exercise `parse_transcript_tool` and `search_courses_tool`, the wrapper tools
each agent calls, which is where all the actual data logic lives. The agents
themselves (`profile_analyst`, `course_recommender`) only add LLM
orchestration on top and are exercised via `test_*_agent_constructs` below.
"""

from uniguide.agents.course_recommender import course_recommender, search_courses_tool
from uniguide.agents.profile_analyst import parse_transcript_tool, profile_analyst
from uniguide.ingestion.catalog_ingestor import ingest_catalog
from uniguide.models.course import CourseRecommendation
from uniguide.models.student import ProfileAnalysis
from uniguide.tests.conftest import make_transcript_pdf


def test_profile_analyst_agent_constructs():
    assert profile_analyst.output_schema is ProfileAnalysis
    assert profile_analyst.output_key == "profile_analysis"


def test_course_recommender_agent_constructs():
    assert course_recommender.output_schema == list[CourseRecommendation]
    assert course_recommender.output_key == "course_recommendations"


def test_parse_transcript_tool_tags_weak_and_strong_subjects(tmp_path):
    pdf_path = tmp_path / "transcript.pdf"
    make_transcript_pdf(
        pdf_path,
        rows=[
            ("DS101", "Statistical Learning", "6", "1,7", "1"),
            ("DS302", "Optimisation Methods", "5", "3,3", "2"),
        ],
    )

    result = parse_transcript_tool(str(pdf_path))

    assert result["success"] is True
    analysis = result["profile_analysis"]
    assert analysis["credits_completed"] == 11
    assert "statistics" in analysis["strong_subjects"]
    assert "math" in analysis["weak_subjects"]


def test_parse_transcript_tool_reports_failure_for_unparseable_pdf(tmp_path):
    bad_path = tmp_path / "missing.pdf"

    result = parse_transcript_tool(str(bad_path))

    assert result["success"] is False
    assert "error" in result


def test_search_courses_tool_marks_prerequisites_met():
    ingest_catalog()

    result = search_courses_tool(
        "deep learning",
        completed_course_ids=["DS101", "DS102"],
        top_k=5,
    )

    assert result["success"] is True
    by_id = {c["course_id"]: c for c in result["courses"]}
    assert "DS103" in by_id
    assert by_id["DS103"]["prerequisites_met"] is True


def test_search_courses_tool_flags_unmet_prerequisites():
    ingest_catalog()

    result = search_courses_tool(
        "deep learning",
        completed_course_ids=[],
        top_k=5,
    )

    by_id = {c["course_id"]: c for c in result["courses"]}
    assert "DS103" in by_id
    assert by_id["DS103"]["prerequisites_met"] is False
