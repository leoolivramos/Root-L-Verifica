"""RF-13 / RF-14: persistence, telemetry, feedback and CSV export."""

from __future__ import annotations

from reliability.config import PIPELINE_VERSION, PROMPT_VERSION
from reliability.schemas import AnalysisStatus, ClaimVerdict, OverallStatus, TagCode


def _new(repo):
    return repo.create_analysis(
        input_type="text",
        original_input="texto de teste",
        depth="rapida",
        pipeline_version=PIPELINE_VERSION,
        prompt_version=PROMPT_VERSION,
        model_name="m1",
        llm_base_url="http://x/v1",
    )


def test_full_lifecycle_and_report(repo):
    aid = _new(repo)
    assert repo.get_status(aid) == (AnalysisStatus.PENDING, "Na fila")
    repo.set_status(aid, AnalysisStatus.EXTRACTING, "Extraindo")
    repo.add_event(aid, "EXTRACTING", "Extraindo conteúdo")
    repo.update_meta(aid, title="T", domain="d.com", summary="S")
    repo.add_warning(aid, "w1")
    repo.add_warning(aid, "w1")  # de-duplicated
    cid = repo.save_claim(
        aid, text="c", claim_type="quantitative_fact", importance=3, time_sensitive=False,
        requires_external_evidence=True, verification_query="q", source_quote="c",
    )
    sid = repo.get_or_create_source(aid, url="https://a.com/x", title="A", domain="a.com", is_paywalled=True)
    assert repo.get_or_create_source(aid, url="https://a.com/x") == sid
    repo.add_evidence(cid, sid, stance="supports", relevance=0.9, exact_quote="q!", omits_context=False)
    repo.set_claim_verdict(cid, ClaimVerdict.CORROBORATED, "Regra 6")
    repo.save_tags(aid, [(TagCode.APELO_EMOCIONAL, "j1", None), (TagCode.FORA_DE_CONTEXTO, "j2", cid)])
    repo.finalize(
        aid, status=AnalysisStatus.COMPLETED, overall_status=OverallStatus.WELL_CORROBORATED,
        overall_reason="r", prompt_tokens=120, completion_tokens=45, processing_time_ms=987,
    )
    assert repo.is_terminal(aid)
    rep = repo.get_report(aid)
    assert rep.status is AnalysisStatus.COMPLETED and rep.overall_status is OverallStatus.WELL_CORROBORATED
    assert (rep.prompt_tokens, rep.completion_tokens, rep.processing_time_ms) == (120, 45, 987)
    assert (rep.pipeline_version, rep.prompt_version, rep.model_name) == (PIPELINE_VERSION, PROMPT_VERSION, "m1")
    assert rep.warnings == ["w1"] and rep.title == "T" and rep.summary == "S"
    assert [t.code for t in rep.tags] == [TagCode.APELO_EMOCIONAL]
    claim = rep.claims[0]
    assert claim.verification_status is ClaimVerdict.CORROBORATED and claim.rationale == "Regra 6"
    assert claim.evidences[0].exact_quote == "q!" and claim.evidences[0].is_paywalled
    assert [t.code for t in claim.tags] == [TagCode.FORA_DE_CONTEXTO]
    assert repo.list_events(aid)[0][1:] == ("EXTRACTING", "Extraindo conteúdo")


def test_feedback_and_history_csv(repo):
    a = _new(repo)
    b = _new(repo)
    repo.finalize(a, status=AnalysisStatus.COMPLETED, prompt_tokens=10, completion_tokens=5, processing_time_ms=100)
    repo.add_feedback(a, True, None)
    repo.add_feedback(b, False, "faltou contexto")
    assert repo.get_report(a).feedback_given
    df = repo.history_dataframe()
    assert list(df["id"]) == [b, a]  # newest first
    assert {"tokens_prompt", "tokens_resposta", "tempo_ms", "modelo", "pipeline", "prompt"} <= set(df.columns)
    assert df.set_index("id").loc[a, "tempo_ms"] == 100
    csv = df.to_csv(index=False)
    assert "faltou" not in csv and csv.splitlines()[0].startswith("id,")


def test_orphans_are_failed_on_startup(repo):
    a = _new(repo)
    repo.set_status(a, AnalysisStatus.INVESTIGATING, "Buscando")
    done = _new(repo)
    repo.finalize(done, status=AnalysisStatus.COMPLETED)
    assert repo.fail_orphans() == 1
    assert repo.get_status(a)[0] is AnalysisStatus.FAILED
    assert repo.get_status(done)[0] is AnalysisStatus.COMPLETED


def test_empty_history_dataframe(repo):
    assert repo.history_dataframe().empty
