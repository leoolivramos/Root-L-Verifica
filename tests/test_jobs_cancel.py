"""RNF-06: background execution and cancellation."""

from __future__ import annotations

import time

from reliability.demo import FakeLLMGateway
from reliability.jobs import JobManager
from reliability.schemas import AnalysisStatus, Depth

TEXT = "O PIB do país cresceu 2,9% em 2025 segundo o instituto oficial. A inflação ficou em 4,1% no período."


def test_submit_returns_immediately_and_job_completes(make_deps, repo):
    deps = make_deps(gateway=FakeLLMGateway(delay_s=0.3))
    jm = JobManager(deps)
    try:
        t0 = time.monotonic()
        aid = jm.submit(TEXT, Depth.FAST)
        assert time.monotonic() - t0 < 0.5  # UI thread is never blocked by the pipeline
        assert jm.is_running(aid)
        assert jm.wait(aid, timeout=30)
        assert repo.get_status(aid)[0] in {AnalysisStatus.COMPLETED, AnalysisStatus.PARTIAL}
    finally:
        jm.shutdown()


def test_cancel_stops_a_slow_job_quickly(make_deps, repo):
    deps = make_deps(gateway=FakeLLMGateway(delay_s=5.0))  # each LLM call would take 5s
    jm = JobManager(deps)
    try:
        aid = jm.submit(TEXT, Depth.FAST)
        time.sleep(0.5)  # let it reach the LLM step
        t0 = time.monotonic()
        assert jm.cancel(aid)
        assert jm.wait(aid, timeout=5)
        assert time.monotonic() - t0 < 2
        assert repo.get_status(aid)[0] is AnalysisStatus.CANCELLED
        rep = repo.get_report(aid)
        assert rep.error_message and "cancelada" in rep.error_message.lower()
        assert not jm.cancel(aid)  # nothing left to cancel
    finally:
        jm.shutdown()


def test_invalid_input_is_rejected_synchronously(make_deps):
    import pytest

    from reliability.errors import InvalidInput

    jm = JobManager(make_deps())
    try:
        with pytest.raises(InvalidInput):
            jm.submit("   ")
    finally:
        jm.shutdown()
