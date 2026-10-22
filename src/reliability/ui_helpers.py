"""Visual layer helpers: CSS and safe HTML snippets.

SECURITY: every piece of externally derived text (documents, sources, LLM output) MUST go through
`esc()` / `md_escape()` before reaching `unsafe_allow_html` or `st.markdown`.
"""

from __future__ import annotations

import html
import re

from reliability.schemas import (
    TAG_LABELS,
    VERDICT_LABELS,
    AnalysisStatus,
    ClaimVerdict,
    OverallStatus,
    Stance,
    TagCode,
)

CSS = """
<style>
:root {
  --bg-card: rgba(255,255,255,0.045);
  --bd: rgba(255,255,255,0.09);
  --muted: #9aa6bd;
  --violet: #8b6cff;
  --teal: #2dd4bf;
}
html, body, [class*="css"] { font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif; }
.stApp {
  background:
    radial-gradient(900px 500px at 8% -10%, rgba(139,108,255,0.18), transparent 60%),
    radial-gradient(800px 480px at 100% 0%, rgba(45,212,191,0.12), transparent 55%),
    #0b0f1a;
}
section[data-testid="stSidebar"] { background: rgba(14,19,34,0.92); border-right: 1px solid var(--bd); }
h1, h2, h3 { letter-spacing: -0.02em; }
.rl-hero h1 {
  font-size: 2.3rem; font-weight: 800; margin: 0 0 .2rem 0;
  background: linear-gradient(92deg, #c9bcff 0%, #8b6cff 35%, #2dd4bf 100%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.rl-hero p { color: var(--muted); margin: 0 0 1.2rem 0; font-size: 1.02rem; }
.rl-card {
  background: var(--bg-card); border: 1px solid var(--bd); border-radius: 18px;
  padding: 1.1rem 1.3rem; backdrop-filter: blur(10px);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}
.rl-card:hover { border-color: rgba(139,108,255,.45); box-shadow: 0 10px 30px rgba(0,0,0,.35); }
.rl-score { border-radius: 22px; padding: 1.5rem 1.7rem; border: 1px solid var(--bd); position: relative; overflow: hidden; }
.rl-score::after { content:""; position:absolute; inset:0; background: radial-gradient(circle at 90% 0%, var(--glow), transparent 55%); opacity:.55; pointer-events:none; }
.rl-score .label { color: var(--muted); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; }
.rl-score .value { font-size: 2rem; font-weight: 800; line-height: 1.15; margin: .25rem 0 .5rem 0; position:relative; z-index:1; }
.rl-score .reason { color:#c8d1e4; position:relative; z-index:1; }
.rl-chip {
  display:inline-block; padding:.28rem .7rem; margin:.15rem .3rem .15rem 0; border-radius:999px;
  font-size:.8rem; font-weight:600; border:1px solid; cursor:help; transition: transform .15s ease;
}
.rl-chip:hover { transform: translateY(-1px) scale(1.03); }
.rl-pill { display:inline-block; padding:.18rem .6rem; border-radius:8px; font-size:.78rem; font-weight:700; }
.rl-stepper { display:flex; gap:.6rem; margin:.4rem 0 1rem 0; }
.rl-step { flex:1; padding:.6rem .8rem; border-radius:12px; border:1px solid var(--bd); background:var(--bg-card);
  color:var(--muted); font-weight:600; font-size:.9rem; text-align:center; }
.rl-step.done { color:#5eead4; border-color: rgba(45,212,191,.4); }
.rl-step.active { color:#fff; border-color: var(--violet); background: rgba(139,108,255,.18);
  animation: rl-pulse 1.6s ease-in-out infinite; }
@keyframes rl-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(139,108,255,.45);} 50% { box-shadow: 0 0 0 8px rgba(139,108,255,0);} }
.rl-quote { border-left: 3px solid var(--violet); background: rgba(139,108,255,.08); padding:.6rem .9rem;
  border-radius: 0 10px 10px 0; color:#dfe5f3; font-style: italic; margin:.3rem 0 .6rem 0; }
.rl-muted { color: var(--muted); font-size: .88rem; }
.rl-kpi { text-align:center; } .rl-kpi .n { font-size:1.5rem; font-weight:800; } .rl-kpi .l { color:var(--muted); font-size:.78rem; }
div[data-testid="stButton"] > button[kind="primary"] {
  background: linear-gradient(92deg, #7c5cff, #2dd4bf); border: 0; color: #08111b; font-weight: 800;
  border-radius: 12px; padding: .65rem 1.4rem; transition: transform .15s ease, filter .15s ease;
}
div[data-testid="stButton"] > button[kind="primary"]:hover { transform: translateY(-1px); filter: brightness(1.08); }
.rl-investigative-box {
  background: rgba(139,108,255,0.06); border: 1px solid rgba(139,108,255,0.22);
  border-radius: 16px; padding: 1.1rem 1.3rem; margin: 0.8rem 0 1.2rem 0;
}
.rl-investigative-title {
  font-size: 1.05rem; font-weight: 700; color: #e2e8f0; margin-bottom: .5rem;
  display: flex; align-items: center; gap: .4rem;
}
.rl-investigative-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-top: .6rem;
}
.rl-box-col {
  background: rgba(255,255,255,0.025); border: 1px solid var(--bd);
  border-radius: 12px; padding: .8rem 1rem; font-size: .92rem;
}
</style>
"""

