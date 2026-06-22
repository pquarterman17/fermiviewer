"""Model-based simultaneous multi-edge EELS fitting (PLAN_SPECTRAL_QUANT #2).

Instead of sequential window-integration (one background fit + one signal
integral per edge, ``eels_quant.quantify``), this fits ONE model to the
whole core-loss spectrum:

    spectrum(E) ≈ A·E^(−r)  +  Σ_X  a_X · dσ_X/dE(E)

— a shared power-law background plus, per element, the hydrogenic
differential ionisation cross-section (the edge *shape*) scaled by an
amplitude ``a_X``. Because each shape already carries the cross-section
magnitude (it is dσ/dE in m²/eV), the fitted amplitudes are directly
proportional to areal densities, so at% = 100·a_X / Σ a. This resolves
overlapping edges (Mn-L₂,₃ / O-K, rare-earth M) that window-integration
mis-assigns, and yields per-amplitude 1σ errors from the fit covariance.

The differential shape is the per-channel form of
``eels_quant.cross_section`` (same Egerton SIGMAK2/SIGMAL2 integrand), so
its window integral reproduces that function — verified in tests. GOS
cross-sections (PLAN #3) can later swap in via the same ``edge_shape_fn``
seam. Pure library: numpy + the spectral_fit core only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eels_quant import ElementEdge
from fermiviewer.calc.spectral_fit import (
    Component,
    fit_spectrum,
    power_law,
)

__all__ = [
    "EdgeFitMapResult",
    "EdgeFitResult",
    "edge_shape_fn",
    "fit_edges",
    "fit_edges_map",
]

# Physical constants — mirror eels_quant.cross_section verbatim.
_A0 = 5.29177210903e-11
_R_EV = 13.605693122994
_MC2_EV = 510998.95
_NORM_FLOOR = 5000.0   # normalisation-grid span (cross_section's max(50Δ,5000) floor)
_EPS = np.finfo(np.float64).eps


def _kinematics(e0_kv: float, beta_mrad: float) -> tuple[float, float, float]:
    e0_ev = e0_kv * 1e3
    gamma = 1.0 + e0_ev / _MC2_EV
    beta2 = 1.0 - 1.0 / gamma**2
    t_ev = 0.5 * _MC2_EV * beta2
    beta_rad = beta_mrad * 1e-3
    return gamma, t_ev, beta_rad


def _shell_params(shell: str) -> tuple[int, float]:
    if shell == "K":
        return 2, 3.7
    if shell == "L":
        return 4, 2.7
    raise ValueError("shell must be 'K' or 'L'")


def edge_shape_fn(
    z: int, shell: str, e0_kv: float, beta_mrad: float, onset_ev: float
) -> Callable[[np.ndarray], np.ndarray]:
    """Closure E → dσ/dE (m², per eV), 0 below onset.

    The per-channel form of ``eels_quant.cross_section``: integrating the
    returned shape over [onset, onset+Δ] reproduces that function (for Δ
    within the 5 keV normalisation floor). The expensive occupancy
    normalisation is computed once here; the returned closure is cheap to
    call repeatedly inside the optimiser.
    """
    gamma, t_ev, beta_rad = _kinematics(e0_kv, beta_mrad)
    occ, s_exp = _shell_params(shell)

    def g_shape(e: np.ndarray) -> np.ndarray:
        return (e / onset_ev) * (onset_ev / e) ** s_exp

    e_norm = np.linspace(onset_ev, onset_ev + _NORM_FLOOR, 4000)
    g_norm = occ / float(np.trapezoid(g_shape(e_norm), e_norm))

    def shape(energy: np.ndarray) -> np.ndarray:
        e = np.asarray(energy, dtype=np.float64)
        out = np.zeros_like(e)
        above = e >= onset_ev
        ea = np.maximum(e[above], _EPS)
        theta_e = ea / (2.0 * gamma * t_ev)
        ang = np.log(1.0 + (beta_rad / theta_e) ** 2)
        pref = 4.0 * np.pi * _A0**2 * (_R_EV / ea) * (_R_EV / t_ev)
        out[above] = pref * g_norm * g_shape(ea) * ang
        return out

    return shape


@dataclass(frozen=True)
class EdgeFitResult:
    elements: list[str]
    atomic_percent: np.ndarray   # [M] — sums to 100
    amplitudes: np.ndarray       # [M] fitted areal-density proxies
    amplitude_errors: np.ndarray  # [M] 1σ from the fit covariance
    background: np.ndarray       # [nE] fitted power-law background
    edge_curves: np.ndarray      # [M, nE] fitted per-edge contributions
    model: np.ndarray            # [nE] total fitted model
    reduced_chi2: float
    success: bool


def _seed_background(
    energy: np.ndarray, spectrum: np.ndarray, first_onset: float
) -> tuple[float, float]:
    """Quick power-law seed (A, r) from the pre-edge region (log-log lstsq)."""
    pre = (energy > 0) & (energy < first_onset) & (spectrum > 0)
    if pre.sum() >= 2:
        coef = np.polyfit(np.log(energy[pre]), np.log(spectrum[pre]), 1)
        return float(np.exp(coef[1])), float(-coef[0])
    return float(np.maximum(spectrum, 0).max() or 1.0), 3.0


def fit_edges(
    energy: np.ndarray,
    spectrum: np.ndarray,
    elements: list[ElementEdge],
    e0_kv: float,
    beta_mrad: float,
    *,
    fit_range: tuple[float, float] | None = None,
    weights: np.ndarray | str | None = None,
) -> EdgeFitResult:
    """Fit background + all edges simultaneously; return at% + per-edge fits.

    ``fit_range`` (e_lo, e_hi) restricts the fit window (defaults to the
    span from the first edge's background window to the axis end). The
    edge onset/shell/z come from each :class:`ElementEdge`; the signal/
    background windows are not used (the model spans the whole range).
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    if energy.shape != spectrum.shape:
        raise ValueError("energy and spectrum must be equal-length 1-D arrays")
    if not elements:
        raise ValueError("need at least one edge to fit")

    onsets = [el.onset_ev for el in elements]
    first_onset = min(onsets)
    if fit_range is None:
        lo = min((el.bg_window[0] for el in elements), default=first_onset)
        fit_range = (float(lo), float(energy.max()))

    # build the (common-scaled) edge shapes for numerical conditioning;
    # the shared SCALE cancels in the at% ratio
    shape_fns = [
        edge_shape_fn(el.z, el.shell, e0_kv, beta_mrad, el.onset_ev)
        for el in elements
    ]
    peaks = [float(fn(energy).max()) for fn in shape_fns]
    scale = 1.0 / max([p for p in peaks if p > 0] or [1.0])

    a_seed, r_seed = _seed_background(energy, spectrum, first_onset)
    bg = power_law("bg", amp=a_seed, exponent=r_seed)

    edge_comps: list[Component] = []
    for el, fn in zip(elements, shape_fns, strict=True):
        name = f"{el.element}_{el.shell}"
        # amplitude seed: rough counts / scaled-shape peak
        shp_peak = max(float(fn(energy).max()) * scale, _EPS)
        a0 = max(float(np.nanmax(spectrum)) / shp_peak, _EPS) * 0.1

        def f(e: np.ndarray, p: np.ndarray, _fn=fn) -> np.ndarray:
            return np.asarray(p[0] * scale * _fn(e), dtype=np.float64)

        edge_comps.append(
            Component(name, ("n",), f, (a0,), (0.0,), (np.inf,))
        )

    res = fit_spectrum(
        energy, spectrum, [bg, *edge_comps],
        weights=weights, fit_range=fit_range,
    )

    syms = [el.element for el in elements]
    amps = np.array([res.params[f"{c.name}_n"] for c in edge_comps])
    amp_err = np.array([res.errors[f"{c.name}_n"] for c in edge_comps])
    total = amps.sum()
    at_pct = 100.0 * amps / total if total > 0 else np.zeros(len(elements))
    edge_curves = np.array([res.component_curves[c.name] for c in edge_comps])

    return EdgeFitResult(
        elements=syms,
        atomic_percent=at_pct,
        amplitudes=amps,
        amplitude_errors=amp_err,
        background=res.component_curves["bg"],
        edge_curves=edge_curves,
        model=res.model,
        reduced_chi2=res.reduced_chi2,
        success=res.success,
    )


@dataclass(frozen=True)
class EdgeFitMapResult:
    elements: list[str]
    atomic_percent: np.ndarray   # [Ny, Nx, M]
    amplitudes: np.ndarray       # [Ny, Nx, M]
    background_exponent: float   # r held fixed across the map


def fit_edges_map(
    cube: np.ndarray,
    energy: np.ndarray,
    elements: list[ElementEdge],
    e0_kv: float,
    beta_mrad: float,
    *,
    fit_range: tuple[float, float] | None = None,
) -> EdgeFitMapResult:
    """Per-pixel model fit over an SI cube [Ny, Nx, nE].

    The background exponent r is fixed from the summed-spectrum fit, which
    makes the per-pixel model LINEAR in (background amp, edge amps) — one
    vectorised least-squares solve over all pixels (mirrors
    quantify_map's vectorisation budget) rather than a nonlinear fit each
    pixel. at% comes from the per-pixel edge amplitudes.
    """
    cube = np.asarray(cube, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    if cube.ndim != 3:
        raise ValueError("cube must be [Ny, Nx, nE]")
    ny, nx, ne = cube.shape
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")
    if not elements:
        raise ValueError("need at least one edge to fit")

    # 1) fix r from the summed spectrum (full nonlinear fit, once)
    summed = cube.reshape(ny * nx, ne).sum(axis=0)
    sum_fit = fit_edges(
        energy, summed, elements, e0_kv, beta_mrad, fit_range=fit_range
    )
    # recover r from the fitted background: bg = A·E^−r ⇒ slope in log-log
    bg = sum_fit.background
    good = (energy > 0) & (bg > 0)
    r = float(-np.polyfit(np.log(energy[good]), np.log(bg[good]), 1)[0])

    # 2) build the linear design matrix [E^−r, scaled shapes…]
    if fit_range is None:
        lo = min((el.bg_window[0] for el in elements),
                 default=min(el.onset_ev for el in elements))
        fit_range = (float(lo), float(energy.max()))
    mask = (energy >= fit_range[0]) & (energy <= fit_range[1])
    e_m = energy[mask]

    shape_fns = [
        edge_shape_fn(el.z, el.shell, e0_kv, beta_mrad, el.onset_ev)
        for el in elements
    ]
    peaks = [float(fn(energy).max()) for fn in shape_fns]
    scale = 1.0 / max([p for p in peaks if p > 0] or [1.0])

    cols = [np.maximum(e_m, _EPS) ** (-r)]
    cols.extend(scale * fn(e_m) for fn in shape_fns)
    design = np.column_stack(cols)                          # [K, M+1]

    spec = cube.reshape(ny * nx, ne)[:, mask].T            # [K, Npx]
    coeffs, *_ = np.linalg.lstsq(design, spec, rcond=None)  # [M+1, Npx]
    amps = np.maximum(coeffs[1:], 0.0)                      # [M, Npx]

    total = amps.sum(axis=0)
    at = np.zeros_like(amps)
    has = total > 0
    at[:, has] = 100.0 * amps[:, has] / total[has]

    m = len(elements)

    def to_map(arr: np.ndarray) -> np.ndarray:
        return np.moveaxis(arr.reshape(m, ny, nx), 0, 2)

    return EdgeFitMapResult(
        elements=[el.element for el in elements],
        atomic_percent=to_map(at),
        amplitudes=to_map(amps),
        background_exponent=r,
    )
