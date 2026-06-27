"""Uncertainty propagation for EELS/EDS quantification (PLAN_SPECTRAL_QUANT #6).

Turns demo-grade composition numbers into publication-grade ones by attaching
a 1σ error bar to every at%/wt% value. Two input regimes feed one propagation
core:

- **Window-integration** (``eels_quant.quantify``, the EDS line-window maps):
  an element's net intensity is a trapezoid integral of the *gross* counts, so
  its variance follows Poisson counting statistics, ``var(N) = N``. For
  ``I = Σ wₖ·Nₖ`` this gives ``var(I) = Σ wₖ²·Nₖ`` (:func:`integral_variance`).
  Using gross (not background-subtracted) counts is exactly Egerton's
  leading-order net-signal variance ``var(I_net) ≈ I_net + I_bg`` — the
  background-fit extrapolation refinement (his *h* factor) is a documented
  second-order term we omit.

- **Model fitting** (``eels_model.fit_edges``, ``eds_peakfit.fit_peaks``): the
  net intensity is a fitted amplitude whose 1σ already comes from the fit
  covariance (:class:`fermiviewer.calc.spectral_fit.FitResult`). We consume
  those errors directly.

Both regimes then flow through the SAME composition — an atomic or weight
fraction ``fracᵢ = qᵢ / Σq`` of some per-element quantity ``q`` (the areal
ratio ``I/σ`` for EELS; ``k·I`` for EDS weight%, ``(k/M)·I`` for EDS atomic%).
The delta method gives ``var(frac) = diag(J·cov·Jᵀ)`` with
``Jᵢⱼ = (δᵢⱼ − fracᵢ)/Σq`` — implemented once in :func:`fraction_variance`
and reused by every domain helper.

Pure library: numpy only. No fastapi/pydantic/route imports (enforced by
``tests/test_repo_integrity.py``). The legacy ``QuantResult``/``ClResult``
dataclasses are left untouched (goldens stay byte-identical); uncertainty is
computed alongside them, never folded into the frozen values.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from fermiviewer.calc.eds import K_FACTORS_200KV
from fermiviewer.calc.elements import ELEMENTS, atomic_mass

__all__ = [
    "ClUncertainty",
    "atomic_fraction_sigma",
    "cliff_lorimer_uncertainty",
    "default_k_factors",
    "eels_atomic_sigma",
    "fraction_variance",
    "integral_variance",
    "poisson_sigma",
    "trapezoid_weights",
]

_EPS = np.finfo(np.float64).eps


# ── Poisson counting-statistics primitives ───────────────────────────


def poisson_sigma(counts: np.ndarray | Sequence[float]) -> np.ndarray:
    """1σ counting-statistics error √N, element-wise.

    Negative inputs (e.g. an over-subtracted channel) clamp to 0 before the
    root, so the result is always real and non-negative.
    """
    c = np.asarray(counts, dtype=np.float64)
    return np.sqrt(np.maximum(c, 0.0))


def trapezoid_weights(x: np.ndarray | Sequence[float]) -> np.ndarray:
    """Per-sample weights ``w`` such that ``Σ wₖ·yₖ == trapezoid(y, x)``.

    For the composite trapezoid rule the coefficient of an interior sample
    ``yₖ`` is ``(x_{k+1} − x_{k−1})/2``; the endpoints get half their single
    adjacent interval. These weights let Poisson variance flow through an
    integral as ``var(I) = Σ wₖ²·var(yₖ)``.
    """
    x = np.asarray(x, dtype=np.float64).ravel()
    n = x.size
    if n < 2:
        raise ValueError("need at least 2 samples for a trapezoid weight")
    w = np.empty(n, dtype=np.float64)
    w[0] = 0.5 * (x[1] - x[0])
    w[-1] = 0.5 * (x[-1] - x[-2])
    w[1:-1] = 0.5 * (x[2:] - x[:-2])
    return w


def integral_variance(
    counts: np.ndarray | Sequence[float], x: np.ndarray | Sequence[float]
) -> float:
    """Variance of ``trapezoid(counts, x)`` under Poisson ``var(N) = N``.

    ``counts`` should be the **gross** counts in the integration window (the
    shot noise is set by the recorded events; background subtraction does not
    reduce it). For ``I = Σ wₖ·Nₖ`` independent Poisson channels,
    ``var(I) = Σ wₖ²·Nₖ``. Negative counts clamp to 0.
    """
    w = trapezoid_weights(x)
    c = np.maximum(np.asarray(counts, dtype=np.float64).ravel(), 0.0)
    if w.shape != c.shape:
        raise ValueError("counts and x must have equal length")
    return float(np.sum(w * w * c))


# ── normalisation (delta-method) propagation ─────────────────────────


def fraction_variance(
    q: np.ndarray | Sequence[float], cov: np.ndarray | Sequence[float]
) -> np.ndarray:
    """Variance of each normalised fraction ``fracᵢ = qᵢ / Σq`` (delta method).

    ``cov`` is either a 1-D vector of per-element variances (independent
    inputs — a diagonal covariance) or a full ``M×M`` covariance matrix
    (correlated fit parameters). Returns a length-``M`` variance array; take
    the square root for the 1σ error on each fraction.

    The Jacobian of the normalisation is ``Jᵢⱼ = (δᵢⱼ − fracᵢ)/S`` with
    ``S = Σq``, so ``var(frac) = diag(J·cov·Jᵀ)``. A single element (M=1) has
    no compositional freedom — its fraction is identically 1 and the returned
    variance is 0. A non-positive or non-finite total yields NaN.
    """
    q = np.asarray(q, dtype=np.float64).ravel()
    m = q.size
    s = float(q.sum())
    if m == 0:
        return np.zeros(0, dtype=np.float64)
    if not np.isfinite(s) or s <= 0:
        return np.full(m, np.nan, dtype=np.float64)

    frac = q / s
    cov = np.asarray(cov, dtype=np.float64)
    if cov.ndim == 1:
        if cov.shape != (m,):
            raise ValueError("variance vector must match q length")
        cov = np.diag(cov)
    elif cov.shape != (m, m):
        raise ValueError("covariance must be (M,) or (M, M)")

    jac = (np.eye(m) - frac[:, None]) / s          # Jᵢⱼ = (δᵢⱼ − fracᵢ)/S
    var = np.einsum("ij,jk,ik->i", jac, cov, jac)
    return np.asarray(np.maximum(var, 0.0), dtype=np.float64)


def atomic_fraction_sigma(
    q: np.ndarray | Sequence[float], q_sigma: np.ndarray | Sequence[float]
) -> np.ndarray:
    """Percent 1σ of ``qᵢ/Σq`` given independent 1σ errors ``q_sigma`` on ``q``.

    Convenience wrapper used by the model-fit paths where each element's
    numerator (a fitted amplitude or areal ratio) carries its own 1σ. Returns
    the error in **percentage points** (i.e. already ×100), matching the at%/
    wt% convention of the quant routes.
    """
    q_sigma = np.asarray(q_sigma, dtype=np.float64).ravel()
    return np.asarray(100.0 * np.sqrt(fraction_variance(q, q_sigma**2)), dtype=np.float64)


# ── EELS: Poisson error on window-integration at% ────────────────────


def eels_atomic_sigma(
    energy: np.ndarray,
    spectrum: np.ndarray,
    signal_windows: Sequence[tuple[float, float]],
    areal_ratio: np.ndarray | Sequence[float],
    sigma: np.ndarray | Sequence[float],
) -> np.ndarray:
    """1σ on EELS at% from Poisson counting statistics (percentage points).

    Mirrors ``eels_quant.quantify``: per edge the net intensity is integrated
    over ``signal_window``; here we take the Poisson variance of that integral
    from the **gross** spectrum, divide by the (constant) cross-section² to get
    ``var(areal ratio)``, then propagate the at% normalisation. ``areal_ratio``
    and ``sigma`` come straight from the :class:`QuantResult`.

    Parameters
    ----------
    energy, spectrum : the gross sum-spectrum the quant was run on.
    signal_windows : (lo, hi) eV per edge, in ``areal_ratio`` order.
    areal_ratio : I/σ per edge (``QuantResult.areal_ratio``).
    sigma : partial cross-sections per edge (``QuantResult.sigma``).
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    areal = np.asarray(areal_ratio, dtype=np.float64).ravel()
    xsec = np.asarray(sigma, dtype=np.float64).ravel()
    if not (len(signal_windows) == areal.size == xsec.size):
        raise ValueError("signal_windows, areal_ratio, sigma length mismatch")

    var_i = np.empty(areal.size, dtype=np.float64)
    for k, (lo, hi) in enumerate(signal_windows):
        mask = (energy >= lo) & (energy <= hi)
        if mask.sum() < 2:
            var_i[k] = np.nan
        else:
            var_i[k] = integral_variance(spectrum[mask], energy[mask])

    # r = I/σ  ⇒  var(r) = var(I)/σ²   (σ is a fixed cross-section)
    safe = xsec > 0
    var_r = np.where(safe, var_i / np.where(safe, xsec, 1.0) ** 2, np.nan)
    return np.asarray(100.0 * np.sqrt(fraction_variance(areal, var_r)), dtype=np.float64)


