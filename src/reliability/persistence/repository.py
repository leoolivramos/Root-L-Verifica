"""Repository over SQLAlchemy sessions. All methods are synchronous and short-lived;
the async pipeline calls them through `asyncio.to_thread`."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from reliability.persistence.models import (
    Analysis,
    Claim,
    Evidence,
    ProgressEvent,
    Source,
    TagAssignment,
    UserFeedback,
    utcnow,
)
from reliability.schemas import (
    TERMINAL_STATUSES,
    AnalysisReport,
    AnalysisStatus,
    ClaimReport,
    ClaimType,
    ClaimVerdict,
    Depth,
    EvidenceView,
    OverallStatus,
    Stance,
    TagCode,
    TagView,
)


class AnalysisRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    # ------------------------------------------------------------------ writes
    def create_analysis(
        self,
        *,
        input_type: str,
        original_input: str,
        depth: str,
        pipeline_version: str,
        prompt_version: str,
        model_name: str,
        llm_base_url: str = "",
    ) -> int:
        with self._sf.begin() as s:
            a = Analysis(
                input_type=input_type,
                original_input=original_input,
                depth=depth,
                status=AnalysisStatus.PENDING.value,
                pipeline_version=pipeline_version,
                prompt_version=prompt_version,
                model_name=model_name,
                llm_base_url=llm_base_url,
                warnings=[],
            )
            s.add(a)
            s.flush()
            return a.id

    def set_status(self, analysis_id: int, status: AnalysisStatus, step_label: str | None = None):
        with self._sf.begin() as s:
            a = s.get(Analysis, analysis_id)
            a.status = status.value
            if step_label:
                a.step_label = step_label

    def add_event(self, analysis_id: int, step: str, message: str) -> None:
        with self._sf.begin() as s:
            s.add(ProgressEvent(analysis_id=analysis_id, step=step, message=message))

    def update_meta(self, analysis_id: int, **fields: Any) -> None:
        allowed = {"title", "domain", "summary", "media_type", "media_url"}
        with self._sf.begin() as s:
            a = s.get(Analysis, analysis_id)
            for k, v in fields.items():
                if k in allowed:
                    setattr(a, k, v)

    def add_warning(self, analysis_id: int, warning: str) -> None:
        with self._sf.begin() as s:
            a = s.get(Analysis, analysis_id)
            current = list(a.warnings or [])
            if warning not in current:
                current.append(warning)
            a.warnings = current

    def save_claim(
        self,
        analysis_id: int,
        *,
        text: str,
        claim_type: str,
        importance: int,
        time_sensitive: bool,
        requires_external_evidence: bool,
        verification_query: str,
        source_quote: str,
    ) -> int:
        with self._sf.begin() as s:
            c = Claim(
                analysis_id=analysis_id,
                text=text,
                claim_type=claim_type,
                importance=importance,
                time_sensitive=time_sensitive,
                requires_external_evidence=requires_external_evidence,
                verification_query=verification_query,
                source_quote=source_quote,
            )
            s.add(c)
            s.flush()
            return c.id

    def get_or_create_source(
        self,
        analysis_id: int,
        *,
        url: str,
        title: str | None = None,
        publisher: str | None = None,
        domain: str | None = None,
        published_at: datetime | None = None,
        is_paywalled: bool = False,
    ) -> int:
        with self._sf.begin() as s:
            existing = s.scalar(
                select(Source).where(Source.analysis_id == analysis_id, Source.url == url)
            )
            if existing:
                return existing.id
            src = Source(
                analysis_id=analysis_id,
                url=url,
                title=title,
                publisher=publisher,
                domain=domain,
                published_at=published_at,
                is_paywalled=is_paywalled,
            )
            s.add(src)
            s.flush()
            return src.id

    def add_evidence(
        self,
        claim_id: int,
        source_id: int,
        *,
        stance: str,
        relevance: float,
        exact_quote: str,
        omits_context: bool,
    ) -> int:
        with self._sf.begin() as s:
            e = Evidence(
                claim_id=claim_id,
                source_id=source_id,
                stance=stance,
                relevance=relevance,
                exact_quote=exact_quote,
                omits_context=omits_context,
            )
            s.add(e)
            s.flush()
            return e.id

    def set_claim_verdict(self, claim_id: int, verdict: ClaimVerdict, rationale: str) -> None:
        with self._sf.begin() as s:
            c = s.get(Claim, claim_id)
            c.verification_status = verdict.value
            c.rationale = rationale

    def save_tags(
        self, analysis_id: int, tags: Iterable[tuple[TagCode, str, int | None]]
    ) -> None:
        with self._sf.begin() as s:
            for code, justification, claim_id in tags:
                s.add(
                    TagAssignment(
                        analysis_id=analysis_id,
                        claim_id=claim_id,
                        tag_code=code.value,
                        justification=justification,
                    )
                )

    def finalize(
        self,
        analysis_id: int,
        *,
        status: AnalysisStatus,
        overall_status: OverallStatus | None = None,
        overall_reason: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        processing_time_ms: int = 0,
        error_message: str | None = None,
    ) -> None:
        with self._sf.begin() as s:
            a = s.get(Analysis, analysis_id)
            a.status = status.value
            a.overall_status = overall_status.value if overall_status else None
            a.overall_reason = overall_reason
            a.prompt_tokens = prompt_tokens
            a.completion_tokens = completion_tokens
            a.processing_time_ms = processing_time_ms
            a.error_message = error_message
            a.finished_at = utcnow()
            a.step_label = {
                AnalysisStatus.COMPLETED: "Concluída",
                AnalysisStatus.PARTIAL: "Concluída parcialmente",
                AnalysisStatus.FAILED: "Falhou",
                AnalysisStatus.CANCELLED: "Cancelada",
            }.get(status, a.step_label)

    def add_feedback(
        self, analysis_id: int, is_accurate: bool, correction_notes: str | None = None
    ) -> None:
        with self._sf.begin() as s:
            s.add(
                UserFeedback(
                    analysis_id=analysis_id,
                    is_accurate=is_accurate,
                    correction_notes=(correction_notes or None),
                )
            )

    # ------------------------------------------------------------------- reads
    def get_input(self, analysis_id: int) -> tuple[str, str, str]:
        with self._sf() as s:
            a = s.get(Analysis, analysis_id)
            return a.input_type, a.original_input, a.depth

    def fail_orphans(self, message: str = "Análise interrompida (aplicativo reiniciado).") -> int:
        """Mark analyses left in a non-terminal state by a previous process as FAILED."""
        terminal = [st.value for st in TERMINAL_STATUSES]
        with self._sf.begin() as s:
            rows = s.scalars(select(Analysis).where(Analysis.status.not_in(terminal))).all()
            for a in rows:
                a.status = AnalysisStatus.FAILED.value
                a.step_label = "Falhou"
                a.error_message = message
                a.finished_at = utcnow()
            return len(rows)

    def get_status(self, analysis_id: int) -> tuple[AnalysisStatus, str] | None:
        with self._sf() as s:
            a = s.get(Analysis, analysis_id)
            if a is None:
                return None
            return AnalysisStatus(a.status), a.step_label

    def is_terminal(self, analysis_id: int) -> bool:
        st = self.get_status(analysis_id)
        return st is not None and st[0] in TERMINAL_STATUSES

    def list_events(self, analysis_id: int) -> list[tuple[datetime, str, str]]:
        with self._sf() as s:
            rows = s.scalars(
                select(ProgressEvent)
                .where(ProgressEvent.analysis_id == analysis_id)
                .order_by(ProgressEvent.id)
            ).all()
            return [(r.ts, r.step, r.message) for r in rows]

    def get_report(self, analysis_id: int) -> AnalysisReport | None:
        with self._sf() as s:
            a = s.scalars(
                select(Analysis)
                .where(Analysis.id == analysis_id)
                .options(
                    selectinload(Analysis.claims)
                    .selectinload(Claim.evidences)
                    .selectinload(Evidence.source),
                    selectinload(Analysis.tags),
                    selectinload(Analysis.feedback),
                )
            ).first()
            if a is None:
                return None

            claim_tags: dict[int, list[TagView]] = {}
            analysis_tags: list[TagView] = []
            for t in a.tags:
                tv = TagView(
                    code=TagCode(t.tag_code), justification=t.justification, claim_id=t.claim_id
                )
                if t.claim_id is None:
                    analysis_tags.append(tv)
                else:
                    claim_tags.setdefault(t.claim_id, []).append(tv)

            claims = [
                ClaimReport(
                    id=c.id,
                    text=c.text,
                    claim_type=ClaimType(c.claim_type),
                    importance=c.importance,
                    verification_status=ClaimVerdict(c.verification_status),
                    rationale=c.rationale,
                    evidences=[
                        EvidenceView(
                            source_url=e.source.url,
                            source_title=e.source.title,
                            publisher=e.source.publisher,
                            domain=e.source.domain,
                            published_at=e.source.published_at,
                            is_paywalled=e.source.is_paywalled,
                            stance=Stance(e.stance),
                            relevance=e.relevance,
                            exact_quote=e.exact_quote,
                            omits_context=e.omits_context,
                        )
                        for e in c.evidences
                    ],
                    tags=claim_tags.get(c.id, []),
                )
                for c in a.claims
            ]
            return AnalysisReport(
                id=a.id,
                input_type=a.input_type,  # type: ignore[arg-type]
                original_input=a.original_input,
                title=a.title,
                domain=a.domain,
                status=AnalysisStatus(a.status),
                overall_status=OverallStatus(a.overall_status) if a.overall_status else None,
                overall_reason=a.overall_reason,
                depth=Depth(a.depth),
                summary=a.summary,
                warnings=list(a.warnings or []),
                error_message=a.error_message,
                tags=analysis_tags,
                claims=claims,
                pipeline_version=a.pipeline_version,
                prompt_version=a.prompt_version,
                model_name=a.model_name,
                prompt_tokens=a.prompt_tokens,
                completion_tokens=a.completion_tokens,
                processing_time_ms=a.processing_time_ms,
                created_at=a.created_at,
                feedback_given=bool(a.feedback),
                media_type=getattr(a, "media_type", None),
                media_url=getattr(a, "media_url", None),
            )

    def history_dataframe(self) -> pd.DataFrame:
        with self._sf() as s:
            rows = s.scalars(select(Analysis).order_by(Analysis.id.desc())).all()
            fb = {
                f.analysis_id: f.is_accurate
                for f in s.scalars(select(UserFeedback).order_by(UserFeedback.id)).all()
            }
            data = [
                {
                    "id": a.id,
                    "criada_em": a.created_at,
                    "entrada": (a.title or a.original_input)[:90].replace("\n", " "),
                    "tipo": a.input_type,
                    "midia": getattr(a, "media_type", None) or "texto",
                    "profundidade": a.depth,
                    "status": a.status,
                    "classificacao": a.overall_status or "",
                    "modelo": a.model_name,
                    "pipeline": a.pipeline_version,
                    "prompt": a.prompt_version,
                    "tokens_prompt": a.prompt_tokens,
                    "tokens_resposta": a.completion_tokens,
                    "tempo_ms": a.processing_time_ms,
                    "feedback_acertou": fb.get(a.id),
                }
                for a in rows
            ]
        cols = [
            "id", "criada_em", "entrada", "tipo", "profundidade", "status", "classificacao",
            "modelo", "pipeline", "prompt", "tokens_prompt", "tokens_resposta", "tempo_ms",
            "feedback_acertou",
        ]
        return pd.DataFrame(data, columns=cols)

    def history_csv(self) -> bytes:
        """CSV (UTF-8 with BOM for Excel). Cells starting with = + - @ are prefixed with an
        apostrophe so that spreadsheet software does not evaluate them as formulas."""
        df = self.history_dataframe()

        def safe(v):
            if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
                return "'" + v
            return v

        for col in df.select_dtypes(include=["object", "string"]).columns:
            df[col] = df[col].map(safe)
        return df.to_csv(index=False).encode("utf-8-sig")
