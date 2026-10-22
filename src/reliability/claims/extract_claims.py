"""Step 3: claim extraction (LLM, structured)."""

from __future__ import annotations

import re

from reliability.claims.llm import LLMGateway, Usage
from reliability.claims.prompts import EXTRACT_SYSTEM, extract_user_message
from reliability.ingestion.sanitize import clean_untrusted, wrap_untrusted
from reliability.schemas import Depth, ExtractionResult

MAX_CLAIMS = {Depth.FAST: 5, Depth.DEEP: 10}


def _key(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


async def extract_claims(
    gateway: LLMGateway, doc_text: str, depth: Depth
) -> tuple[ExtractionResult, Usage]:
    """Extract claims from the (already truncated) document text."""
    cleaned = clean_untrusted(doc_text)
    max_claims = MAX_CLAIMS[depth]
    result, usage = await gateway.structured(
        ExtractionResult,
        system=EXTRACT_SYSTEM,
        user=extract_user_message(wrap_untrusted(doc_text), max_claims),
        source_text=cleaned,
    )
    # de-duplicate and cap, keeping the most important first
    seen: set[str] = set()
    unique = []
    for c in result.claims:
        k = _key(c.text)
        if k and k not in seen:
            seen.add(k)
            unique.append(c)
    unique.sort(key=lambda c: -c.importance)  # stable: keeps document order inside a level
    result.claims = unique[:max_claims]
    return result, usage
