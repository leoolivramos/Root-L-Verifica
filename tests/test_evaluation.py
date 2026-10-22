"""Evaluation runner metrics."""

from __future__ import annotations

import json

from reliability.evaluation.runner import compute_metrics, macro_f1, main


def test_macro_f1_perfect_and_partial():
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert 0 < macro_f1(["a", "a", "b"], ["a", "b", "b"]) < 1.0
    assert macro_f1([], []) == 0.0


def test_compute_metrics_ignores_unlabelled_and_failed():
    rows = [
        {"id": 1, "expected": "x", "predicted": "x", "status": "COMPLETED", "time_ms": 100, "tokens": 10},
        {"id": 2, "expected": "x", "predicted": "y", "status": "PARTIAL", "time_ms": 300, "tokens": 30},
        {"id": 3, "expected": None, "predicted": "x", "status": "COMPLETED", "time_ms": 200, "tokens": 20},
        {"id": 4, "expected": "x", "predicted": None, "status": "FAILED", "time_ms": 0, "tokens": 0},
    ]
    m = compute_metrics(rows)
    assert m["labelled"] == 2 and m["accuracy"] == 0.5
    assert m["status_counts"] == {"COMPLETED": 2, "PARTIAL": 1, "FAILED": 1}
    assert m["latency_ms_mean"] == 200


def test_runner_end_to_end_in_demo_mode(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "eval.db"))
    ds = tmp_path / "d.jsonl"
    ds.write_text(
        json.dumps({"id": "a", "input": "O PIB cresceu 2,9% em 2025 segundo o instituto oficial de estatística.",
                    "expected_overall": "Evidências insuficientes"}) + "\n"
        + json.dumps({"id": "b", "input": "   ", "expected_overall": None}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.csv"
    assert main([str(ds), "--demo", "--out", str(out)]) == 0
    assert out.exists() and "INVALID" in out.read_text(encoding="utf-8-sig")
    assert '"items": 2' in capsys.readouterr().out
