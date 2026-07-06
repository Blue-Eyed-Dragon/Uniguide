import csv

import fitz  # PyMuPDF
import pytest

from uniguide.tests.conftest import make_transcript_pdf
from uniguide.ingestion.catalog_ingestor import (
    COLLECTION_NAME,
    DEFAULT_CATALOG_PATH,
    get_chroma_client,
    ingest_catalog,
)
from uniguide.ingestion.transcript_parser import (
    TranscriptParseError,
    analyze_grades,
    extract_grades_from_pdf,
)
from uniguide.models.course import Course, CourseRecommendation
from uniguide.models.plan import SemesterBlock, SemesterPlan
from uniguide.models.student import Grade, StudentProfile
from uniguide.tools.credit_gap_tool import credit_gap_tool
from uniguide.tools.db_tool import (
    read_latest_semester_plan,
    read_student_profile,
    write_semester_plan,
    write_student_profile,
)
from uniguide.tools.rag_search_tool import rag_search_tool


def test_ingest_catalog_populates_chromadb():
    count = ingest_catalog()

    with open(DEFAULT_CATALOG_PATH, newline="", encoding="utf-8") as f:
        expected = sum(1 for _ in csv.DictReader(f))

    assert count == expected

    client = get_chroma_client()
    collection = client.get_collection(COLLECTION_NAME)
    assert collection.count() == expected


def test_rag_search_tool_ranks_relevant_courses_and_excludes_completed():
    ingest_catalog()

    result = rag_search_tool(
        "neural networks and deep learning",
        top_k=3,
        completed_course_ids=["DS103"],
    )

    assert result["success"] is True
    course_ids = [c["course_id"] for c in result["courses"]]
    assert "DS103" not in course_ids
    assert len(course_ids) == 3
    scores = [c["relevance_score"] for c in result["courses"]]
    assert scores == sorted(scores, reverse=True)


def test_rag_search_tool_reports_missing_collection():
    client = get_chroma_client()
    if COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(COLLECTION_NAME)

    result = rag_search_tool("anything")

    assert result["success"] is False
    assert "error" in result


def test_extract_grades_from_pdf_happy_path(tmp_path):
    pdf_path = tmp_path / "transcript.pdf"
    rows = [
        ("DS101", "Statistical Learning", "6", "1,7", "1"),
        ("DS201", "Big Data Systems", "6", "2,3", "1"),
    ]
    make_transcript_pdf(pdf_path, rows)

    grades = extract_grades_from_pdf(pdf_path)

    assert len(grades) == 2
    assert grades[0].course_id == "DS101"
    assert grades[0].course_title == "Statistical Learning"
    assert grades[0].ects == 6
    assert grades[0].grade == 1.7
    assert grades[0].semester == 1


def test_extract_grades_from_pdf_raises_on_pdf_without_table(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "No table here.")
    doc.save(pdf_path)
    doc.close()

    with pytest.raises(TranscriptParseError):
        extract_grades_from_pdf(pdf_path)


def test_analyze_grades_computes_credits_and_subjects():
    grades = [
        Grade(course_id="DS101", course_title="Statistical Learning", ects=6, grade=1.7, semester=1),
        Grade(course_id="DS302", course_title="Optimisation Methods", ects=5, grade=3.3, semester=2),
    ]
    catalog = [
        Course(course_id="DS101", title="Statistical Learning", description="d", ects=6, tags=["statistics", "ml"]),
        Course(course_id="DS302", title="Optimisation Methods", description="d", ects=5, tags=["math", "optimisation"]),
    ]

    analysis = analyze_grades(grades, catalog=catalog, weak_threshold=2.7)

    assert analysis.credits_completed == 11
    assert analysis.credits_remaining == 120 - 11
    assert set(analysis.strong_subjects) == {"statistics", "ml"}
    assert set(analysis.weak_subjects) == {"math", "optimisation"}
    assert analysis.gpa == round((1.7 + 3.3) / 2, 2)


def test_write_and_read_student_profile_roundtrip():
    profile = StudentProfile(
        student_id="s1",
        name="Test Student",
        program="MSc Data Science",
        semesters_completed=1,
        start_year=2024,
        start_season="winter",
        interests=["nlp"],
        grades=[
            Grade(course_id="DS101", course_title="Statistical Learning", ects=6, grade=1.7, semester=1)
        ],
    )
    write_student_profile(profile)

    loaded = read_student_profile("s1")

    assert loaded is not None
    assert loaded.name == "Test Student"
    assert loaded.interests == ["nlp"]
    assert len(loaded.grades) == 1
    assert loaded.grades[0].course_id == "DS101"


def test_read_student_profile_returns_none_when_missing():
    assert read_student_profile("does-not-exist") is None


def test_credit_gap_tool_computes_remaining_credits():
    profile = StudentProfile(
        student_id="s2",
        name="Another Student",
        program="MSc Data Science",
        semesters_completed=1,
        start_year=2024,
        start_season="winter",
        grades=[
            Grade(course_id="DS101", course_title="Statistical Learning", ects=6, grade=1.7, semester=1)
        ],
    )
    write_student_profile(profile)

    result = credit_gap_tool("s2")

    assert result["credits_completed"] == 6
    assert result["credits_remaining"] == 120 - 6
    assert result["degree_total_ects"] == 120


def test_write_and_read_semester_plan_roundtrip():
    write_student_profile(
        StudentProfile(
            student_id="s3",
            name="Plan Student",
            program="MSc Data Science",
            semesters_completed=2,
            start_year=2024,
            start_season="winter",
        )
    )

    plan = SemesterPlan(
        student_id="s3",
        semesters=[
            SemesterBlock(
                semester_number=3,
                total_credits=6,
                calendar_event_ids=["evt1"],
                courses=[
                    CourseRecommendation(
                        course_id="DS103",
                        title="Deep Learning",
                        credits=6,
                        relevance_score=0.9,
                        rationale="Matches your interest in deep learning.",
                        semester_offered=[1, 3],
                        prerequisites_met=True,
                    )
                ],
            )
        ],
        total_planned_credits=6,
        graduation_semester=4,
    )

    plan_id = write_semester_plan(plan)
    assert plan_id is not None

    loaded = read_latest_semester_plan("s3")

    assert loaded is not None
    assert loaded.graduation_semester == 4
    assert loaded.semesters[0].courses[0].course_id == "DS103"
    assert loaded.semesters[0].calendar_event_ids == ["evt1"]