FACTCHECK_DOMAINS = {
    "boatos.org",
    "aosfatos.org",
    "lupa.news",
    "agencialupa.com.br",
    "fatooufake",
    "globo.com",
    "uol.com.br",
    "estadao.com.br",
    "folha.uol.com.br",
    "poder360.com.br",
    "reuters.com",
    "afp.com",
    "factcheck.org",
    "snopes.com",
    "checamos.afp.com",
    "projetocomprova.com.br",
    "metropoles.com",
}


def is_factcheck_domain(domain: str | None) -> bool:
    if not domain:
        return False
    d = domain.lower()
    return any(f in d for f in FACTCHECK_DOMAINS)


def factcheck_badge() -> str:
    return (
        '<span style="background:rgba(234,179,8,0.18);color:#facc15;border:1px solid rgba(234,179,8,0.45);'
        'padding:.15rem .55rem;border-radius:6px;font-size:.74rem;font-weight:700;margin-left:.4rem;">'
        '🛡️ Fonte de Checagem / Noticiário</span>'
    )

_OVERALL_COLORS = {
    OverallStatus.WELL_CORROBORATED: ("#2dd4bf", "rgba(45,212,191,0.10)"),
    OverallStatus.CORROBORATED_WITH_CAVEATS: ("#a3e635", "rgba(163,230,53,0.08)"),
    OverallStatus.MIXED: ("#fbbf24", "rgba(251,191,36,0.09)"),
    OverallStatus.INSUFFICIENT: ("#94a3b8", "rgba(148,163,184,0.09)"),
    OverallStatus.CONTRADICTED: ("#f87171", "rgba(248,113,113,0.12)"),
}
_VERDICT_COLORS = {
    ClaimVerdict.CORROBORATED: ("#2dd4bf", "rgba(45,212,191,.15)"),
    ClaimVerdict.CONTRADICTED: ("#f87171", "rgba(248,113,113,.16)"),
    ClaimVerdict.PARTIALLY_CORROBORATED: ("#fbbf24", "rgba(251,191,36,.15)"),
    ClaimVerdict.INCONCLUSIVE: ("#94a3b8", "rgba(148,163,184,.15)"),
    ClaimVerdict.NOT_VERIFIABLE: ("#a78bfa", "rgba(167,139,250,.15)"),
}
_TAG_COLORS = {
    TagCode.FONTE_NAO_IDENTIFICADA: "#60a5fa",
    TagCode.FONTES_INDEPENDENTES_INSUFICIENTES: "#60a5fa",
    TagCode.EVIDENCIA_INSUFICIENTE: "#fb923c",
    TagCode.CONTRADICAO_ENCONTRADA: "#f87171",
    TagCode.FORA_DE_CONTEXTO: "#fbbf24",
    TagCode.DATA_DESATUALIZADA: "#fbbf24",
    TagCode.APELO_EMOCIONAL: "#c084fc",
    TagCode.OPINIAO_COMO_FATO: "#c084fc",
    TagCode.ORIGEM_NAO_CONFIRMADA: "#fb7185",
    TagCode.LINK_SUSPEITO: "#fb7185",
}
STATUS_LABELS = {
    AnalysisStatus.PENDING: ("Na fila", "#94a3b8"),
    AnalysisStatus.EXTRACTING: ("Extraindo", "#8b6cff"),
    AnalysisStatus.INVESTIGATING: ("Investigando", "#8b6cff"),
    AnalysisStatus.CLASSIFYING: ("Classificando", "#8b6cff"),
    AnalysisStatus.COMPLETED: ("Concluída", "#2dd4bf"),
    AnalysisStatus.PARTIAL: ("Concluída parcialmente", "#fbbf24"),
    AnalysisStatus.FAILED: ("Falhou", "#f87171"),
    AnalysisStatus.CANCELLED: ("Cancelada", "#94a3b8"),
}
STANCE_UI = {
    Stance.SUPPORTS: ("Sustenta", "#2dd4bf"),
    Stance.PARTIALLY_SUPPORTS: ("Sustenta em parte", "#fbbf24"),
    Stance.CONTRADICTS: ("Contradiz", "#f87171"),
    Stance.NEUTRAL: ("Neutra", "#94a3b8"),
}

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~$<])")


