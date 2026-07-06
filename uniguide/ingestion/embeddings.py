"""Shared embedding helper — used by catalog_ingestor at index time and by
Person B's rag_search_tool at query time. Keep both in sync: whichever provider
indexed the collection must also be used to embed the query.

settings.embedding_provider picks the backend:
- "gemini" (default): Gemini's gemini-embedding-001, requires GEMINI_API_KEY.
- "local": sentence-transformers, runs offline once the model is cached —
  used by tests (EMBEDDING_PROVIDER=local) so they don't need an API key.
"""

from functools import lru_cache

from uniguide.config import gemini_api_keys, settings


@lru_cache(maxsize=1)
def _local_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.local_embedding_model)


def _embed_texts_local(texts: list[str]) -> list[list[float]]:
    return [vec.tolist() for vec in _local_model().encode(texts)]


def _embed_texts_gemini(texts: list[str]) -> list[list[float]]:
    from google import genai

    keys = gemini_api_keys()
    last_exc: Exception | None = None
    for key in keys:
        try:
            client = genai.Client(api_key=key)
            response = client.models.embed_content(model="gemini-embedding-001", contents=texts)
            return [embedding.values for embedding in response.embeddings]
        except Exception as exc:  # noqa: BLE001 - try the next key regardless of failure reason
            last_exc = exc
    raise last_exc


def embed_texts(texts: list[str]) -> list[list[float]]:
    if settings.embedding_provider == "local":
        return _embed_texts_local(texts)
    return _embed_texts_gemini(texts)
