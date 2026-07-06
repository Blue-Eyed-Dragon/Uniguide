"""ADK tool wrapper around ingestion.transcript_parser.

Returns a plain dict (JSON-serializable) as ADK function tools expect. On
parse failure, returns success=False so the calling agent / CLI can fall back
to manual input mode instead of crashing the pipeline.
"""

from uniguide.ingestion.transcript_parser import TranscriptParseError, parse_transcript
from uniguide.models.course import Course


def pdf_parse_tool(pdf_path: str, catalog: list[Course] | None = None) -> dict:
    """Extract a ProfileAnalysis from a TU Dortmund transcript (Notenspiegel) PDF.

    Args:
        pdf_path: path to the transcript PDF.
        catalog: optional course catalog, used to map completed courses to
            tags for weak/strong subject detection. Without it, those lists
            are empty.

    Returns:
        {"success": True, "profile_analysis": {...}} on success, or
        {"success": False, "error": "..."} on failure.
    """
    try:
        analysis = parse_transcript(pdf_path, catalog=catalog)
        return {"success": True, "profile_analysis": analysis.model_dump()}
    except (TranscriptParseError, FileNotFoundError) as exc:
        return {"success": False, "error": str(exc)}
