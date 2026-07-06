"""Transcript (Notenspiegel) PDF -> ProfileAnalysis.

TU Dortmund's BOSS export is a grade table with columns roughly matching
Modulnummer / Modulbezeichnung / ECTS(LP) / Note / Semester. Column headers
vary by export, so we match on keyword rather than exact position.

Grading is the German 1.0 (best) - 5.0 (fail) scale, so "weak" means a grade
*above* the threshold, not below it.
"""

from pathlib import Path

import pdfplumber

from uniguide.config import settings
from uniguide.models.course import Course
from uniguide.models.student import Grade, ProfileAnalysis

_HEADER_ALIASES = {
    "course_id": ["modulnummer", "nr", "nr.", "code", "course_id", "module id"],
    "title": ["modulbezeichnung", "modul", "titel", "title", "course", "veranstaltung"],
    "ects": ["ects", "lp", "leistungspunkte", "credits", "cp"],
    "grade": ["note", "grade", "endnote"],
    "semester": ["semester", "fachsemester"],
}


class TranscriptParseError(Exception):
    """Raised when no grade table can be extracted from the PDF."""


def _match_column(header_cell: str | None) -> str | None:
    if not header_cell:
        return None
    normalized = header_cell.strip().lower()
    for field, aliases in _HEADER_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            return field
    return None


def _parse_grade_value(raw: str) -> float | None:
    try:
        return float(raw.strip().replace(",", "."))
    except (ValueError, AttributeError):
        return None


def extract_grades_from_pdf(pdf_path: str | Path) -> list[Grade]:
    grades: list[Grade] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header = table[0]
                column_map = {i: _match_column(cell) for i, cell in enumerate(header)}
                if "title" not in column_map.values() or "grade" not in column_map.values():
                    continue  # not the grades table

                for row in table[1:]:
                    fields = {}
                    for i, cell in enumerate(row):
                        field = column_map.get(i)
                        if field:
                            fields[field] = (cell or "").strip()

                    grade_value = _parse_grade_value(fields.get("grade", ""))
                    if grade_value is None or not fields.get("title"):
                        continue  # skip rows without a passed/graded module

                    ects_raw = fields.get("ects", "0").replace(",", ".")
                    try:
                        ects = int(float(ects_raw)) if ects_raw else 0
                    except ValueError:
                        ects = 0

                    semester_raw = fields.get("semester", "")
                    try:
                        semester = int(semester_raw) if semester_raw else None
                    except ValueError:
                        semester = None

                    grades.append(
                        Grade(
                            course_id=fields.get("course_id") or fields["title"][:12],
                            course_title=fields["title"],
                            ects=ects,
                            grade=grade_value,
                            semester=semester,
                        )
                    )

    if not grades:
        raise TranscriptParseError(
            f"No grade table found in {pdf_path}. Falls back to manual input mode."
        )

    return grades


def derive_semesters_completed(grades: list[Grade]) -> int:
    """The highest semester number with a recorded grade, or 0 if none.

    This is the authoritative floor for a student's progress — callers that
    also take a student-stated "which semester are you planning for" value
    (agents/concierge.py::set_planning_context_tool,
    agents/orchestrator.py::run_pipeline) must never let semesters_completed
    fall below this, or a single conversation defaulting to/stating an early
    semester silently erases previously recorded progress.
    """
    semesters = [g.semester for g in grades if g.semester is not None]
    return max(semesters, default=0)


def analyze_grades(
    grades: list[Grade],
    catalog: list[Course] | None = None,
    weak_threshold: float = settings.weak_grade_threshold,
) -> ProfileAnalysis:
    credits_completed = sum(g.ects for g in grades)
    credits_remaining = max(settings.degree_total_ects - credits_completed, 0)

    graded = [g for g in grades if g.grade is not None]
    gpa = round(sum(g.grade for g in graded) / len(graded), 2) if graded else None

    weak_subjects: list[str] = []
    strong_subjects: list[str] = []
    if catalog:
        tags_by_course = {c.course_id: c.tags for c in catalog}
        tag_grades: dict[str, list[float]] = {}
        for g in graded:
            for tag in tags_by_course.get(g.course_id, []):
                tag_grades.setdefault(tag, []).append(g.grade)

        for tag, values in tag_grades.items():
            avg = sum(values) / len(values)
            if avg > weak_threshold:
                weak_subjects.append(tag)
            else:
                strong_subjects.append(tag)

    return ProfileAnalysis(
        credits_completed=credits_completed,
        credits_remaining=credits_remaining,
        completed_course_ids=[g.course_id for g in grades],
        weak_subjects=weak_subjects,
        strong_subjects=strong_subjects,
        gpa=gpa,
    )


def parse_transcript(
    pdf_path: str | Path, catalog: list[Course] | None = None
) -> ProfileAnalysis:
    grades = extract_grades_from_pdf(pdf_path)
    return analyze_grades(grades, catalog=catalog)


if __name__ == "__main__":
    import sys

    result = parse_transcript(sys.argv[1])
    print(result.model_dump_json(indent=2))
