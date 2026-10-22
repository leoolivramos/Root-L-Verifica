"""RNF-03 / RF-09..RF-11: deterministic verdict, tag and overall rules."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from reliability.schemas import ClaimType, ClaimVerdict, OverallStatus, Stance, TagCode
from reliability.verification.overall import classify_overall
from reliability.verification.rules import ClaimFacts, EvidenceFact, evaluate_claim
from reliability.verification.tags import ClaimOutcome, DocFacts, assign_tags

S, P, C, N = Stance.SUPPORTS, Stance.PARTIALLY_SUPPORTS, Stance.CONTRADICTS, Stance.NEUTRAL


def ev(domain, stance, rel=0.9, omits=False, verified=True):
    return EvidenceFact(domain, stance, rel, omits, verified)


def facts(evs, ctype=ClaimType.QUANTITATIVE_FACT, importance=2, time_sensitive=False):
    return ClaimFacts(ctype, importance, time_sensitive, tuple(evs))


@pytest.mark.parametrize(
    ("claim", "verdict", "rule"),
    [
        (facts([], ClaimType.OPINION), ClaimVerdict.NOT_VERIFIABLE, 1),
        (facts([ev("a.com", S)], ClaimType.PREDICTION), ClaimVerdict.NOT_VERIFIABLE, 1),
        (facts([]), ClaimVerdict.INCONCLUSIVE, 2),
        (facts([ev("a.com", S, rel=0.3)]), ClaimVerdict.INCONCLUSIVE, 2),  # irrelevant
        (facts([ev("a.com", S, verified=False)]), ClaimVerdict.INCONCLUSIVE, 2),  # unverified quote
        (facts([ev("a.com", N)]), ClaimVerdict.INCONCLUSIVE, 2),
        (facts([ev("a.com", C)]), ClaimVerdict.CONTRADICTED, 3),
        (facts([ev("a.com", C), ev("b.com", C)]), ClaimVerdict.CONTRADICTED, 3),
        (facts([ev("a.com", C), ev("b.com", S)]), ClaimVerdict.INCONCLUSIVE, 4),
        (facts([ev("a.com", C), ev("b.com", P)]), ClaimVerdict.INCONCLUSIVE, 4),
        (facts([ev("a.com", P)]), ClaimVerdict.PARTIALLY_CORROBORATED, 5),
        (facts([ev("a.com", P), ev("b.com", S)]), ClaimVerdict.PARTIALLY_CORROBORATED, 5),
        (facts([ev("a.com", S)]), ClaimVerdict.CORROBORATED, 6),
        (facts([ev("a.com", S), ev("b.com", S)]), ClaimVerdict.CORROBORATED, 6),
    ],
)
def test_verdict_table(claim, verdict, rule):
    r = evaluate_claim(claim)
    assert r.verdict is verdict
    assert r.rule_id == rule
    assert r.rationale.startswith(f"Regra {rule}")


def test_same_domain_counts_once_best_relevance_wins():
    r = evaluate_claim(facts([ev("a.com", S, 0.6), ev("a.com", C, 0.95)]))
    # only the most relevant evidence of the domain counts → contradicted, not conflicting
    assert r.verdict is ClaimVerdict.CONTRADICTED and r.valid_evidence == 1


def outcome(i, claim):
    return ClaimOutcome(i, f"alegação {i}", claim, evaluate_claim(claim))


def test_five_truths_one_lie_is_not_an_average():
    good = [outcome(i, facts([ev("a.com", S), ev("b.com", S)])) for i in range(5)]
    bad = outcome(9, facts([ev("x.com", C)]))
    verdicts = [o.result.verdict for o in [*good, bad]]
    res = classify_overall(verdicts, [])
    assert res.status is OverallStatus.CONTRADICTED
    assert "1 de 6" in res.reason


def V(*vs):
    return list(vs)


def test_overall_table():
    K, Pa, Inc, NV = (
        ClaimVerdict.CORROBORATED,
        ClaimVerdict.PARTIALLY_CORROBORATED,
        ClaimVerdict.INCONCLUSIVE,
        ClaimVerdict.NOT_VERIFIABLE,
    )
    assert classify_overall(V(), []).status is OverallStatus.INSUFFICIENT
    assert classify_overall(V(NV, NV), []).status is OverallStatus.INSUFFICIENT
    assert classify_overall(V(Inc, Inc), []).status is OverallStatus.INSUFFICIENT
    assert classify_overall(V(K, K), []).status is OverallStatus.WELL_CORROBORATED
    assert classify_overall(V(K, NV), []).status is OverallStatus.WELL_CORROBORATED
    caveat = classify_overall(V(K, K), [TagCode.FONTES_INDEPENDENTES_INSUFICIENTES])
    assert caveat.status is OverallStatus.CORROBORATED_WITH_CAVEATS
    # non-caveat tags (e.g. emotional appeal) do not downgrade
    assert classify_overall(V(K), [TagCode.APELO_EMOCIONAL]).status is OverallStatus.WELL_CORROBORATED
    assert classify_overall(V(K, Inc), []).status is OverallStatus.MIXED
    assert classify_overall(V(K, Pa), []).status is OverallStatus.MIXED
    assert classify_overall(V(Pa), []).status is OverallStatus.MIXED
    assert classify_overall(V(K, ClaimVerdict.CONTRADICTED, Inc), []).status is OverallStatus.CONTRADICTED


NOW = datetime(2026, 10, 22)


def codes(tags):
    return {t.code for t in tags}


def test_text_input_gets_origin_tag_url_without_metadata_gets_source_tag():
    t = assign_tags(DocFacts("text", document_text="x"), [], now=NOW)
    assert TagCode.ORIGEM_NAO_CONFIRMADA in codes(t)
    u = assign_tags(DocFacts("url", url="https://example.com/a", document_text="x"), [], now=NOW)
    assert TagCode.FONTE_NAO_IDENTIFICADA in codes(u)
    ok = assign_tags(
        DocFacts("url", url="https://example.com/a", publisher="Jornal", document_text="x"), [], now=NOW
    )
    assert not codes(ok)


@pytest.mark.parametrize(
    "url",
    [
        "https://bit.ly/abc",
        "http://192.0.2.10/login",
        "https://xn--pple-43d.com/",
        "https://noticia.example.tk/x",
        "https://example.com@evil.test/",
    ],
)
def test_suspicious_links(url):
    t = assign_tags(DocFacts("url", url=url, publisher="x", document_text="x"), [], now=NOW)
    assert TagCode.LINK_SUSPEITO in codes(t)


def test_subjective_tags_require_literally_verified_quotes():
    text = "Isso é um ABSURDO total! Uma vergonha sem tamanho! Eu garanto que é o melhor país."
    doc = DocFacts(
        "url",
        url="https://example.com/a",
        publisher="J",
        document_text=text,
        emotional_quotes=("Isso é um ABSURDO total!", "Uma vergonha sem tamanho!"),
        assertive_opinion_quotes=("é o melhor país",),
    )
    assert {TagCode.APELO_EMOCIONAL, TagCode.OPINIAO_COMO_FATO} <= codes(assign_tags(doc, [], now=NOW))
    # invented quotes are ignored
    fake = DocFacts(
        "url", url="https://example.com/a", publisher="J", document_text=text,
        emotional_quotes=("frase inventada um", "frase inventada dois"),
        assertive_opinion_quotes=("nada disso existe",),
    )
    assert not codes(assign_tags(fake, [], now=NOW))
    # a single emotional quote is not enough
    one = DocFacts(
        "url", url="https://example.com/a", publisher="J", document_text=text,
        emotional_quotes=("Isso é um ABSURDO total!",),
    )
    assert TagCode.APELO_EMOCIONAL not in codes(assign_tags(one, [], now=NOW))


def test_outdated_requires_old_date_and_time_sensitive_claim():
    old = NOW - timedelta(days=800)
    ts = outcome(1, facts([ev("a.com", S)], time_sensitive=True))
    not_ts = outcome(2, facts([ev("a.com", S)]))
    d = DocFacts("url", url="https://example.com/a", publisher="J", published_at=old, document_text="x")
    assert TagCode.DATA_DESATUALIZADA in codes(assign_tags(d, [ts], now=NOW))
    assert TagCode.DATA_DESATUALIZADA not in codes(assign_tags(d, [not_ts], now=NOW))
    recent = DocFacts("url", url="https://example.com/a", publisher="J", published_at=NOW, document_text="x")
    assert TagCode.DATA_DESATUALIZADA not in codes(assign_tags(recent, [ts], now=NOW))


def test_claim_level_tags():
    doc = DocFacts("url", url="https://example.com/a", publisher="J", document_text="x")
    outs = [
        outcome(1, facts([ev("a.com", C)])),  # contradiction
        outcome(2, facts([], importance=3)),  # insufficient evidence on important claim
        outcome(3, facts([], importance=1)),  # unimportant → no tag
        outcome(4, facts([ev("a.com", S)])),  # single independent source
        outcome(5, facts([ev("a.com", S), ev("b.com", S, omits=True)])),  # out of context
        outcome(6, facts([], ClaimType.OPINION)),  # not verifiable → no tags
    ]
    tags = assign_tags(doc, outs, now=NOW)
    by_claim = {(t.code, t.claim_id) for t in tags}
    assert (TagCode.CONTRADICAO_ENCONTRADA, 1) in by_claim
    assert (TagCode.EVIDENCIA_INSUFICIENTE, 2) in by_claim
    assert not any(cid == 3 for _, cid in by_claim)
    assert (TagCode.FONTES_INDEPENDENTES_INSUFICIENTES, 4) in by_claim
    assert (TagCode.FORA_DE_CONTEXTO, 5) in by_claim
    assert not any(cid == 6 for _, cid in by_claim)
    assert all(t.justification for t in tags)
