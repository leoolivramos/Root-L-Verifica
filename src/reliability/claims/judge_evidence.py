"""Step 6: judge one source passage against one claim (LLM, structured, quote-verified)."""

from __future__ import annotations

from reliability.claims.llm import LLMGateway, Usage
from reliability.claims.prompts import JUDGE_SYSTEM, judge_user_message
from reliability.ingestion.sanitize import clean_untrusted, wrap_untrusted
from reliability.schemas import EvidenceJudgement


async def judge_evidence(
    gateway: LLMGateway, claim_text: str, passage: str
) -> tuple[EvidenceJudgement, Usage]:
    cleaned = clean_untrusted(passage)
    return await gateway.structured(
        EvidenceJudgement,
        system=JUDGE_SYSTEM,
        user=judge_user_message(clean_untrusted(claim_text), wrap_untrusted(passage)),
        source_text=cleaned,
    )
