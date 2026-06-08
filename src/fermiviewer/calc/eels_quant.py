"""EELS quantification: hydrogenic cross-sections, at% composition, ELNES.

Port of eelsCrossSection.m / eelsQuantify.m / eelsELNES.m (completes the
+imaging/+eels suite). The cross-section is the onset-anchored hydrogenic
model (Egerton SIGMAK2/SIGMAL2 family): Z enters through the edge onset;
the s-exponent and occupancy are per-shell constants — port verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eels import background

__all__ = ["ElementEdge", "QuantResult", "cross_section", "elnes", "quantify"]

_EPS = np.finfo(np.float64).eps


def cross_section(
    z: int, shell: str, e0_kv: float, beta_mrad: float,
    delta_ev: float, onset_ev: float,
) -> float:
    """Partial ionization cross-section (m²) integrated over delta_ev."""
    a0 = 5.29177210903e-11
    r_ev = 13.605693122994
    mc2_ev = 510998.95

    e0_ev = e0_kv * 1e3
    gamma = 1 + e0_ev / mc2_ev
    beta2 = 1 - 1 / gamma**2
    t_ev = 0.5 * mc2_ev * beta2
    beta_rad = beta_mrad * 1e-3

    if shell == "K":
        occ, s_exp = 2, 3.7
    elif shell == "L":
        occ, s_exp = 4, 2.7
    else:
        raise ValueError("shell must be 'K' or 'L'")

    e_grid = np.linspace(onset_ev, onset_ev + delta_ev, 400)

    def g_shape(e: np.ndarray) -> np.ndarray:
        out: np.ndarray = (e / onset_ev) * (onset_ev / e) ** s_exp
        return out

    e_norm = np.linspace(onset_ev, onset_ev + max(50 * delta_ev, 5000), 4000)
    g_norm = occ / np.trapezoid(g_shape(e_norm), e_norm)

    theta_e = e_grid / (2 * gamma * t_ev)
    ang = np.log(1 + (beta_rad / theta_e) ** 2)
    pref = 4 * np.pi * a0**2 * (r_ev / e_grid) * (r_ev / t_ev)
    sigma = float(np.trapezoid(pref * g_norm * g_shape(e_grid) * ang, e_grid))
    return max(sigma, 0.0)


@dataclass(frozen=True)
class ElementEdge:
    element: str
    shell: str                       # 'K' | 'L'
    z: int
    onset_ev: float
    signal_window: tuple[float, float]
    bg_window: tuple[float, float]


@dataclass(frozen=True)
class QuantResult:
    elements: list[str]
    atomic_percent: np.ndarray
    intensity: np.ndarray
    sigma: np.ndarray
    areal_ratio: np.ndarray


def quantify(
    energy: np.ndarray,
    spectrum: np.ndarray,
    elements: list[ElementEdge],
    e0_kv: float,
    beta_mrad: float,
    bg_method: str = "powerlaw",
) -> QuantResult:
    """at% composition from core-loss edges (port of eelsQuantify.m).

    N_X ∝ I_X / σ_X per edge; atomic percent from normalised ratios.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()

    syms, intens, sigmas, ratios = [], [], [], []
    for el in elements:
        sig, _, _ = background(energy, spectrum,
                               fit_window=el.bg_window, method=bg_method)
        mask = (energy >= el.signal_window[0]) & (energy <= el.signal_window[1])
        if mask.sum() < 2:
            raise ValueError(
                f"{el.element}: signal window {el.signal_window} has < 2 channels"
            )
        i_x = max(float(np.trapezoid(sig[mask], energy[mask])), 0.0)
        delta = el.signal_window[1] - el.signal_window[0]
        s_x = cross_section(el.z, el.shell, e0_kv, beta_mrad, delta, el.onset_ev)
        syms.append(el.element)
        intens.append(i_x)
        sigmas.append(s_x)
        ratios.append(i_x / s_x if s_x > 0 else 0.0)

    ratio_arr = np.array(ratios)
    total = ratio_arr.sum()
    at_pct = 100 * ratio_arr / total if total > 0 else np.zeros(len(elements))
    return QuantResult(syms, at_pct, np.array(intens), np.array(sigmas), ratio_arr)


@dataclass(frozen=True)
class QuantMapResult:
    elements: list[str]
    atomic_percent: np.ndarray   # [Ny, Nx, M] — sums to 100 where signal
    intensity: np.ndarray        # [Ny, Nx, M]
    sigma: np.ndarray            # [M]
    areal_ratio: np.ndarray      # [Ny, Nx, M]


