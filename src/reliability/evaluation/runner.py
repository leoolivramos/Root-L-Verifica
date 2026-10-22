"""Batch evaluation runner.

    python -m reliability.evaluation.runner datasets/sample.jsonl [--depth rapida|profunda]
                                            [--out results.csv] [--demo]

Dataset: JSONL, one object per line: {"id": str, "input": str (URL or text),
"expected_overall": one of the OverallStatus values or null, "notes": str?}.
Metrics: accuracy and macro-F1 of the overall classification vs. the gold label, plus
latency, token usage and processing-status distribution.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from reliability.bootstrap import build_deps
from reliability.config import Settings
from reliability.pipeline import create_analysis, run_analysis
from reliability.schemas import Depth, OverallStatus


def macro_f1(gold: list[str], pred: list[str]) -> float:
    labels = sorted(set(gold) | set(pred))
    scores = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred, strict=True))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred, strict=True))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(scores) / len(scores) if scores else 0.0


def compute_metrics(rows: list[dict]) -> dict:
    labelled = [r for r in rows if r["expected"] and r["predicted"]]
    gold = [r["expected"] for r in labelled]
    pred = [r["predicted"] for r in labelled]
    times = [r["time_ms"] for r in rows if r["time_ms"]]
    return {
        "items": len(rows),
        "labelled": len(labelled),
        "accuracy": (sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold)) if gold else None,
        "macro_f1": macro_f1(gold, pred) if gold else None,
        "latency_ms_mean": statistics.mean(times) if times else None,
        "latency_ms_p95": (sorted(times)[max(0, int(len(times) * 0.95) - 1)] if times else None),
        "tokens_mean": statistics.mean([r["tokens"] for r in rows]) if rows else None,
        "status_counts": dict(Counter(r["status"] for r in rows)),
    }


async def evaluate(dataset: Path, depth: Depth, settings: Settings) -> list[dict]:
    deps = build_deps(settings)
    rows: list[dict] = []
    for line in dataset.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        try:
            aid = create_analysis(deps, item["input"], depth)
        except Exception as exc:  # noqa: BLE001 - report invalid dataset rows, keep going
            rows.append({"id": item["id"], "expected": item.get("expected_overall"), "predicted": None,
                         "status": f"INVALID: {exc}", "time_ms": 0, "tokens": 0})
            continue
        await run_analysis(aid, deps)
        rep = deps.repo.get_report(aid)
        rows.append(
            {
                "id": item["id"],
                "expected": item.get("expected_overall"),
                "predicted": rep.overall_status.value if rep.overall_status else None,
                "status": rep.status.value,
                "time_ms": rep.processing_time_ms,
                "tokens": rep.prompt_tokens + rep.completion_tokens,
            }
        )
        print(f"[{item['id']}] {rows[-1]['status']:<9} -> {rows[-1]['predicted']} (esperado: {rows[-1]['expected']})")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--depth", choices=[d.value for d in Depth], default=Depth.FAST.value)
    ap.add_argument("--out", type=Path, default=None, help="CSV with per-item results")
    ap.add_argument("--demo", action="store_true", help="use fake LLM/search (no network)")
    args = ap.parse_args(argv)

    settings = Settings()
    if args.demo:
        settings.reliability_demo = True
    valid = {o.value for o in OverallStatus}
    rows = asyncio.run(evaluate(args.dataset, Depth(args.depth), settings))
    bad = [r["id"] for r in rows if r["expected"] and r["expected"] not in valid]
    if bad:
        print(f"Rótulos inválidos em: {bad}", file=sys.stderr)
    metrics = compute_metrics(rows)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if args.out:
        with args.out.open("w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