# ── EDS: Cliff-Lorimer at%/wt% error (Poisson OR fit-error input) ────


class ClUncertainty:
    """1σ errors (percentage points) on Cliff-Lorimer at%/wt%.

    ``atomic_pct_sigma`` / ``weight_pct_sigma`` are length-M arrays aligned to
    ``elements``. Returned by :func:`cliff_lorimer_uncertainty`.
    """

    __slots__ = ("atomic_pct_sigma", "elements", "weight_pct_sigma")

    def __init__(
        self,
        elements: list[str],
        atomic_pct_sigma: np.ndarray,
        weight_pct_sigma: np.ndarray,
    ) -> None:
        self.elements = elements
        self.atomic_pct_sigma = atomic_pct_sigma
        self.weight_pct_sigma = weight_pct_sigma


def cliff_lorimer_uncertainty(
    net_intensity: np.ndarray | Sequence[float],
    var_intensity: np.ndarray | Sequence[float],
    elements: Sequence[str],
    k_factors: np.ndarray | Sequence[float],
) -> ClUncertainty:
    """1σ on Cliff-Lorimer at%/wt% from per-element net-intensity variances.

    Regime-agnostic: pass Poisson variances (window-integration) **or** squared
    fit errors (peak-deconvolution) as ``var_intensity`` — the propagation is
    identical. Pass the *resolved* k-factors (``ClResult.k_factors``).

    The composition normalisations collapse to a single fraction each:

    - weight%  ``wᵢ = (kᵢ·Iᵢ) / Σ(k·I)`` — numerator ``qᵢ = kᵢ·Iᵢ``
    - atomic%  ``atᵢ = (kᵢ/Mᵢ·Iᵢ) / Σ(k/M·I)`` — the ``1/Σ(k·I)`` weight-norm
      factor is common to all elements and cancels, leaving numerator
      ``qᵢ = (kᵢ/Mᵢ)·Iᵢ``.

    so each reduces to one :func:`fraction_variance` call with
    ``var(qᵢ) = (∂qᵢ/∂Iᵢ)²·var(Iᵢ)``.
    """
    net = np.asarray(net_intensity, dtype=np.float64).ravel()
    var_i = np.asarray(var_intensity, dtype=np.float64).ravel()
    k = np.asarray(k_factors, dtype=np.float64).ravel()
    syms = list(elements)
    n = len(syms)
    if not (net.size == var_i.size == k.size == n):
        raise ValueError("net_intensity, var_intensity, k_factors, elements length mismatch")

    masses = np.array(
        [atomic_mass(s) if s in ELEMENTS else 1.0 for s in syms], dtype=np.float64
    )

    # weight%: q = k·I
    qw = k * net
    var_qw = (k**2) * var_i
    w_sigma = 100.0 * np.sqrt(fraction_variance(qw, var_qw))

    # atomic%: q = (k/M)·I
    km = k / np.maximum(masses, _EPS)
    qa = km * net
    var_qa = (km**2) * var_i
    a_sigma = 100.0 * np.sqrt(fraction_variance(qa, var_qa))

    return ClUncertainty(syms, a_sigma, w_sigma)


def default_k_factors(elements: Sequence[str]) -> np.ndarray:
    """Resolve the built-in 200 kV k-factors for ``elements`` (1.0 fallback).

    Convenience for callers that have only element symbols and want the same
    k-factors :func:`fermiviewer.calc.eds.cliff_lorimer` would use, without
    re-running the quant.
    """
    return np.array(
        [K_FACTORS_200KV.get(s, 1.0) for s in elements], dtype=np.float64
    )
