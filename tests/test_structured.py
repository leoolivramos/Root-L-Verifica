"""RF-06 / RNF-05: structured output, retries and quote verification."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from reliability.claims.extract_claims import extract_claims
from reliability.claims.judge_evidence import judge_evidence
from reliability.demo import FakeLLMGateway
from reliability.errors import StructuredOutputError
from reliability.schemas import Depth, EvidenceJudgement, ExtractionResult

DOC = "O PIB cresceu 2,9% em 2025 segundo o IBGE. A taxa de desemprego caiu para 6%. Muito bom."

GOOD = {
    "summary": "Resumo.",
    "claims": [
        {
            "text": "O PIB cresceu 2,9% em 2025 segundo o IBGE",
            "claim_type": "quantitative_fact",
            "verification_query": "PIB 2025 IBGE crescimento",
            "requires_external_evidence": True,
            "source_quote": "O PIB cresceu 2,9% em 2025 segundo o IBGE",
        }
    ],
}


def handler_factory(attempts):
    def handler(model, system, user, source_text):
        return attempts

    return handler


async def test_prose_then_valid_json_succeeds_on_third_attempt():
    gw = FakeLLMGateway(handler_factory(["Aqui estão as alegações: 1) ...", {"claims": "nope"}, GOOD]))
    res, usage = await extract_claims(gw, DOC, Depth.FAST)
    assert len(res.claims) == 1
    assert usage.prompt_tokens > 0 and usage.completion_tokens > 0  # telemetry counts every attempt
    assert gw.calls[0]["n_attempts"] == 3


async def test_continuous_failure_raises_structured_output_error_with_usage():
    gw = FakeLLMGateway(handler_factory(["lixo", "mais lixo", "ainda lixo", GOOD]))  # 4th never used
    with pytest.raises(StructuredOutputError) as ei:
        await extract_claims(gw, DOC, Depth.FAST)
    assert ei.value.prompt_tokens > 0
    assert "3 tentativas" in str(ei.value)


async def test_invented_source_quote_is_rejected():
    bad = {**GOOD, "claims": [{**GOOD["claims"][0], "source_quote": "frase que não existe no texto"}]}
    gw = FakeLLMGateway(handler_factory([bad, bad, bad]))
    with pytest.raises(StructuredOutputError):
        await extract_claims(gw, DOC, Depth.FAST)


async def test_quote_matching_is_whitespace_and_case_insensitive():
    ok = {**GOOD, "claims": [{**GOOD["claims"][0], "source_quote": "o pib  cresceu\n2,9% em 2025"}]}
    res, _ = await extract_claims(FakeLLMGateway(handler_factory([ok])), DOC, Depth.FAST)
    assert res.claims


async def test_duplicates_removed_and_capped():
    claims = [
        {**GOOD["claims"][0], "text": f"Fato número {i} distinto", "importance": 1 + i % 3}
        for i in range(9)
    ]
    claims.append({**GOOD["claims"][0], "text": "O PIB cresceu 2,9% em 2025 segundo o IBGE"})
    claims.append({**GOOD["claims"][0], "text": "o pib cresceu 2,9% em 2025, segundo o ibge!"})
    gw = FakeLLMGateway(handler_factory([{"claims": claims}]))
    res, _ = await extract_claims(gw, DOC, Depth.FAST)
    assert len(res.claims) == 5
    assert [c.importance for c in res.claims] == sorted((c.importance for c in res.claims), reverse=True)


def test_validators_without_context_do_not_enforce():
    # context-free validation (e.g. loading from DB) must not crash
    assert ExtractionResult.model_validate(GOOD).claims


def test_judgement_validation_bounds_and_quote():
    with pytest.raises(ValidationError):
        EvidenceJudgement.model_validate(
            {"stance": "supports", "relevance": 1.5, "exact_quote": "x"}, context={"source_text": "x"}
        )
    with pytest.raises(ValidationError):
        EvidenceJudgement.model_validate(
            {"stance": "supports", "relevance": 0.5, "exact_quote": "ausente"},
            context={"source_text": "texto da fonte"},
        )
    with pytest.raises(ValidationError):
        EvidenceJudgement.model_validate(
            {"stance": "banana", "relevance": 0.5, "exact_quote": "texto"},
            context={"source_text": "texto da fonte"},
        )


async def test_judge_evidence_quote_verified():
    passage = "A agência confirma o dado. Mais detalhes a seguir."
    good = {"stance": "supports", "relevance": 0.9, "exact_quote": "A agência confirma o dado."}
    j, _ = await judge_evidence(FakeLLMGateway(handler_factory([good])), "claim", passage)
    assert j.stance.value == "supports"
    bad = {**good, "exact_quote": "A agência desmente tudo."}
    with pytest.raises(StructuredOutputError):
        await judge_evidence(FakeLLMGateway(handler_factory([bad])), "claim", passage)
