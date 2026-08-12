"""API tests for POST /api/analyze/distribution
(ANALYSIS_PRESENTATION_PLAN.md #6, audit R6).

Calc-level numerics (AIC selection, param recovery) are covered by
tests/test_distributions.py; these verify the wire contract: 200 happy
path shape, 422 on a too-small population, the fit="all"/kind/"none"
response shapes, and that NaN/Infinity survive the JSON round-trip and
get reported as dropped.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app

pytestmark = [pytest.mark.api]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _lognormal_sample(n: int = 300) -> list[float]:
    rng = np.random.default_rng(0)
    return rng.lognormal(mean=1.0, sigma=0.4, size=n).tolist()


def test_happy_path_shape(client: TestClient) -> None:
    r = client.post(
        "/api/analyze/distribution",
        json={"values": _lognormal_sample(), "fit": "all"},
    )
    assert r.status_code == 200
    body = r.json()

    summary = body["summary"]
    for key in ("n", "n_dropped", "mean", "std", "min", "max", "median", "q1", "q3"):
        assert key in summary
    assert summary["n"] == 300
    assert summary["n_dropped"] == 0

    histogram = body["histogram"]
    assert len(histogram["edges"]) == len(histogram["counts"]) + 1
    assert sum(histogram["counts"]) == 300

    fits = body["fits"]
    assert fits["best"] in ("normal", "lognormal", "weibull")
    for kind in ("normal", "lognormal", "weibull"):
        assert fits[kind]["kind"] == kind
        assert "params" in fits[kind]
        assert "aic" in fits[kind]
        assert "ks_statistic" in fits[kind]
        assert "ks_pvalue" in fits[kind]


def test_too_few_values_is_422(client: TestClient) -> None:
    r = client.post(
        "/api/analyze/distribution",
        json={"values": [1.0, 2.0, 3.0], "fit": "all"},
    )
    assert r.status_code == 422
    assert "at least" in r.json()["detail"]


def test_single_kind_fit_only_populates_that_key(client: TestClient) -> None:
    r = client.post(
        "/api/analyze/distribution",
        json={"values": _lognormal_sample(), "fit": "normal"},
    )
    assert r.status_code == 200
    fits = r.json()["fits"]
    assert fits["normal"] is not None
    assert fits["lognormal"] is None
    assert fits["weibull"] is None
    assert fits["best"] is None  # no comparison made for a single kind


def test_fit_none_omits_fits(client: TestClient) -> None:
    r = client.post(
        "/api/analyze/distribution",
        json={"values": _lognormal_sample(), "fit": "none"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["fits"] is None
    assert body["summary"]["n"] == 300


def test_negative_values_reject_lognormal_fit(client: TestClient) -> None:
    values = [-1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    r = client.post(
        "/api/analyze/distribution", json={"values": values, "fit": "lognormal"}
    )
    assert r.status_code == 422
    assert "strictly positive" in r.json()["detail"]


def test_nan_and_infinity_values_are_dropped_and_counted(client: TestClient) -> None:
    # json.dumps emits literal NaN/Infinity tokens (a Python/JS extension
    # both scipy-adjacent JSON parsers accept); httpx's `json=` kwarg would
    # instead reject these via its own encoder, so build the body by hand.
    values = [1.0, 2.0, 3.0, 4.0, float("nan"), 5.0, 6.0, 7.0, 8.0, float("inf")]
    raw = json.dumps({"values": values, "fit": "none"})
    r = client.post(
        "/api/analyze/distribution",
        content=raw,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["n"] == 8
    assert summary["n_dropped"] == 2
