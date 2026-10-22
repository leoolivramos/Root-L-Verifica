"""Reliability Lab — Streamlit entry point.

Run:  uv run streamlit run app.py
The pipeline runs in a background thread (JobManager); the UI only polls the SQLite state, so it
never freezes and the "Cancelar Análise" button works at any moment.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Análise de confiabilidade",
    layout="wide",
    initial_sidebar_state="expanded",
)

from reliability.bootstrap import build_deps
from reliability.config import PIPELINE_VERSION, PROMPT_VERSION, get_settings
from reliability.errors import InvalidInput, ReliabilityError
from reliability.jobs import JobManager
from reliability.schemas import (
    TAG_LABELS,
    TERMINAL_STATUSES,
    AnalysisReport,
    AnalysisStatus,
    ClaimVerdict,
    Depth,
)
from reliability.ui_helpers import (
    CSS,
    STANCE_UI,
    esc,
    factcheck_badge,
    is_factcheck_domain,
    md_escape,
    safe_http_url,
    score_card,
    status_pill,
    stepper,
    tag_chip,
    verdict_pill,
)

st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Iniciando o motor de análise…")
def get_manager() -> JobManager:
    return JobManager(build_deps(get_settings()))


try:
    manager = get_manager()
except Exception as exc:  # noqa: BLE001 - configuration problems must be readable, not a traceback
    st.error(f"Não foi possível iniciar o aplicativo: {exc}")
    st.stop()

repo = manager.deps.repo
settings = manager.deps.settings
PAGES: dict[str, st.Page] = {}


# ===================================================================== page: new analysis
def page_new() -> None:
    st.markdown(
        '<div class="rl-hero"><h1>Reliability Lab</h1>'
        "<p>Cole uma URL ou um texto. O sistema extrai as alegações, busca evidências e "
        "classifica por <b>regras explícitas</b> — o modelo nunca dá o veredito.</p></div>",
        unsafe_allow_html=True,
    )

    active = st.session_state.get("active_id")
    if active and not repo.is_terminal(active):
        st.info("Há uma análise em andamento.")
        if st.button("Ver progresso", key="goto_progress"):
            st.switch_page(PAGES["progress"])

    with st.container(border=True):
        raw = st.text_area(
            "URL ou texto a analisar",
            height=180,
            placeholder="Cole qualquer link: notícia, foto (.jpg/.png), vídeo do YouTube, arquivo de vídeo (.mp4) ou texto completo…",
            key="input_raw",
            help="Qualquer link http/https pode ser analisado (páginas web, vídeos do YouTube, arquivos de vídeo e fotos/imagens). Textos precisam de ao menos 40 caracteres.",
        )
        c1, c2 = st.columns([2, 1])
        with c1:
            depth_label = st.radio(
                "Profundidade",
                ["Rápida", "Profunda"],
                horizontal=True,
                key="depth",
                help="Rápida: até 5 alegações, usa trechos da busca. Profunda: até 10 alegações, abre as páginas das fontes.",
            )
        with c2:
            st.write("")
            go = st.button("Analisar", type="primary", width="stretch", key="submit")
        if go:
            try:
                aid = manager.submit(raw, Depth.DEEP if depth_label == "Profunda" else Depth.FAST)
            except InvalidInput as exc:
                st.error(str(exc))
            except ReliabilityError as exc:
                st.error(str(exc))
            else:
                st.session_state.active_id = aid
                st.switch_page(PAGES["progress"])

    st.markdown(
        '<p class="rl-muted">Nenhum conteúdo sai desta máquina além das consultas de busca e do '
        f"endpoint do modelo configurado ({esc(settings.llm_base_url)}).</p>",
        unsafe_allow_html=True,
    )


# ======================================================================== page: progress
def page_progress() -> None:
    aid = st.session_state.get("active_id")
    if not aid:
        st.info("Nenhuma análise ativa.")
        if st.button("Nova análise", key="p_new"):
            st.switch_page(PAGES["new"])
        return
    if repo.is_terminal(aid):
        st.session_state.report_id = aid
        st.switch_page(PAGES["report"])

    st.markdown('<div class="rl-hero"><h1>Analisando…</h1></div>', unsafe_allow_html=True)

    @st.fragment(run_every=1)
    def live() -> None:
        state = repo.get_status(aid)
        if state is None:
            return
        status, label = state
        if status in TERMINAL_STATUSES:
            st.session_state.report_id = aid
            st.rerun(scope="app")
        st.markdown(stepper(status), unsafe_allow_html=True)
        with st.status(f"{label}…", state="running", expanded=True):
            for ts, step, msg in repo.list_events(aid)[-14:]:
                st.markdown(
                    f"`{ts:%H:%M:%S}` **{step.title()}** — {md_escape(msg)}"
                )

    live()

    if st.button("Cancelar Análise", key="cancel"):
        if manager.cancel(aid):
            st.toast("Cancelando…")


# ========================================================================= page: report
def _render_claims(rep: AnalysisReport) -> None:
    if not rep.claims:
        st.caption("Nenhuma alegação factual foi identificada.")
        return
    for i, c in enumerate(rep.claims, start=1):
        with st.expander(f"{i}. {c.text[:110]}{'…' if len(c.text) > 110 else ''}"):
            st.markdown(
                f"{verdict_pill(c.verification_status)} "
                f'<span class="rl-muted">tipo: {esc(c.claim_type.value)} · importância {c.importance}/3</span>',
                unsafe_allow_html=True,
            )
            st.markdown("**Alegação:** " + md_escape(c.text))
            if c.rationale:
                st.caption("Regra aplicada (código): " + c.rationale)
            if c.tags:
                st.markdown(
                    "".join(tag_chip(t.code, t.justification) for t in c.tags), unsafe_allow_html=True
                )
            if not c.evidences:
                st.caption("Nenhuma evidência com trecho verificado foi encontrada.")
            for e in c.evidences:
                label, color = STANCE_UI[e.stance]
                who = e.publisher or e.domain or "fonte"
                fc_badge = factcheck_badge() if is_factcheck_domain(e.domain) else ""
                st.markdown(
                    f'<span style="color:{color};font-weight:700">{label}</span> · '
                    f"<b>{esc(who)}</b>{fc_badge} · relevância {e.relevance:.0%}"
                    + (" · 🔒 paywall" if e.is_paywalled else "")
                    + (" · ⚠️ omite contexto" if e.omits_context else ""),
                    unsafe_allow_html=True,
                )
                st.markdown(f'<div class="rl-quote">“{esc(e.exact_quote)}”</div>', unsafe_allow_html=True)
                url = safe_http_url(e.source_url)
                if url:
                    st.link_button(
                        f"Abrir fonte · {(e.source_title or e.domain or url)[:60]}",
                        url,
                        key=f"src_{c.id}_{abs(hash(e.source_url + e.exact_quote)) % 10**8}",
                    )


def _render_investigative_dashboard(rep: AnalysisReport) -> None:
    if not rep.claims:
        return

    contradicted = [c for c in rep.claims if c.verification_status == ClaimVerdict.CONTRADICTED]
    partial = [c for c in rep.claims if c.verification_status == ClaimVerdict.PARTIALLY_CORROBORATED]
    corroborated = [c for c in rep.claims if c.verification_status == ClaimVerdict.CORROBORATED]
    inconclusive = [c for c in rep.claims if c.verification_status == ClaimVerdict.INCONCLUSIVE]

    with st.container(border=True):
        st.markdown(
            '<div class="rl-investigative-title">🔍 <b>Painel Investigativo · Confronto Factual</b></div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Contraditas / Falsas",
            len(contradicted),
            help="Alegações formalmente desmentidas por fontes externas ou checagens",
        )
        c2.metric(
            "Com Ressalvas / Distorcidas",
            len(partial),
            help="Alegações que misturam fatos reais com dados incorretos ou fora de contexto",
        )
        c3.metric(
            "Corroboradas / Fatos",
            len(corroborated),
            help="Alegações comprovadas e confirmadas por fontes independentes",
        )
        c4.metric(
            "Sem Provas / Inconclusivas",
            len(inconclusive),
            help="Alegações sem respaldo ou registros documentais encontrados",
        )

        suspect = contradicted or partial or [c for c in inconclusive if c.importance >= 2]
        if suspect:
            st.markdown("---")
            st.markdown("##### ⚖️ Confronto Direto dos Fatos")
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**🔴 O que o conteúdo afirma:**")
                for s in suspect[:4]:
                    st.markdown(f"- *“{md_escape(s.text[:130])}{'…' if len(s.text) > 130 else ''}”*")
            with col_b:
                st.markdown("**🟢 O que as fontes apuraram:**")
                for s in suspect[:4]:
                    if s.evidences:
                        # Prioriza evidência que desmente ou com maior relevância
                        best_ev = max(
                            s.evidences,
                            key=lambda e: (1 if e.stance.value == "contradicts" else 0, e.relevance),
                        )
                        who = best_ev.publisher or best_ev.domain or "Fonte"
                        fc = " [🛡️ Checagem]" if is_factcheck_domain(best_ev.domain) else ""
                        st.markdown(
                            f"- **{esc(who)}{fc}**: “{esc(best_ev.exact_quote[:130])}{'…' if len(best_ev.exact_quote) > 130 else ''}”"
                        )
                    else:
                        st.markdown("- *Nenhum registro oficial ou jornalístico confirmou este fato.*")


def _feedback_form(rep: AnalysisReport) -> None:
    st.subheader("Esta análise acertou?")
    if rep.feedback_given:
        st.success("Obrigado! Seu feedback foi registrado.")
        return
    with st.form(f"fb_{rep.id}", clear_on_submit=True):
        verdict = st.radio("Avaliação", ["Acertou", "Errou"], horizontal=True)
        notes = st.text_area("Correção / observações (opcional)", height=90)
        if st.form_submit_button("Enviar feedback"):
            repo.add_feedback(rep.id, verdict.startswith("👍"), notes.strip() or None)
            st.rerun()


def page_report() -> None:
    rid = st.session_state.get("report_id") or st.session_state.get("active_id")
    if not rid:
        st.info("Nenhum relatório selecionado. Faça uma análise ou abra uma pelo Histórico.")
        return
    rep = repo.get_report(rid)
    if rep is None:
        st.error("Análise não encontrada.")
        return
    if rep.status not in TERMINAL_STATUSES:
        st.session_state.active_id = rid
        st.switch_page(PAGES["progress"])

    st.markdown(
        f'<div class="rl-hero"><h1>Relatório #{rep.id}</h1>'
        f"<p>{esc(rep.title or rep.original_input[:120])} {status_pill(rep.status)}</p></div>",
        unsafe_allow_html=True,
    )

    if rep.status is AnalysisStatus.FAILED:
        st.error(rep.error_message or "A análise falhou.")
    elif rep.status is AnalysisStatus.CANCELLED:
        st.warning("Análise cancelada. Resultados parciais (se houver) abaixo.")
    for w in rep.warnings:
        st.warning(w)

    # Exibição de mídia associada (fotos ou vídeos)
    if rep.media_url:
        with st.container(border=True):
            if rep.media_type in ("video", "youtube"):
                st.caption("**Vídeo analisado**")
                st.video(rep.media_url)
            elif rep.media_type == "image":
                st.caption("📷 **Foto / Imagem analisada**")
                st.image(rep.media_url, width="stretch")

    # (1) scoreboard + painel investigativo + tags
    if rep.overall_status:
        st.markdown(score_card(rep.overall_status, rep.overall_reason), unsafe_allow_html=True)

    _render_investigative_dashboard(rep)

    all_tags = [*rep.tags, *(t for c in rep.claims for t in c.tags)]
    if all_tags:
        st.markdown("#### Pontos de atenção")
        st.markdown("".join(tag_chip(t.code, t.justification) for t in all_tags), unsafe_allow_html=True)
        with st.expander("Por que estas tags?"):
            for t in all_tags:
                st.markdown(f"**{TAG_LABELS[t.code]}** — {md_escape(t.justification)}")

    if rep.summary:
        st.markdown("#### Resumo")
        st.markdown(md_escape(rep.summary))

    # (2) claims
    st.markdown("#### Alegações e evidências")
    _render_claims(rep)

    # (3) feedback
    if rep.status in {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}:
        _feedback_form(rep)

    with st.expander("Telemetria e reprodutibilidade"):
        k = st.columns(4)
        k[0].metric("Tempo", f"{rep.processing_time_ms / 1000:.1f}s")
        k[1].metric("Tokens (prompt)", f"{rep.prompt_tokens:,}".replace(",", "."))
        k[2].metric("Tokens (resposta)", f"{rep.completion_tokens:,}".replace(",", "."))
        k[3].metric("Profundidade", rep.depth.value)
        st.caption(
            f"Modelo: `{rep.model_name}` · pipeline `{rep.pipeline_version}` · prompts `{rep.prompt_version}`"
        )
    if st.button("Nova análise", key="r_new"):
        st.switch_page(PAGES["new"])


# ========================================================================= page: history
def page_history() -> None:
    st.markdown(
        '<div class="rl-hero"><h1>Histórico e métricas</h1><p>Todas as análises, com custo de tokens e tempo.</p></div>',
        unsafe_allow_html=True,
    )
    df = repo.history_dataframe()
    if df.empty:
        st.info("Ainda não há análises.")
        return

    done = df[df["status"].isin(["COMPLETED", "PARTIAL"])]
    fb = df["feedback_acertou"].dropna()
    cols = st.columns(5)
    cols[0].metric("Análises", len(df))
    cols[1].metric("Concluídas", len(done))
    cols[2].metric("Tokens totais", f"{int(df['tokens_prompt'].sum() + df['tokens_resposta'].sum()):,}".replace(",", "."))
    cols[3].metric("Tempo médio", f"{(done['tempo_ms'].mean() / 1000 if len(done) else 0):.1f}s")
    cols[4].metric("Acerto (feedback)", f"{(fb.astype(bool).mean() * 100 if len(fb) else 0):.0f}%" if len(fb) else "—")

    event = st.dataframe(
        df,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="history_table",
    )
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        sel = event.selection.rows if event and event.selection else []
        if st.button("Abrir análise selecionada", disabled=not sel, key="open_sel"):
            st.session_state.report_id = int(df.iloc[sel[0]]["id"])
            st.switch_page(PAGES["report"])
    with c2:
        st.download_button(
            "⬇️ Exportar CSV",
            repo.history_csv(),
            file_name="historico_reliability_lab.csv",
            mime="text/csv",
            key="csv",
        )


PAGES["new"] = st.Page(page_new, title="Nova análise", default=True, url_path="nova")
PAGES["progress"] = st.Page(page_progress, title="Progresso", url_path="progresso")
PAGES["report"] = st.Page(page_report, title="Relatório", url_path="relatorio")
PAGES["history"] = st.Page(page_history, title="Histórico", url_path="historico")

with st.sidebar:
    st.markdown("### Reliability Lab")
    if settings.reliability_demo:
        st.warning("MODO DEMONSTRAÇÃO: LLM e busca simulados.")
    elif not settings.effective_api_key and "localhost" not in settings.llm_base_url:
        st.warning("⚠️ Chave `OPENAI_API_KEY` não configurada no `.env`.")
    st.caption(f"Modelo: `{settings.llm_model}`")
    st.caption(f"Pipeline `{PIPELINE_VERSION}` · prompts `{PROMPT_VERSION}`")

nav = st.navigation(list(PAGES.values()))
nav.run()