def esc(text: object) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def md_escape(text: object) -> str:
    """Escape Markdown/HTML so external text renders literally (no links, images, headings)."""
    s = "" if text is None else str(text)
    return _MD_SPECIAL.sub(r"\\\1", s).replace("&", "&amp;")


def safe_http_url(url: str) -> str | None:
    return url if url.lower().startswith(("http://", "https://")) else None


def score_card(status: OverallStatus | None, reason: str | None) -> str:
    if status is None:
        return ""
    color, glow = _OVERALL_COLORS[status]
    return (
        f'<div class="rl-score" style="--glow:{glow}; border-color:{color}55;">'
        f'<div class="label">Classificação geral</div>'
        f'<div class="value" style="color:{color}">{esc(status.value)}</div>'
        f'<div class="reason">{esc(reason or "")}</div></div>'
    )


def status_pill(status: AnalysisStatus) -> str:
    label, color = STATUS_LABELS[status]
    return f'<span class="rl-pill" style="background:{color}22;color:{color}">{esc(label)}</span>'


def verdict_pill(verdict: ClaimVerdict) -> str:
    color, bg = _VERDICT_COLORS[verdict]
    return f'<span class="rl-pill" style="background:{bg};color:{color}">{esc(VERDICT_LABELS[verdict])}</span>'


def tag_chip(code: TagCode, justification: str) -> str:
    color = _TAG_COLORS[code]
    return (
        f'<span class="rl-chip" title="{esc(justification)}" '
        f'style="color:{color};border-color:{color}77;background:{color}18">{esc(TAG_LABELS[code])}</span>'
    )


def stepper(status: AnalysisStatus) -> str:
    order = [AnalysisStatus.EXTRACTING, AnalysisStatus.INVESTIGATING, AnalysisStatus.CLASSIFYING]
    names = ["1 · Extraindo", "2 · Investigando", "3 · Classificando"]
    current = order.index(status) if status in order else (-1 if status is AnalysisStatus.PENDING else 3)
    out = []
    for i, name in enumerate(names):
        cls = "done" if i < current else "active" if i == current else ""
        out.append(f'<div class="rl-step {cls}">{name}</div>')
    return f'<div class="rl-stepper">{"".join(out)}</div>'
