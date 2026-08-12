"""Population statistics + distribution fitting for measured object
populations (particle/grain sizes) — ANALYSIS_PRESENTATION_PLAN.md #6,
audit R6.

Every particle/grain analysis already emits per-object metrics (area,
equivalent diameter — see ``calc/particles.py``'s ``RegionStats`` and
``calc/grains.py``'s ``GrainStats``), but the app has never turned that
list of numbers into the canonical image-derived statistic: a size
histogram with normal/log-normal/Weibull fits and a proper summary (N,
mean, median, quartiles). This module is the pure statistics core;
``routes/distributions.py`` is its thin FastAPI adapter.

Pure library: numpy + scipy.stats/scipy.optimize only. No fastapi/
pydantic/route imports (enforced by tests/test_repo_integrity.py).
Domain errors are plain ``ValueError`` — the route wraps calls in
``value_error_as_422()`` the same way every other analysis route does.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats
from scipy.optimize import OptimizeWarning

__all__ = [
    "MIN_FIT_N",
    "AllFits",
    "DistFit",
    "Histogram",
    "PopulationSummary",
    "fit_all",
    "fit_distribution",
    "histogram_bins",
    "summarize",
]

# Below this many finite samples a 2-parameter MLE fit is essentially
# unconstrained — reject outright rather than hand back a fit nobody
# should trust.
MIN_FIT_N = 8

_DISTS: dict[str, stats.rv_continuous] = {
    "normal": stats.norm,
    "lognormal": stats.lognorm,
    "weibull": stats.weibull_min,
}

_MAX_HIST_BINS = 200  # guards a pathological width from exploding n_bins


def _clean(values: np.ndarray) -> tuple[np.ndarray, int]:
    """Flatten to float64, drop non-finite entries, report how many were
    dropped. NaN/Inf commonly reach here from an unmeasured/degenerate
    per-object metric — e.g. ``diameter_calibrated`` is NaN on an
    uncalibrated image (see ``calc/particles.py``'s ``RegionStats``)."""
    arr = np.asarray(values, dtype=np.float64).ravel()
    finite = np.isfinite(arr)
    dropped = int(arr.size - int(finite.sum()))
    return arr[finite], dropped


@dataclass(frozen=True)
class PopulationSummary:
    """N / mean / std / min / max / median / quartiles over a cleaned
    population.

    ``std`` is the SAMPLE standard deviation (``ddof=1``) — unlike
    ``frontend/src/lib/measureStats.ts``'s ``meanSd`` (population,
    ``ddof=0``, matching the MATLAB status-bar convention for a
    handful of manual measurements), a particle/grain population is
    exactly the case ``ddof=1`` exists for: N is usually large and the
    population is a SAMPLE of a size distribution the user wants to
    generalise from, not the complete population of interest.

    Quartiles use linear interpolation between order statistics
    (``np.percentile``'s default method — "Type 7" in Hyndman & Fan
    1996), the same convention this codebase already uses for
    percentile calls in ``calc/normalize.py`` and
    ``calc/trace_roughness.py``.
    """

    n: int
    n_dropped: int
    mean: float
    std: float
    minimum: float
    maximum: float
    median: float
    q1: float
    q3: float


def summarize(values: np.ndarray) -> PopulationSummary:
    """Summary statistics over ``values`` (non-finite entries dropped).

    Raises ``ValueError`` if no finite values remain.
    """
    arr, dropped = _clean(values)
    if arr.size == 0:
        raise ValueError("no finite values to summarize")
    q1, median, q3 = (float(v) for v in np.percentile(arr, [25, 50, 75]))
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else float("nan")
    return PopulationSummary(
        n=arr.size,
        n_dropped=dropped,
        mean=float(arr.mean()),
        std=std,
        minimum=float(arr.min()),
        maximum=float(arr.max()),
        median=median,
        q1=q1,
        q3=q3,
    )


@dataclass(frozen=True)
class DistFit:
    """One ``scipy.stats.*.fit()`` result plus goodness-of-fit metrics.

    ``params`` keys are the distribution's own parameter names —
    scipy's shape-parameter name(s) (``dist.shapes``), always followed
    by ``loc``/``scale`` — e.g. ``{"loc": ..., "scale": ...}`` for
    normal, ``{"s": ..., "loc": ..., "scale": ...}`` for lognormal.

    ``aic`` is the Akaike Information Criterion, ``2k - 2*log_likelihood``
    (lower is better). ``ks_statistic``/``ks_pvalue`` are a
    Kolmogorov-Smirnov goodness-of-fit test of the SAME sample against
    its own fitted distribution: because the parameters were estimated
    from this sample rather than specified independently, the reported
    p-value is optimistic (no Lilliefors-style correction is applied)
    — treat it as a descriptive "how far is the empirical CDF from the
    fitted curve", not a calibrated hypothesis test.
    """

    kind: str
    params: dict[str, float]
    log_likelihood: float
    aic: float
    ks_statistic: float
    ks_pvalue: float


def fit_distribution(values: np.ndarray, kind: str) -> DistFit:
    """Fit ``kind`` (``"normal"`` | ``"lognormal"`` | ``"weibull"``) to
    ``values``.

    lognormal/weibull are fit with ``floc=0`` (location pinned at
    zero): both are conventionally 2-parameter distributions for a
    strictly-positive quantity (shape, scale), and leaving loc free
    lets the MLE chase a spurious shift with no physical meaning for a
    particle/grain size while destabilising the fit on small samples.
    This keeps every fit here at exactly 2 FREE parameters, which is
    also why AIC and raw log-likelihood rank identically (see
    ``fit_all``).

    Raises ``ValueError`` if ``kind`` is unknown, fewer than
    ``MIN_FIT_N`` finite values remain after dropping NaN/Inf, or
    (lognormal/weibull only) any remaining value is <= 0.
    """
    if kind not in _DISTS:
        raise ValueError(
            f"unknown distribution kind {kind!r}; expected one of "
            f"{sorted(_DISTS)}"
        )
    arr, _ = _clean(values)
    if arr.size < MIN_FIT_N:
        raise ValueError(
            f"need at least {MIN_FIT_N} finite values to fit a "
            f"distribution, got {arr.size}"
        )
    if kind != "normal" and bool(np.any(arr <= 0)):
        raise ValueError(f"{kind} fit requires strictly positive values")

    dist = _DISTS[kind]
    fit_kwargs = {} if kind == "normal" else {"floc": 0.0}
    # MLE optimisation on small/near-degenerate samples can raise benign
    # RuntimeWarning/OptimizeWarning from scipy's internal Nelder-Mead
    # search (e.g. while probing a boundary) that don't indicate a bad
    # result — a genuinely bad fit still shows up in the KS
    # statistic/AIC below, so these are swallowed here rather than left
    # to trip pytest's filterwarnings=error.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        warnings.simplefilter("ignore", category=OptimizeWarning)
        params = dist.fit(arr, **fit_kwargs)

    log_l = float(np.sum(dist.logpdf(arr, *params)))
    k = len(params)  # loc+scale, or shape+loc+scale
    if kind != "normal":
        k -= 1  # floc was fixed, not estimated — 2 free params either way
    aic = float(2 * k - 2 * log_l)
    ks_stat, ks_p = stats.kstest(arr, dist.cdf, args=tuple(params))

    shape_names = (
        [s.strip() for s in dist.shapes.split(",")] if dist.shapes else []
    )
    param_names = [*shape_names, "loc", "scale"]
    param_dict = {
        name: float(v) for name, v in zip(param_names, params, strict=True)
    }

    return DistFit(
        kind=kind,
        params=param_dict,
        log_likelihood=log_l,
        aic=aic,
        ks_statistic=float(ks_stat),
        ks_pvalue=float(ks_p),
    )


@dataclass(frozen=True)
class AllFits:
    """All three fits plus the AIC-selected ``best``."""

    normal: DistFit
    lognormal: DistFit
    weibull: DistFit
    best: str  # "normal" | "lognormal" | "weibull"


def fit_all(values: np.ndarray) -> AllFits:
    """Fit normal, lognormal and weibull; ``best`` = lowest AIC.

    All three fits here use exactly 2 free parameters (see
    ``fit_distribution``), so ranking by AIC is equivalent to ranking
    by raw log-likelihood — AIC is used anyway because it is the
    metric that stays correct if a future distribution with a
    different parameter count is added.

    lognormal/weibull require strictly positive values (see
    ``fit_distribution``); for a population containing zero or
    negative values, call ``fit_distribution(values, "normal")``
    directly instead of this.
    """
    fits = {
        "normal": fit_distribution(values, "normal"),
        "lognormal": fit_distribution(values, "lognormal"),
        "weibull": fit_distribution(values, "weibull"),
    }
    best = min(fits, key=lambda k: fits[k].aic)
    return AllFits(
        normal=fits["normal"],
        lognormal=fits["lognormal"],
        weibull=fits["weibull"],
        best=best,
    )


@dataclass(frozen=True)
class Histogram:
    edges: np.ndarray  # shape (n_bins + 1,)
    counts: np.ndarray  # shape (n_bins,), int64


def histogram_bins(values: np.ndarray) -> Histogram:
    """Bin edges via the Freedman-Diaconis rule, plus their counts.

    bin width = ``2 * IQR / N**(1/3)``; ``n_bins = ceil((max-min) /
    width)``. Falls back to the sqrt-choice rule (``n_bins =
    ceil(sqrt(N))``) when the IQR is degenerate (0 — e.g. more than
    half the population shares one value), since FD's width would be
    zero/undefined there. When EVERY value is identical (``min ==
    max``) there is no width to divide at all, so a single bin
    covering +/-5% of the value (or +/-0.5 absolute when the value is
    exactly 0) is returned instead.

    ``n_bins`` is capped at 200 to guard against a pathological
    near-zero IQR blowing the bin count up on a wide range.

    Raises ``ValueError`` if no finite values remain.
    """
    arr, _ = _clean(values)
    if arr.size == 0:
        raise ValueError("no finite values to histogram")
    lo, hi = float(arr.min()), float(arr.max())
    if lo == hi:
        pad = 0.5 if lo == 0.0 else abs(lo) * 0.05
        edges = np.array([lo - pad, hi + pad])
        counts = np.array([arr.size], dtype=np.int64)
        return Histogram(edges=edges, counts=counts)

    q1, q3 = np.percentile(arr, [25, 75])
    iqr = float(q3 - q1)
    n_bins = 0
    if iqr > 0:
        width = 2 * iqr / (arr.size ** (1 / 3))
        if width > 0:
            n_bins = int(np.ceil((hi - lo) / width))
    if n_bins <= 0:
        n_bins = int(np.ceil(np.sqrt(arr.size)))  # degenerate-IQR fallback
    n_bins = max(1, min(n_bins, _MAX_HIST_BINS))

    edges = np.linspace(lo, hi, n_bins + 1)
    counts, edges = np.histogram(arr, bins=edges)
    return Histogram(edges=edges, counts=counts.astype(np.int64))
