"""Worst-case overall classification (RF-11): no averaging, divergences preserved."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from reliability.schemas import CAVEAT_TAGS, ClaimVerdict, OverallStatus, TagCode


@dataclass(frozen=True)
class OverallResult:
    status: OverallStatus
    reason: str


def classify_overall(verdicts: Iterable[ClaimVerdict], tag_codes: Iterable[TagCode]) -> OverallResult:
    verdicts = [v for v in verdicts if v is not ClaimVerdict.NOT_VERIFIABLE]
    tag_set = set(tag_codes)
    n = len(verdicts)
    counts = {v: verdicts.count(v) for v in ClaimVerdict}

    if counts[ClaimVerdict.CONTRADICTED]:
        k = counts[ClaimVerdict.CONTRADICTED]
        return OverallResult(
            OverallStatus.CONTRADICTED,
            f"Desinformação/Contradição detectada: {k} de {n} alegação(ões) verificável(is) foram "
            "formalmente contraditas ou desmentidas por fontes externas. O pior caso prevalece.",
        )
    if n == 0:
        return OverallResult(
            OverallStatus.INSUFFICIENT, "Nenhuma alegação factual verificável foi identificada."
        )
    if counts[ClaimVerdict.INCONCLUSIVE] == n:
        if TagCode.APELO_EMOCIONAL in tag_set or TagCode.ORIGEM_NAO_CONFIRMADA in tag_set:
            return OverallResult(
                OverallStatus.INSUFFICIENT,
                f"Boato viral sem sustentação: todas as {n} alegação(ões) verificável(is) ficaram inconclusivas "
                "(nenhuma evidência jornalística ou oficial encontrada).",
            )
        return OverallResult(
            OverallStatus.INSUFFICIENT,
            f"Todas as {n} alegação(ões) verificável(is) ficaram inconclusivas.",
        )
    if counts[ClaimVerdict.CORROBORATED] == n:
        caveats = sorted(t.value for t in tag_set & CAVEAT_TAGS)
        if caveats:
            return OverallResult(
                OverallStatus.CORROBORATED_WITH_CAVEATS,
                f"Todas as {n} alegação(ões) corroborada(s), com ressalvas: {', '.join(caveats)}.",
            )
        return OverallResult(
            OverallStatus.WELL_CORROBORATED,
            f"Todas as {n} alegação(ões) verificável(is) corroborada(s), sem ressalvas.",
        )
    parts = [
        f"{counts[v]} {label}"
        for v, label in (
            (ClaimVerdict.CORROBORATED, "corroborada(s)"),
            (ClaimVerdict.PARTIALLY_CORROBORATED, "parcialmente corroborada(s)"),
            (ClaimVerdict.INCONCLUSIVE, "inconclusiva(s)"),
        )
        if counts[v]
    ]
    diag = ""
    if counts[ClaimVerdict.PARTIALLY_CORROBORATED] > 0 and (
        TagCode.FORA_DE_CONTEXTO in tag_set or TagCode.OPINIAO_COMO_FATO in tag_set
    ):
        diag = " (indício de descontextualização ou distorção de fatos reais)"
    return OverallResult(OverallStatus.MIXED, "Resultados mistos: " + ", ".join(parts) + diag + ".")
