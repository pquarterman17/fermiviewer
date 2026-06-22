"""Shared least-squares spectral fitting core.

One model-fit engine that both EELS (``eels_model``) and EDS
(``eds_continuum`` / ``eds_peakfit``) build on, replacing ad-hoc
per-domain curve fits. A spectrum is modelled as a sum of named
``Component`` curves (backgrounds, edges, peaks); ``fit_spectrum``
optimises all their parameters jointly and returns best-fit values,
1σ errors, per-component curves and the reduced χ².

Key Decision (2026-06-21): the optimiser is
``scipy.optimize.least_squares`` (already a runtime dep) rather than
lmfit (BSD-3 but a *new* dependency). The named-parameter, bounds and
covariance machinery lmfit would give for free is small enough to build
here, keeping zero new runtime deps in line with the project's
dependency-minimisation rule. Covariance is recovered from the Jacobian
at the solution (cov = (JᵀJ)⁻¹ · reduced χ²) and feeds the uncertainty
module (PLAN_SPECTRAL_QUANT #6).

Pure library: numpy + scipy.optimize only. No fastapi/pydantic/route
imports (enforced by tests/test_repo_integrity.py).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

__all__ = [
    "Component",
    "FitResult",
    "evaluate",
    "fit_spectrum",
    "gaussian",
    "linear_background",
    "polynomial_background",
    "power_law",
]

# A component evaluator: (energy axis, this component's params) → curve.
ComponentFunc = Callable[[np.ndarray, np.ndarray], np.ndarray]

_EPS = 1e-12
_INF = math.inf


@dataclass(frozen=True)
class Component:
    """One additive model term over the energy axis.

    ``func(energy, params)`` receives ONLY this component's parameters
    (in ``param_names`` order) and returns a same-length curve. ``p0`` is
    the initial guess; ``lower``/``upper`` are per-parameter bounds
    (use ±inf for unbounded). Parameter names are prefixed with the
    component ``name`` in the fit result so several components can share
    plain names like "amp".
    """

    name: str
    param_names: tuple[str, ...]
    func: ComponentFunc
    p0: tuple[float, ...]
    lower: tuple[float, ...] = ()
    upper: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        n = len(self.param_names)
        if len(self.p0) != n:
            raise ValueError(
                f"component '{self.name}': {n} params but {len(self.p0)} p0"
            )
        # default bounds = unbounded
        if not self.lower:
            object.__setattr__(self, "lower", (-_INF,) * n)
        if not self.upper:
            object.__setattr__(self, "upper", (_INF,) * n)
        if len(self.lower) != n or len(self.upper) != n:
            raise ValueError(f"component '{self.name}': bound length mismatch")


@dataclass(frozen=True)
class FitResult:
    """Outcome of :func:`fit_spectrum`.

    ``params``/``errors`` are keyed by ``"<component>_<param>"``.
    ``component_curves`` holds each component evaluated at the solution;
    ``model`` is their sum. ``covariance`` is the full parameter
    covariance in ``param_order``; ``errors`` are its √diag.
    """

    params: dict[str, float]
    errors: dict[str, float]
    param_order: tuple[str, ...]
    model: np.ndarray
    component_curves: dict[str, np.ndarray]
    residual: np.ndarray
    reduced_chi2: float
    covariance: np.ndarray
    success: bool
    nfev: int = 0
    cost: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


def _slices(components: Sequence[Component]) -> list[slice]:
    out, i = [], 0
    for c in components:
        n = len(c.param_names)
        out.append(slice(i, i + n))
        i += n
    return out


def evaluate(
    components: Sequence[Component],
    energy: np.ndarray,
    params: np.ndarray | Sequence[float],
) -> dict[str, np.ndarray]:
    """Evaluate each component at ``params`` (flat, in component order).

    Returns a name→curve dict; sum the values for the full model.
    """
    energy = np.asarray(energy, dtype=np.float64)
    flat = np.asarray(params, dtype=np.float64)
    curves: dict[str, np.ndarray] = {}
    for c, sl in zip(components, _slices(components), strict=True):
        curves[c.name] = np.asarray(
            c.func(energy, flat[sl]), dtype=np.float64
        )
    return curves


def _weights(
    counts: np.ndarray, weights: np.ndarray | str | None
) -> np.ndarray:
    """Resolve the weighting scheme to a 1/σ² array.

    ``None`` → uniform (ones); ``"poisson"`` → 1/max(counts, 1) (counting
    statistics); an array → used verbatim (already 1/σ²).
    """
    if weights is None:
        return np.ones_like(counts)
    if isinstance(weights, str):
        if weights == "poisson":
            return np.asarray(1.0 / np.maximum(counts, 1.0), dtype=np.float64)
        raise ValueError(f"unknown weights scheme '{weights}'")
    w = np.asarray(weights, dtype=np.float64)
    if w.shape != counts.shape:
        raise ValueError("weights array must match counts shape")
    return w


def fit_spectrum(
    energy: np.ndarray,
    counts: np.ndarray,
    components: Sequence[Component],
    *,
    weights: np.ndarray | str | None = None,
    max_nfev: int | None = None,
    fit_range: tuple[float, float] | None = None,
) -> FitResult:
    """Fit ``sum(components)`` to ``counts`` over ``energy``.

    Parameters
    ----------
    energy, counts : 1-D arrays of equal length.
    components : the additive model terms.
    weights : ``None`` (uniform), ``"poisson"`` (1/N counting variance),
        or a 1/σ² array. Used both to weight the residual and to scale the
        returned covariance.
    fit_range : optional (e_lo, e_hi) to restrict the fit to a sub-window
        (e.g. exclude a noisy ZLP); components are still returned over the
        full input axis.

    Returns
    -------
    FitResult with best-fit params, 1σ errors, per-component curves over
    the FULL input axis, residual (model − counts over the fit window),
    and reduced χ².
    """
    energy = np.asarray(energy, dtype=np.float64)
    counts = np.asarray(counts, dtype=np.float64)
    if energy.shape != counts.shape or energy.ndim != 1:
        raise ValueError("energy and counts must be equal-length 1-D arrays")
    if not components:
        raise ValueError("need at least one component to fit")

    mask = np.ones(energy.shape, dtype=bool)
    if fit_range is not None:
        lo, hi = fit_range
        mask = (energy >= lo) & (energy <= hi)
        if mask.sum() < 2:
            raise ValueError("fit_range selects fewer than 2 channels")

    e_fit = energy[mask]
    c_fit = counts[mask]
    w = _weights(counts, weights)[mask]
    sqrt_w = np.sqrt(np.maximum(w, 0.0))

    slices = _slices(components)
    x0 = np.concatenate([np.asarray(c.p0, dtype=np.float64) for c in components])
    lower = np.concatenate(
        [np.asarray(c.lower, dtype=np.float64) for c in components]
    )
    upper = np.concatenate(
        [np.asarray(c.upper, dtype=np.float64) for c in components]
    )
    # clamp the initial guess into the (closed) bound box for trf
    x0 = np.clip(x0, lower, upper)

    def residual(p: np.ndarray) -> np.ndarray:
        total = np.zeros_like(e_fit)
        for c, sl in zip(components, slices, strict=True):
            total = total + np.asarray(c.func(e_fit, p[sl]), dtype=np.float64)
        return np.asarray((total - c_fit) * sqrt_w, dtype=np.float64)

    res = least_squares(
        residual, x0, bounds=(lower, upper), method="trf",
        max_nfev=max_nfev,
    )

    n_param = x0.size
    n_data = e_fit.size
    dof = max(n_data - n_param, 1)
    sse = float(2.0 * res.cost)            # res.cost = ½·Σr²
    reduced_chi2 = sse / dof

    cov = _covariance(res.jac, reduced_chi2, n_param)
    perr = np.sqrt(np.clip(np.diag(cov), 0.0, None))

    names: list[str] = []
    for c in components:
        names.extend(f"{c.name}_{pn}" for pn in c.param_names)
    param_order = tuple(names)
    params = {k: float(v) for k, v in zip(param_order, res.x, strict=True)}
    errors = {k: float(v) for k, v in zip(param_order, perr, strict=True)}

    curves = evaluate(components, energy, res.x)        # full axis
    model = np.sum(list(curves.values()), axis=0)

    return FitResult(
        params=params,
        errors=errors,
        param_order=param_order,
        model=model,
        component_curves=curves,
        residual=model[mask] - c_fit,
        reduced_chi2=reduced_chi2,
        covariance=cov,
        success=bool(res.success),
        nfev=int(res.nfev),
        cost=sse,
    )


def _covariance(
    jac: np.ndarray, reduced_chi2: float, n_param: int
) -> np.ndarray:
    """Parameter covariance from the (weighted) Jacobian at the solution.

    cov = (JᵀJ)⁻¹ · reduced χ². Falls back to the pseudo-inverse when JᵀJ
    is singular (degenerate/over-parameterised fit); returns NaNs only if
    even that fails.
    """
    jtj = jac.T @ jac
    try:
        inv = np.linalg.inv(jtj)
    except np.linalg.LinAlgError:
        inv = np.linalg.pinv(jtj)
    return np.asarray(inv * reduced_chi2, dtype=np.float64)


# ── building-block components ────────────────────────────────────────
# Reusable terms for EELS backgrounds/edges and EDS peaks/continuum.


def gaussian(
    name: str,
    *,
    amp: float,
    center: float,
    sigma: float,
    amp_bounds: tuple[float, float] = (0.0, _INF),
    center_bounds: tuple[float, float] | None = None,
    sigma_bounds: tuple[float, float] = (_EPS, _INF),
) -> Component:
    """A Gaussian peak: amp·exp(−½((E−center)/sigma)²)."""
    if center_bounds is None:
        center_bounds = (-_INF, _INF)

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, c, s = p
        s = max(float(s), _EPS)
        return np.asarray(a * np.exp(-0.5 * ((energy - c) / s) ** 2), dtype=np.float64)

    return Component(
        name, ("amp", "center", "sigma"), f,
        (amp, center, sigma),
        (amp_bounds[0], center_bounds[0], sigma_bounds[0]),
        (amp_bounds[1], center_bounds[1], sigma_bounds[1]),
    )


def power_law(
    name: str,
    *,
    amp: float,
    exponent: float,
    amp_bounds: tuple[float, float] = (0.0, _INF),
    exponent_bounds: tuple[float, float] = (0.0, 12.0),
) -> Component:
    """EELS power-law background A·E^(−r) (E>0 guarded)."""

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, r = p
        e = np.maximum(energy, _EPS)
        return np.asarray(a * np.power(e, -r), dtype=np.float64)

    return Component(
        name, ("amp", "exponent"), f, (amp, exponent),
        (amp_bounds[0], exponent_bounds[0]),
        (amp_bounds[1], exponent_bounds[1]),
    )


def linear_background(
    name: str, *, intercept: float = 0.0, slope: float = 0.0
) -> Component:
    """Linear background a + b·E (unbounded)."""

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        a, b = p
        return np.asarray(a + b * energy, dtype=np.float64)

    return Component(name, ("intercept", "slope"), f, (intercept, slope))


def polynomial_background(
    name: str, coeffs: Sequence[float]
) -> Component:
    """Polynomial background Σ cₖ·Eᵏ, k=0..len-1 (unbounded coefficients)."""
    coeffs = tuple(float(c) for c in coeffs)
    if not coeffs:
        raise ValueError("polynomial_background needs ≥1 coefficient")
    pnames = tuple(f"c{k}" for k in range(len(coeffs)))

    def f(energy: np.ndarray, p: np.ndarray) -> np.ndarray:
        out = np.zeros_like(energy)
        for k, ck in enumerate(p):
            out = out + ck * np.power(energy, k)
        return out

    return Component(name, pnames, f, coeffs)
