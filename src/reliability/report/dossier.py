"""Forensic report dossier generator (Laudo Técnico Pericial de Confiabilidade Informacional)."""

from __future__ import annotations

import hashlib
import html
from datetime import datetime

from reliability.schemas import (
    AnalysisReport,
    ClaimVerdict,
    OverallStatus,
    Stance,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _escape(text: str | None) -> str:
    if not text:
        return ""
    return html.escape(str(text))


def _status_color(status: OverallStatus | None) -> tuple[str, str]:
    """Returns (background_color, text_color)."""
    if status is OverallStatus.WELL_CORROBORATED:
        return ("#065f46", "#ecfdf5")
    if status is OverallStatus.CORROBORATED_WITH_CAVEATS:
        return ("#1e3a8a", "#eff6ff")
    if status is OverallStatus.MIXED:
        return ("#854d0e", "#fefce8")
    if status is OverallStatus.INSUFFICIENT:
        return ("#374151", "#f9fafb")
    if status is OverallStatus.CONTRADICTED:
        return ("#991b1b", "#fef2f2")
    return ("#1f2937", "#f3f4f6")


def _verdict_badge(verdict: ClaimVerdict) -> str:
    if verdict is ClaimVerdict.CORROBORATED:
        return '<span class="badge badge-corroborated">✓ Corroborada</span>'
    if verdict is ClaimVerdict.CONTRADICTED:
        return '<span class="badge badge-contradicted">✕ Contradita</span>'
    if verdict is ClaimVerdict.PARTIALLY_CORROBORATED:
        return '<span class="badge badge-partial">⚠ Parcialmente Corroborada</span>'
    if verdict is ClaimVerdict.NOT_VERIFIABLE:
        return '<span class="badge badge-notverifiable">○ Não Verificável</span>'
    return '<span class="badge badge-inconclusive">? Inconclusiva</span>'


def _stance_badge(stance: Stance) -> str:
    if stance is Stance.SUPPORTS:
        return '<span class="badge-mini badge-green">Sustenta</span>'
    if stance is Stance.CONTRADICTS:
        return '<span class="badge-mini badge-red">Contradiz</span>'
    if stance is Stance.PARTIALLY_SUPPORTS:
        return '<span class="badge-mini badge-yellow">Sustenta em parte</span>'
    return '<span class="badge-mini badge-gray">Neutro</span>'


def generate_forensic_html_report(report: AnalysisReport) -> str:
    """Generate a self-contained, print-ready Forensic Dossier in HTML."""
    now_iso = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
    protocol = f"LTP-{report.id:06d}"

    input_hash = _sha256(report.original_input)

    # Compute a combined evidence hash
    all_evs = [
        f"{e.source_url}|{e.exact_quote}|{e.stance.value}"
        for c in report.claims
        for e in c.evidences
    ]
    evidence_hash = _sha256(";;".join(all_evs)) if all_evs else "NENHUMA_EVIDENCIA_COLETADA"

    status_val = report.overall_status.value if report.overall_status else "Em Análise"
    bg_status, fg_status = _status_color(report.overall_status)

    # Forensic media section (if present)
    media_html = ""
    if report.forensic_media_analysis:
        m = report.forensic_media_analysis
        dims = m.get("dimensions") or {}
        dim_str = f"{dims.get('width')}x{dims.get('height')} px ({dims.get('megapixels', '')} MP)" if dims else "N/A"
        gps = m.get("gps")
        gps_html = "Não registrado"
        if gps:
            lat = gps.get("latitude")
            lon = gps.get("longitude")
            gps_html = f'<a href="{_escape(gps.get("google_maps"))}" target="_blank" style="color: #2563eb; text-decoration: underline;">Lat {lat}, Lon {lon} (Ver no Google Maps ↗)</a>'

        alerts_html = ""
        if m.get("alerts"):
            alerts_html = "".join(
                f'<div class="callout callout-warning"><strong>⚠️ ALERTA FORENSE:</strong> {_escape(al)}</div>'
                for al in m["alerts"]
            )

        media_html = f"""
        <section class="section">
            <h2 class="section-title">2. Perícia Técnica de Mídia / Arquivo Digital</h2>
            {alerts_html}
            <table class="forensic-table">
                <tr><th>Tipo de Arquivo</th><td>{_escape(m.get("format", "Digital"))} ({_escape(m.get("media_type", "").upper())})</td><th>Tamanho em Disco</th><td>{_escape(m.get("size_formatted"))} ({m.get("size_bytes", 0):,} bytes)</td></tr>
                <tr><th>Dispositivo de Captura</th><td>{_escape(m.get("camera_make") or "")} {_escape(m.get("camera_model") or "Não informado")}</td><th>Resolução Digital</th><td>{_escape(dim_str)}</td></tr>
                <tr><th>Data Original de Registro</th><td>{_escape(m.get("date_original") or "Não preservada no arquivo")}</td><th>Geolocalização (GPS)</th><td>{gps_html}</td></tr>
                <tr><th>Software / Editor Detectado</th><td colspan="3"><strong style="color: {'#dc2626' if m.get('is_edited') else '#16a34a'};">{_escape(m.get('software_detected') or 'Nenhum software de edição/manipulação gráfica assinado')}</strong></td></tr>
                <tr><th>Hash Criptográfico SHA-256</th><td colspan="3"><code class="hash-code">{_escape(m.get("sha256"))}</code></td></tr>
                <tr><th>Hash Criptográfico MD5</th><td colspan="3"><code class="hash-code">{_escape(m.get("md5"))}</code></td></tr>
            </table>
        </section>
        """

    # Claims and Confrontations section
    claims_html = []
    for idx, c in enumerate(report.claims, start=1):
        cid_label = f"AL-{idx:02d}"
        v_badge = _verdict_badge(c.verification_status)

        ev_rows = []
        if not c.evidences:
            ev_rows.append('<tr><td colspan="4" style="text-align: center; color: #6b7280; font-style: italic;">Nenhuma evidência pública com trecho literal comprovado foi localizada.</td></tr>')
        else:
            for ev in c.evidences:
                s_badge = _stance_badge(ev.stance)
                tier_badge = f'<span class="badge-mini badge-tier">{_escape(ev.tier_label or ev.tier)}</span>'
                domain_txt = _escape(ev.domain or ev.source_url)
                date_txt = ev.published_at.strftime("%d/%m/%Y") if ev.published_at else ""
                date_meta = f" <small style='color: #6b7280;'>({date_txt})</small>" if date_txt else ""

                ev_rows.append(f"""
                <tr>
                    <td style="width: 25%;">
                        <strong>{domain_txt}</strong>{date_meta}<br>
                        {tier_badge}<br>
                        <a href="{_escape(ev.source_url)}" target="_blank" style="font-size: 11px; color: #2563eb; text-decoration: none;">Link da Fonte ↗</a>
                    </td>
                    <td style="width: 15%; text-align: center;">{s_badge}</td>
                    <td style="width: 60%; font-size: 13px; line-height: 1.45;">
                        <blockquote class="quote-text">“{_escape(ev.exact_quote)}”</blockquote>
                    </td>
                </tr>
                """)

        rationale_html = f'<div class="claim-rationale"><strong>Fundamentação Lógica:</strong> {_escape(c.rationale)}</div>' if c.rationale else ""

        claims_html.append(f"""
        <div class="claim-card">
            <div class="claim-header">
                <div>
                    <span class="claim-id">{cid_label}</span>
                    <span class="claim-type">[{_escape(c.claim_type.value)}]</span>
                </div>
                <div>{v_badge}</div>
            </div>
            <div class="claim-text"><strong>Alegação Factual:</strong> {_escape(c.text)}</div>
            {rationale_html}
            <div style="margin-top: 10px;">
                <table class="evidence-subtable">
                    <thead>
                        <tr>
                            <th>Fonte Investigada</th>
                            <th>Posicionamento</th>
                            <th>Trecho Exato Auditado (Citação Literal)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(ev_rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """)

    # Tags / Risks section
    tags_html = ""
    if report.tags:
        tag_items = "".join(
            f'<li><strong>{_escape(t.code.value.replace("_", " ").title())}:</strong> {_escape(t.justification)}</li>'
            for t in report.tags
        )
        tags_html = f"""
        <section class="section">
            <h2 class="section-title">4. Auditoria de Vulnerabilidades e Sinais de Alerta</h2>
            <ul class="tags-list">
                {tag_items}
            </ul>
        </section>
        """

    confidence_pct = int(round((report.forensic_confidence or 0.5) * 100))
    confidence_label = report.forensic_confidence_label or f"Certeza Metodológica ({confidence_pct}%)"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Laudo Pericial - {protocol}</title>
<style>
    :root {{
        --font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        --border-color: #e5e7eb;
        --text-color: #111827;
        --bg-light: #f9fafb;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: var(--font-main);
        color: var(--text-color);
        background-color: #ffffff;
        padding: 30px;
        line-height: 1.5;
        font-size: 14px;
    }}
    .container {{
        max-width: 960px;
        margin: 0 auto;
    }}
    .print-actions {{
        display: flex;
        justify-content: flex-end;
        gap: 12px;
        margin-bottom: 24px;
    }}
    .btn {{
        background: #1e293b;
        color: #fff;
        padding: 8px 18px;
        border-radius: 6px;
        text-decoration: none;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        border: none;
    }}
    .btn:hover {{ background: #0f172a; }}

    /* Header */
    .report-header {{
        border-bottom: 3px solid #0f172a;
        padding-bottom: 18px;
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }}
    .header-titles h1 {{
        font-size: 20px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #0f172a;
        font-weight: 800;
        margin-bottom: 4px;
    }}
    .header-titles p {{
        font-size: 12px;
        color: #64748b;
        font-weight: 500;
    }}
    .header-meta {{
        text-align: right;
        font-size: 12px;
        color: #334155;
    }}
    .protocol-tag {{
        font-size: 14px;
        font-weight: 700;
        color: #0f172a;
        font-family: monospace;
    }}

    /* Sections */
    .section {{
        margin-bottom: 26px;
        page-break-inside: avoid;
    }}
    .section-title {{
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.7px;
        color: #1e293b;
        font-weight: 700;
        border-bottom: 1.5px solid var(--border-color);
        padding-bottom: 6px;
        margin-bottom: 14px;
    }}

    /* Status Box */
    .verdict-box {{
        background: {bg_status};
        color: {fg_status};
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 20px;
    }}
    .verdict-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }}
    .verdict-title {{
        font-size: 18px;
        font-weight: 800;
        letter-spacing: 0.3px;
    }}
    .verdict-desc {{
        font-size: 13px;
        line-height: 1.5;
        opacity: 0.95;
    }}

    /* Tables */
    .forensic-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12.5px;
        margin-bottom: 12px;
    }}
    .forensic-table th, .forensic-table td {{
        border: 1px solid var(--border-color);
        padding: 8px 12px;
        text-align: left;
    }}
    .forensic-table th {{
        background-color: var(--bg-light);
        color: #374151;
        font-weight: 600;
        width: 22%;
    }}
    .hash-code {{
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 11px;
        color: #0f172a;
        word-break: break-all;
    }}

    /* Claim cards */
    .claim-card {{
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 18px;
        background: #ffffff;
        page-break-inside: avoid;
    }}
    .claim-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
        border-bottom: 1px dashed var(--border-color);
        padding-bottom: 6px;
    }}
    .claim-id {{
        font-weight: 800;
        font-size: 13px;
        color: #0f172a;
        margin-right: 6px;
    }}
    .claim-type {{
        font-size: 11px;
        color: #6b7280;
        text-transform: uppercase;
    }}
    .claim-text {{
        font-size: 13.5px;
        color: #1f2937;
        margin-bottom: 8px;
    }}
    .claim-rationale {{
        font-size: 12px;
        color: #4b5563;
        background: var(--bg-light);
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 10px;
    }}
    .evidence-subtable {{
        width: 100%;
        border-collapse: collapse;
        font-size: 12px;
        margin-top: 8px;
    }}
    .evidence-subtable th {{
        background: #f1f5f9;
        color: #475569;
        font-weight: 600;
        padding: 6px 10px;
        border: 1px solid var(--border-color);
        text-align: left;
    }}
    .evidence-subtable td {{
        border: 1px solid var(--border-color);
        padding: 8px 10px;
        vertical-align: top;
    }}
    .quote-text {{
        font-style: italic;
        color: #1e293b;
        background: #f8fafc;
        border-left: 3px solid #94a3b8;
        padding: 6px 10px;
        border-radius: 3px;
    }}

    /* Badges */
    .badge {{
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
    }}
    .badge-corroborated {{ background: #dcfce7; color: #15803d; }}
    .badge-contradicted {{ background: #fee2e2; color: #b91c1c; }}
    .badge-partial {{ background: #fef9c3; color: #a16207; }}
    .badge-inconclusive {{ background: #f3f4f6; color: #4b5563; }}
    .badge-notverifiable {{ background: #e0e7ff; color: #4338ca; }}

    .badge-mini {{
        display: inline-block;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 10.5px;
        font-weight: 600;
    }}
    .badge-green {{ background: #dcfce7; color: #166534; }}
    .badge-red {{ background: #fee2e2; color: #991b1b; }}
    .badge-yellow {{ background: #fef3c7; color: #92400e; }}
    .badge-gray {{ background: #f1f5f9; color: #475569; }}
    .badge-tier {{ background: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; font-size: 9.5px; }}

    /* Callouts */
    .callout {{
        border-radius: 6px;
        padding: 10px 14px;
        font-size: 12.5px;
        margin-bottom: 12px;
    }}
    .callout-warning {{
        background: #fffbeb;
        color: #92400e;
        border-left: 4px solid #f59e0b;
    }}
    .tags-list {{
        padding-left: 20px;
        font-size: 13px;
        color: #374151;
    }}
    .tags-list li {{
        margin-bottom: 6px;
    }}

    /* Footer */
    .report-footer {{
        border-top: 1.5px solid var(--border-color);
        padding-top: 16px;
        margin-top: 32px;
        font-size: 11px;
        color: #64748b;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }}

    @media print {{
        body {{ padding: 0; font-size: 12px; background: transparent; }}
        .print-actions {{ display: none !important; }}
        .container {{ max-width: 100%; }}
        .claim-card {{ break-inside: avoid; }}
        .verdict-box {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
        .badge, .badge-mini {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="print-actions">
        <button class="btn" onclick="window.print()">🖨️ Imprimir / Salvar como PDF</button>
    </div>

    <header class="report-header">
        <div class="header-titles">
            <h1>Laudo Técnico Pericial de Confiabilidade</h1>
            <p>Root-L Verifica — Sistema Pessoal de Inteligência Informacional e Fact-Checking</p>
        </div>
        <div class="header-meta">
            <div>Protocolo: <span class="protocol-tag">{protocol}</span></div>
            <div>Data de Emissão: <strong>{now_iso}</strong></div>
            <div>Certeza: <strong>{_escape(confidence_label)}</strong></div>
        </div>
    </header>

    <!-- Custody & Integrity -->
    <section class="section">
        <h2 class="section-title">1. Cadeia de Custódia e Integridade Digital</h2>
        <table class="forensic-table">
            <tr>
                <th>Entrada Auditada</th>
                <td colspan="3">{_escape(report.title or report.original_input[:140] + ('...' if len(report.original_input) > 140 else ''))} ({_escape(report.input_type.upper())})</td>
            </tr>
            <tr>
                <th>Hash SHA-256 do Input</th>
                <td colspan="3"><code class="hash-code">{input_hash}</code></td>
            </tr>
            <tr>
                <th>Hash SHA-256 das Evidências</th>
                <td colspan="3"><code class="hash-code">{evidence_hash}</code></td>
            </tr>
            <tr>
                <th>Motor de Decisão (RNF-03)</th>
                <td>Determinístico (LLM-Free)</td>
                <th>Pipeline / Versão</th>
                <td>v{_escape(report.pipeline_version or '0.1.0')} (Prompt: {_escape(report.prompt_version)})</td>
            </tr>
        </table>
    </section>

    <!-- Executive Verdict -->
    <section class="section">
        <div class="verdict-box">
            <div class="verdict-header">
                <span class="verdict-title">{_escape(status_val)}</span>
                <span style="font-weight: 700; font-size: 13px;">{_escape(confidence_label)}</span>
            </div>
            <div class="verdict-desc">
                {_escape(report.overall_reason or 'Sem fundamentação descritiva registrada.')}
            </div>
        </div>
        {f'<div style="font-size: 13px; color: #334155; margin-bottom: 14px;"><strong>Resumo Factual:</strong> {_escape(report.summary)}</div>' if report.summary else ''}
    </section>

    {media_html}

    <!-- Claims and Evidences -->
    <section class="section">
        <h2 class="section-title">3. Confronto Factual: Alegações vs. Evidências Coletadas</h2>
        {"".join(claims_html)}
    </section>

    {tags_html}

    <footer class="report-footer">
        <div>
            Root-L-Verifica • Protocolo RNF-03 de Verificação Factual Auditável • Hash de Autenticidade: <code>{input_hash[:16]}...{evidence_hash[:16]}</code>
        </div>
        <div>
            Documento gerado automaticamente para fins de investigação e auditoria.
        </div>
    </footer>
</div>
</body>
</html>
"""
