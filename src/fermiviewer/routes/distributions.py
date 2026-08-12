"""Population histogram + distribution fitting endpoint
(ANALYSIS_PRESENTATION_PLAN.md #6, audit R6).

Thin adapter over ``calc/distributions.py``. Unlike every other
``routes/*.py`` module this one never touches the image store: the
caller already has the per-object metric values (particle equivalent
diameters, grain areas, ...) from an ``/api/analyze/particles`` or
``/api/analyze/grains`` response and posts that plain list straight
here — a size distribution is a property of the extracted NUMBERS, not
of any particular image id.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel

from fermiviewer.calc.distributions import (
    AllFits,
    DistFit,
    Histogram,
    PopulationSummary,
    fit_all,
    fit_distribution,
    histogram_bins,
    summarize,
)
from fermiviewer.routes._arrays import value_error_as_422

router = APIRouter(prefix="/api")

FitChoice = Literal["all", "normal", "lognormal", "weibull", "none"]


class DistributionRequest(BaseModel):
    values: list[float]
    fit: FitChoice = "all"


def _summary_payload(s: PopulationSummary) -> dict:
    return {
        "n": s.n,
        "n_dropped": s.n_dropped,
        "mean": s.mean,
        "std": s.std,
        "min": s.minimum,
        "max": s.maximum,
        "median": s.median,
        "q1": s.q1,
        "q3": s.q3,
    }


def _histogram_payload(h: Histogram) -> dict:
    return {"edges": h.edges.tolist(), "counts": h.counts.tolist()}


def _fit_payload(f: DistFit) -> dict:
    return {
        "kind": f.kind,
        "params": f.params,
        "log_likelihood": f.log_likelihood,
        "aic": f.aic,
        "ks_statistic": f.ks_statistic,
        "ks_pvalue": f.ks_pvalue,
    }


def _all_fits_payload(fits: AllFits) -> dict:
    return {
        "normal": _fit_payload(fits.normal),
        "lognormal": _fit_payload(fits.lognormal),
        "weibull": _fit_payload(fits.weibull),
        "best": fits.best,
    }


@router.post("/analyze/distribution")
def analyze_distribution(req: DistributionRequest) -> dict:
    """Summary + histogram + optional fit(s) over a raw value list.

    ``fit="all"`` (the default, and what the frontend always sends —
    the distribution SELECTOR switches which already-fetched curve is
    drawn, it does not re-request) returns all three fits keyed by
    name plus ``best`` (the AIC winner). A single ``kind`` returns only
    that one fit with ``best`` left ``null`` (no comparison was made).
    ``"none"`` omits the ``fits`` key (``null``) entirely — a plain
    summary + histogram for a population too small/degenerate to fit
    (below ``calc.distributions.MIN_FIT_N``) or one the caller simply
    doesn't want fit.
    """
    values = np.asarray(req.values, dtype=np.float64)
    with value_error_as_422():
        summary = summarize(values)
        histogram = histogram_bins(values)
        fits: dict | None
        if req.fit == "all":
            fits = _all_fits_payload(fit_all(values))
        elif req.fit == "none":
            fits = None
        else:
            fits = {
                "normal": None,
                "lognormal": None,
                "weibull": None,
                "best": None,
            }
            fits[req.fit] = _fit_payload(fit_distribution(values, req.fit))
    return {
        "summary": _summary_payload(summary),
        "histogram": _histogram_payload(histogram),
        "fits": fits,
    }