def quantify_map(
    cube: np.ndarray,
    energy: np.ndarray,
    elements: list[ElementEdge],
    e0_kv: float,
    beta_mrad: float,
    bg_method: str = "powerlaw",
) -> QuantMapResult:
    """Per-pixel SI at% maps (port of eelsQuantifyMap.m). Identical
    per-channel arithmetic to quantify() — a uniform cube reproduces the
    scalar result to round-off — with ONE vectorised background solve
    per element (the eelsExtractMap approach) and σ computed once per
    element, never per pixel."""
    cube = np.asarray(cube, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    if cube.ndim != 3:
        raise ValueError("cube must be [Ny, Nx, nE]")
    ny, nx, ne = cube.shape
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")
    if bg_method not in ("powerlaw", "exponential"):
        raise ValueError("bg_method must be 'powerlaw' or 'exponential'")

    n_px = ny * nx
    m = len(elements)
    spec = cube.reshape(n_px, ne).T                       # [nE, Np]
    eps = np.finfo(np.float64).eps

    syms: list[str] = []
    sigma = np.zeros(m)
    intensity = np.zeros((m, n_px))
    areal = np.zeros((m, n_px))

    for k, el in enumerate(elements):
        fit_mask = (energy >= el.bg_window[0]) & (energy <= el.bg_window[1])
        if fit_mask.sum() < 2:
            raise ValueError(
                f"{el.element}: bg window {el.bg_window} has < 2 channels"
            )
        sig_mask = (
            (energy >= el.signal_window[0]) & (energy <= el.signal_window[1])
        )
        if sig_mask.sum() < 2:
            raise ValueError(
                f"{el.element}: signal window {el.signal_window} "
                "has < 2 channels"
            )

        e_fit = energy[fit_mask]
        e_sig = energy[sig_mask][:, None]                  # [Ks, 1]
        i_fit = np.maximum(spec[fit_mask], eps)            # [K, Np]

        # vectorised background fit — the exp(A)·… two-step matches the
        # scalar eelsBackground so degenerate pixels over/underflow
        # identically (parity note ported from eelsExtractMap)
        if bg_method == "powerlaw":
            design = np.column_stack([np.log(e_fit), np.ones(e_fit.size)])
            coeffs, *_ = np.linalg.lstsq(design, np.log(i_fit), rcond=None)
            a = np.exp(coeffs[1])                          # [Np]
            r = -coeffs[0]
            with np.errstate(over="ignore"):
                bg_sig = np.maximum(e_sig, eps) ** (-r) * a
        else:
            design = np.column_stack([e_fit, np.ones(e_fit.size)])
            coeffs, *_ = np.linalg.lstsq(design, np.log(i_fit), rcond=None)
            a = np.exp(coeffs[1])
            bg_sig = np.exp(e_sig * coeffs[0]) * a

        # subtract + clamp per channel BEFORE integrating (scalar order)
        resid = np.maximum(spec[sig_mask] - bg_sig, 0.0)
        resid[~np.isfinite(resid)] = 0.0
        i_x = np.maximum(
            np.trapezoid(resid, energy[sig_mask], axis=0), 0.0
        )                                                  # [Np]

        delta = el.signal_window[1] - el.signal_window[0]
        s_x = cross_section(
            el.z, el.shell, e0_kv, beta_mrad, delta, el.onset_ev
        )
        syms.append(el.element)
        sigma[k] = s_x
        intensity[k] = i_x
        if s_x > 0:
            areal[k] = i_x / s_x

    total = areal.sum(axis=0)                              # [Np]
    at_pct = np.zeros((m, n_px))
    has = total > 0
    at_pct[:, has] = 100.0 * areal[:, has] / total[has]

    def to_maps(arr: np.ndarray) -> np.ndarray:
        out: np.ndarray = np.moveaxis(arr.reshape(m, ny, nx), 0, 2)
        return out

    return QuantMapResult(
        elements=syms,
        atomic_percent=to_maps(at_pct),
        intensity=to_maps(intensity),
        sigma=sigma,
        areal_ratio=to_maps(areal),
    )


@dataclass(frozen=True)
class ElnesResult:
    relative_energy: np.ndarray
    intensity: np.ndarray
    edge_jump: float
    edge_onset: float
    background_params: dict[str, float]


def elnes(
    energy: np.ndarray,
    spectrum: np.ndarray,
    edge_onset: float,
    fit_window: tuple[float, float],
    elnes_window: tuple[float, float] = (0.0, 30.0),
    method: str = "powerlaw",
    normalize: bool = True,
) -> ElnesResult:
    """Near-edge fine structure extraction (port of eelsELNES.m)."""
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    if fit_window[0] >= fit_window[1]:
        raise ValueError("fit_window must be increasing")
    if fit_window[1] >= edge_onset:
        raise ValueError("fit_window must lie entirely below edge_onset")

    signal, _, params = background(energy, spectrum,
                                   fit_window=fit_window, method=method)
    mask = (energy >= edge_onset + elnes_window[0]) & (
        energy <= edge_onset + elnes_window[1]
    )
    if mask.sum() < 2:
        raise ValueError("ELNES window contains fewer than 2 channels")

    e_rel = energy[mask] - edge_onset
    inten = signal[mask]
    jump_mask = (energy >= edge_onset) & (energy <= edge_onset + 5)
    edge_jump = float(signal[jump_mask].mean()) if jump_mask.any() else float(inten[0])
    edge_jump = max(edge_jump, _EPS)
    if normalize and edge_jump > 0:
        inten = inten / edge_jump
    return ElnesResult(e_rel, inten, edge_jump, edge_onset, params)
