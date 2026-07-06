"""ADK tool: semantic search over the course catalog ChromaDB collection.

Queries the same collection `ingestion.catalog_ingestor.ingest_catalog` builds,
embedding the query text with the same provider used at index time (see
`ingestion.embeddings`) so query and document vectors are comparable.
"""

from uniguide.ingestion.catalog_ingestor import COLLECTION_NAME, get_chroma_client
from uniguide.ingestion.embeddings import embed_texts


def _split(value: str) -> list[str]:
    return [v for v in value.split(";") if v]


def rag_search_tool(
    query: str,
    top_k: int = 5,
    completed_course_ids: list[str] | None = None,
) -> dict:
    """Semantically search the course catalog for courses relevant to a query.

    Args:
        query: natural-language description of what the student is looking for
            (e.g. an interest, a weak subject to shore up, a career goal).
        top_k: maximum number of courses to return.
        completed_course_ids: course_ids the student has already completed;
            these are excluded from the results.

    Returns:
        {"success": True, "courses": [{course_id, title, description,
        ects, tags, semester_offered, prerequisites, mandatory, link,
        day_of_week, start_time, end_time, relevance_score}, ...]} ranked by
        relevance_score (0-1, higher is more relevant), or {"success": False,
        "error": "..."} if the catalog hasn't been ingested yet.
        day_of_week/start_time/end_time are "" for courses with no fixed
        weekly class time (e.g. thesis entries).
    """
    completed = set(completed_course_ids or [])

    client = get_chroma_client()
    existing = {c.name for c in client.list_collections()}
    if COLLECTION_NAME not in existing:
        return {
            "success": False,
            "error": f"Collection '{COLLECTION_NAME}' not found — run catalog_ingestor first.",
        }
    collection = client.get_collection(COLLECTION_NAME)

    [query_embedding] = embed_texts([query])
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k + len(completed), collection.count()),
    )

    courses = []
    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for course_id, document, metadata, distance in zip(ids, documents, metadatas, distances):
        if course_id in completed:
            continue
        courses.append(
            {
                "course_id": course_id,
                "title": metadata["title"],
                "description": document,
                "ects": metadata["ects"],
                "tags": _split(metadata["tags"]),
                "semester_offered": [int(s) for s in _split(metadata["semester_offered"])],
                "prerequisites": _split(metadata["prerequisites"]),
                "mandatory": metadata["mandatory"],
                "link": metadata.get("link", ""),
                "day_of_week": metadata.get("day_of_week", ""),
                "start_time": metadata.get("start_time", ""),
                "end_time": metadata.get("end_time", ""),
                "relevance_score": round(max(1.0 - distance, 0.0), 4),
            }
        )
        if len(courses) == top_k:
            break

    return {"success": True, "courses": courses}
