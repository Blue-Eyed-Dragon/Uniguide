"""A BaseLlm that tries several LiteLlm-backed candidates in order.

Groq and Gemini's free tiers both cap usage (per-minute/per-day quota, or a
revoked/invalid key). Rather than surfacing that as a crashed agent turn,
FallbackLlm walks a list of candidate models — e.g. every configured Groq
key, then every configured Gemini key — and only raises once every candidate
has failed. Any exception from a candidate triggers the fallback (not just
quota/auth-specific errors), since a candidate failing for any reason should
still let the next one have a try.
"""

import logging
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger(__name__)


class FallbackLlm(BaseLlm):
    """Delegates to the first candidate that doesn't raise."""

    candidates: list[LiteLlm]

    def __init__(self, candidates: list[LiteLlm]):
        if not candidates:
            raise ValueError("FallbackLlm needs at least one candidate model.")
        super().__init__(model=candidates[0].model, candidates=candidates)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last_exc: Exception | None = None
        for i, candidate in enumerate(self.candidates):
            try:
                # LiteLlm.generate_content_async uses `llm_request.model or self.model`,
                # so a model already stamped onto the (shared, mutable) request by an
                # earlier candidate — or by ADK's flow using this wrapper's own .model —
                # would otherwise silently win over every later candidate's own model.
                llm_request.model = candidate.model
                async for response in candidate.generate_content_async(llm_request, stream=stream):
                    yield response
                return
            except Exception as exc:  # noqa: BLE001 - intentionally broad, see module docstring
                last_exc = exc
                logger.warning(
                    "LLM candidate %d/%d (%s) failed, falling back: %s",
                    i + 1,
                    len(self.candidates),
                    candidate.model,
                    exc,
                )
        raise last_exc
