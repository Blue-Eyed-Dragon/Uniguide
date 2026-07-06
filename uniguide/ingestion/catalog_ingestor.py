"""CSV course catalog -> ChromaDB persistent collection.

CSV columns: course_id, title, description, ects, tags, semester_offered,
prerequisites, mandatory, link, day_of_week, start_time, end_time. tags /
semester_offered / prerequisites are semicolon-separated within a cell.
day_of_week/start_time/end_time are blank for courses with no fixed weekly
class time (e.g. thesis/independent-study entries).
"""

import csv
from pathlib import Path

import chromadb

from uniguide.config import settings
from uniguide.ingestion.embeddings import embed_texts
from uniguide.models.course import Course

COLLECTION_NAME = "courses"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_catalog.csv"


def _parse_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(";") if v.strip()]


def load_courses(csv_path: str | Path) -> list[Course]:
    courses = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            courses.append(
                Course(
                    course_id=row["course_id"],
                    title=row["title"],
                    description=row["description"],
                    ects=int(row["ects"]),
                    tags=_parse_list(row.get("tags", "")),
                    semester_offered=[
                        int(s) for s in _parse_list(row.get("semester_offered", ""))
                    ],
                    prerequisites=_parse_list(row.get("prerequisites", "")),
                    mandatory=row.get("mandatory", "false").strip().lower() == "true",
                    link=row.get("link", ""),
                    day_of_week=row.get("day_of_week", "").strip() or None,
                    start_time=row.get("start_time", "").strip() or None,
                    end_time=row.get("end_time", "").strip() or None,
                )
            )
    return courses


def get_chroma_client() -> chromadb.PersistentClient:
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


def ingest_catalog(csv_path: str | Path = DEFAULT_CATALOG_PATH) -> int:
    courses = load_courses(csv_path)

    client = get_chroma_client()
    existing = {c.name for c in client.list_collections()}
    if COLLECTION_NAME in existing:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )

    documents = [f"{c.title}. {c.description}" for c in courses]
    embeddings = embed_texts(documents)
    metadatas = [
        {
            "title": c.title,
            "ects": c.ects,
            "tags": ";".join(c.tags),
            "semester_offered": ";".join(str(s) for s in c.semester_offered),
            "prerequisites": ";".join(c.prerequisites),
            "mandatory": c.mandatory,
            "link": c.link,
            # Chroma metadata can't store None, so blank string stands in for
            # "no fixed weekly class time" (see Course.day_of_week).
            "day_of_week": c.day_of_week or "",
            "start_time": c.start_time or "",
            "end_time": c.end_time or "",
        }
        for c in courses
    ]
    ids = [c.course_id for c in courses]

    collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    return len(courses)


if __name__ == "__main__":
    n = ingest_catalog()
    print(f"Ingested {n} courses into ChromaDB collection '{COLLECTION_NAME}' "
          f"at {settings.chroma_persist_dir}")
