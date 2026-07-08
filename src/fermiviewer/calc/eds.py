"""EDS quantification: k-factors, line energies, mass absorption,
Cliff-Lorimer, ZAF. Port of fermi-viewer's +imaging/+eds/ (quant half).

CALIBRATED CONSTANTS — do not "fix": the MAC prefactor C = 1.0e22 is
NIST-calibrated (see fermi-viewer memory/CHANGELOG); k-factors are the
200 kV table; fluorescence F is held at 1.0 by design.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.elements import ELEMENTS, atomic_mass, bulk_density

__all__ = [
    "K_FACTORS_200KV",
    "ClResult",
    "ElementAssignment",
    "PeakAssignment",
    "ZafResult",
    "assign_elements",
    "cliff_lorimer",
    "detect_peaks",
    "line_energy",
    "mass_absorption_coeff",
    "zaf_correction",
]

# ── 200 kV Cliff-Lorimer k-factors relative to Si (verbatim) ─────────
K_FACTORS_200KV: dict[str, float] = {
    "B": 4.50, "C": 3.00, "N": 2.20, "O": 1.80, "F": 1.50,
    "Na": 1.10, "Mg": 0.95, "Al": 0.87, "Si": 1.00, "P": 0.97,
    "S": 0.93, "Cl": 0.92, "K": 1.01, "Ca": 1.03, "Sc": 1.05,
    "Ti": 1.07, "V": 1.09, "Cr": 1.13, "Mn": 1.18, "Fe": 1.21,
    "Co": 1.25, "Ni": 1.28, "Cu": 1.32, "Zn": 1.36, "Ga": 1.52,
    "Ge": 1.56, "As": 1.58, "Se": 1.62, "Br": 1.66, "Sr": 2.50,
    "Y": 2.55, "Zr": 2.60, "Nb": 2.65, "Mo": 2.70, "Ru": 2.80,
    "Pd": 2.85, "Ag": 2.90, "Sn": 2.95, "Sb": 3.00, "Ba": 2.70,
    "La": 2.10, "Ce": 2.15, "Hf": 1.70, "Ta": 1.75, "W": 1.80,
    "Pt": 1.90, "Au": 1.85,
}

# ── characteristic line energies, keV (verbatim) ─────────────────────
_K_LINES = dict(zip(
    ["Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S",
     "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni",
     "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Rb", "Sr", "Y", "Zr", "Nb",
     "Mo", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn"],
    [0.108, 0.183, 0.277, 0.392, 0.525, 0.677, 0.849, 1.041, 1.254, 1.487,
     1.740, 2.013, 2.307, 2.622, 2.957, 3.314, 3.692, 4.091, 4.511, 4.952,
     5.415, 5.899, 6.404, 6.930, 7.478, 8.048, 8.639, 9.252, 9.886, 10.544,
     11.222, 11.924, 13.395, 14.165, 14.958, 15.775, 16.615, 17.479, 19.279,
     20.216, 21.177, 22.163, 23.174, 24.210, 25.271],
    strict=True,
))
_L_LINES = dict(zip(
    ["Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
     "As", "Zr", "Nb", "Mo", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb",
     "Ba", "La", "Ce", "Nd", "Sm", "Gd", "Dy", "Er", "Yb", "Hf", "Ta", "W",
     "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Th", "U"],
    [0.341, 0.452, 0.511, 0.573, 0.637, 0.705, 0.776, 0.851, 0.930, 1.012,
     1.098, 1.188, 1.282, 2.042, 2.166, 2.293, 2.559, 2.697, 2.839, 2.984,
     3.133, 3.287, 3.444, 3.605, 4.466, 4.651, 4.840, 5.230, 5.636, 6.057,
     6.495, 6.949, 7.416, 7.899, 8.146, 8.398, 8.652, 8.911, 9.175, 9.442,
     9.713, 9.989, 10.269, 10.551, 10.839, 12.968, 13.615],
    strict=True,
))
_M_LINES = dict(zip(
    ["Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi",
     "Th", "U"],
    [1.645, 1.710, 1.775, 1.843, 1.910, 1.980, 2.051, 2.123, 2.196, 2.271,
     2.342, 2.420, 2.996, 3.171],
    strict=True,
))

_K_ALPHA_KEV: dict[str, float] = {
    "C": 0.277, "N": 0.392, "O": 0.525, "F": 0.677, "Na": 1.041, "Mg": 1.254,
    "Al": 1.487, "Si": 1.740, "P": 2.013, "S": 2.308, "Cl": 2.622, "K": 3.314,
    "Ca": 3.692, "Ti": 4.511, "V": 4.952, "Cr": 5.415, "Mn": 5.899,
    "Fe": 6.404, "Co": 6.930, "Ni": 7.478, "Cu": 8.048, "Zn": 8.639,
    "Ga": 9.252, "Ge": 9.886, "As": 10.544, "Sr": 14.165, "Y": 14.958,
    "Zr": 15.775, "Nb": 16.615, "Mo": 17.479, "Ba": 32.194, "La": 33.442,
}


def line_energy(
    symbol: str, line: str = "auto", beam_kv: float = float("inf")
) -> tuple[float, str]:
    """Principal X-ray line energy (keV) + the line used ('K'/'L'/'M').

    'auto': first of K→L→M whose overvoltage U = beam_kv/edge ≥ 1.5
    (edges approximated as E_K/0.90, E_L/0.80, E_M/0.93); otherwise the
    best-U candidate. Port of lineEnergy.m.
    """
    sym = symbol.strip()
    k_e = _K_LINES.get(sym, float("nan"))
    l_e = _L_LINES.get(sym, float("nan"))
    m_e = _M_LINES.get(sym, float("nan"))

    line = line.upper()
    if line in ("K", "L", "M"):
        e = {"K": k_e, "L": l_e, "M": m_e}[line]
        return e, ("" if np.isnan(e) else line)

    u_min = 1.5
    cand = [("K", k_e, k_e / 0.90), ("L", l_e, l_e / 0.80), ("M", m_e, m_e / 0.93)]
    best_u, best = -np.inf, None
    for name, e, edge in cand:
        if np.isnan(e):
            continue
        u = beam_kv / edge
        if u >= u_min:
            return e, name
        if u > best_u:
            best_u, best = u, (name, e)
    if best is not None:
        return best[1], best[0]
    return float("nan"), ""


def mass_absorption_coeff(emitter: str, absorber: str) -> float:
    """μ/ρ (cm²/g) for the emitter's Kα in the absorber.

    mac = C · Z⁴ · λ³ / A with the calibrated C = 1.0e22 — do not "fix".
    """
    if emitter not in _K_ALPHA_KEV:
        warnings.warn(f"no Kα energy for emitter '{emitter}'", stacklevel=2)
        return float("nan")
    if absorber not in ELEMENTS:
        warnings.warn(f"no element data for absorber '{absorber}'", stacklevel=2)
        return float("nan")
    lambda_cm = (12.398 / _K_ALPHA_KEV[emitter]) * 1e-8
    z = float(ELEMENTS[absorber][0])
    a = atomic_mass(absorber)
    return 1.0e22 * z**4 * lambda_cm**3 / a


# ════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ClResult:
    atomic_pct_maps: list[np.ndarray]
    weight_pct_maps: list[np.ndarray]
    elements: list[str]
    k_factors: np.ndarray
    mask: np.ndarray
    mean_atomic_pct: np.ndarray
    mean_weight_pct: np.ndarray


def _resolve_k(elements: list[str], k_factors: np.ndarray | None) -> np.ndarray:
    if k_factors is not None:
        k = np.asarray(k_factors, dtype=np.float64)
        if k.size != len(elements):
            raise ValueError("k_factors must match elements length")
        return k
    out = np.ones(len(elements))
    for i, sym in enumerate(elements):
        if sym in K_FACTORS_200KV:
            out[i] = K_FACTORS_200KV[sym]
        else:
            warnings.warn(f"no built-in k-factor for '{sym}', using 1.00", stacklevel=3)
    return out


def cliff_lorimer(
    intensity_maps: list[np.ndarray],
    elements: list[str],
    k_factors: np.ndarray | None = None,
    mask_threshold: float = 0.0,
) -> ClResult:
    """Thin-film Cliff-Lorimer quantification (port of cliffLorimer.m).

    w_i ∝ k_i·I_i; atomic fractions via w_i/M_i renormalisation. Pixels
    with total intensity ≤ mask_threshold are NaN.

    Negative input counts are clipped to 0 before any arithmetic. The MATLAB
    reference (+imaging/+eds/cliffLorimer.m) does NOT clip — a stray negative
    count (e.g. a background-over-subtraction artifact upstream) flows
    straight into k·I there and can flip signs in the weight/atomic
    fractions. This is a deliberate, small divergence from the ported
    behaviour: it aligns with :func:`fermiviewer.calc.eds_zeta.zeta_quantify`,
    which already clamps (net-new code, no MATLAB analogue), and with the
    non-negative-counts convention used elsewhere in the quant stack.
    """
    n = len(elements)
    if len(intensity_maps) != n:
        raise ValueError("intensity_maps and elements must have equal length")
    cube = np.stack([np.asarray(m, dtype=np.float64) for m in intensity_maps], axis=2)
    cube = np.clip(cube, 0.0, None)

    k = _resolve_k(elements, k_factors)
    masses = np.array([atomic_mass(s) if s in ELEMENTS else 1.0 for s in elements])

    mask = cube.sum(axis=2) > mask_threshold
    ki = cube * k
    ki_sum = ki.sum(axis=2)
    ki_sum[~mask] = 1.0
    w = ki / ki_sum[:, :, None]

    w_over_m = w / masses
    s = w_over_m.sum(axis=2)
    s[~mask] = 1.0
    at = w_over_m / s[:, :, None]

    w[~mask] = np.nan
    at[~mask] = np.nan

    valid = mask.ravel()
    at_maps = [at[:, :, i] * 100 for i in range(n)]
    w_maps = [w[:, :, i] * 100 for i in range(n)]
    mean_at = np.array([np.nanmean(m.ravel()[valid]) for m in at_maps])
    mean_wt = np.array([np.nanmean(m.ravel()[valid]) for m in w_maps])

    return ClResult(at_maps, w_maps, list(elements), k, mask, mean_at, mean_wt)


# ════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ZafResult:
    atomic_pct_maps: list[np.ndarray]
    weight_pct_maps: list[np.ndarray]
    elements: list[str]
    k_factors: np.ndarray
    mask: np.ndarray
    mean_atomic_pct: np.ndarray
    mean_weight_pct: np.ndarray
    z_factors: np.ndarray
    a_factors: np.ndarray
    f_factors: np.ndarray
    uncorrected: ClResult


def zaf_correction(
    intensity_maps: list[np.ndarray],
    elements: list[str],
    k_factors: np.ndarray | None = None,
    thickness_nm: float = 100.0,
    take_off_angle_deg: float = 20.0,
    density: float = float("nan"),
    mask_threshold: float = 0.0,
    iterations: int = 3,
) -> ZafResult:
    """Iterative thin-film ZAF correction (port of zafCorrection.m).

    Z: mean-Z scaling damped by 1−exp(−t/200); A: χ/(1−e^−χ) absorption
    with χ = (MAC·w̄)·ρ·t·csc(takeoff); F held at 1.0 by design.
    """
    if not 0 < take_off_angle_deg < 90:
        raise ValueError("take_off_angle_deg must be in (0, 90)")
    n = len(elements)
    cl = cliff_lorimer(intensity_maps, elements, k_factors, mask_threshold)
    mask = cl.mask

    z_num = np.array([float(ELEMENTS[s][0]) if s in ELEMENTS else 1.0 for s in elements])
    masses = np.array([atomic_mass(s) if s in ELEMENTS else 1.0 for s in elements])
    dens = np.array(
        [bulk_density(s) if s in ELEMENTS and bulk_density(s) else 5.0 for s in elements],
        dtype=np.float64,
    )
    dens[~np.isfinite(dens) | (dens <= 0)] = 5.0

    csc = 1.0 / np.sin(np.deg2rad(take_off_angle_deg))
    t_cm = thickness_nm * 1e-7

    mac = np.empty((n, n))
    for i, em in enumerate(elements):
        for j, ab in enumerate(elements):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mac[i, j] = mass_absorption_coeff(em, ab)
    mac[~np.isfinite(mac)] = 100.0

    w_mean = np.maximum(cl.mean_weight_pct / 100, 0)
    s0 = w_mean.sum()
    w_mean = w_mean / s0 if s0 > 0 else np.full(n, 1 / n)

    w_cl = np.stack([m / 100 for m in cl.weight_pct_maps], axis=2)
    z_f = np.ones(n)
    a_f = np.ones(n)
    f_f = np.ones(n)
    w_cube = w_cl.copy()
    valid = mask.ravel()

    for _ in range(max(1, int(round(iterations)))):
        mean_z = float((w_mean * z_num).sum())
        z_scale = 1 - np.exp(-thickness_nm / 200)
        z_f = np.where(z_num > 0, 1 + (mean_z / z_num - 1) * z_scale, 1.0)

        rho = density if np.isfinite(density) and density > 0 else float(
            (w_mean * dens).sum()
        )
        if not np.isfinite(rho) or rho <= 0:
            rho = 5.0

        chi = (mac @ w_mean) * rho * t_cm * csc
        a_f = np.ones(n)
        big = np.abs(chi) >= 1e-6
        a_f[big] = chi[big] / (1 - np.exp(-chi[big]))

        zaf = np.maximum(z_f * a_f * f_f, np.finfo(np.float64).eps)
        w_scaled = w_cl / zaf
        w_sum = np.nansum(w_scaled, axis=2)
        w_sum[~mask] = 1.0
        w_cube = w_scaled / w_sum[:, :, None]
        w_cube[~mask] = np.nan

        w_flat = w_cube.reshape(-1, n)[valid]
        w_mean = np.nanmean(w_flat, axis=0)
        s = np.nansum(w_mean)
        if s > 0:
            w_mean = w_mean / s

    w_over_m = w_cube / masses
    s = np.nansum(w_over_m, axis=2)
    s[~mask] = 1.0
    at = w_over_m / s[:, :, None]
    at[~mask] = np.nan

    at_maps = [at[:, :, i] * 100 for i in range(n)]
    w_maps = [w_cube[:, :, i] * 100 for i in range(n)]
    mean_at = np.array([np.nanmean(m.ravel()[valid]) for m in at_maps])
    mean_wt = np.array([np.nanmean(m.ravel()[valid]) for m in w_maps])

    return ZafResult(
        at_maps, w_maps, list(elements), cl.k_factors, mask,
        mean_at, mean_wt, z_f, a_f, f_f, cl,
    )


# ── EDS auto-assign (D10) ─────────────────────────────────────────────

@dataclass(frozen=True)
class ElementAssignment:
    symbol: str
    line: str     # 'K', 'L', or 'M'
    energy_kev: float
    delta_kev: float


@dataclass(frozen=True)
class PeakAssignment:
    peak_kev: float
    candidates: tuple[ElementAssignment, ...]


def detect_peaks(
    energy: np.ndarray,
    counts: np.ndarray,
    threshold: float = 0.05,
) -> np.ndarray:
    """Local-maxima peak detection on an EDS sum spectrum.

    Returns the energies (keV) of peaks above threshold * max(counts).
    Minima-separated local maxima — three-point comparison on the smoothed
    spectrum (box-3 average to suppress single-channel noise).

    Parameters
    ----------
    energy    : 1-D energy axis in keV
    counts    : 1-D count spectrum aligned to energy
    threshold : fraction of the global maximum; peaks below are ignored
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    counts = np.asarray(counts, dtype=np.float64).ravel()
    if energy.size != counts.size:
        raise ValueError("energy and counts must have equal length")
    if counts.size < 3:
        return np.array([], dtype=np.float64)

    # simple box-3 smoothing to suppress single-channel spikes
    smoothed = np.convolve(counts, [1 / 3, 1 / 3, 1 / 3], mode="same")
    floor = float(smoothed.max()) * threshold
    # strictly greater than both neighbours → local max
    is_max = (
        (smoothed[1:-1] > smoothed[:-2])
        & (smoothed[1:-1] > smoothed[2:])
        & (smoothed[1:-1] >= floor)
    )
    # energy indices are offset by 1 because we sliced [1:-1]
    peak_idx = np.where(is_max)[0] + 1
    return energy[peak_idx]


# Build a flat lookup: [(symbol, line, energy_kev), ...] from the known tables.
def _build_line_table() -> list[tuple[str, str, float]]:
    table = []
    for sym, e in _K_LINES.items():
        if not np.isnan(e):
            table.append((sym, "K", e))
    for sym, e in _L_LINES.items():
        if not np.isnan(e):
            table.append((sym, "L", e))
    for sym, e in _M_LINES.items():
        if not np.isnan(e):
            table.append((sym, "M", e))
    return table


_LINE_TABLE: list[tuple[str, str, float]] = _build_line_table()


def assign_elements(
    peak_energies_kev: np.ndarray,
    tolerance_kev: float = 0.15,
) -> list[PeakAssignment]:
    """Match detected EDS peak energies to candidate element lines (D10).

    For each peak, all known K/L/M lines within tolerance_kev are returned,
    sorted by absolute delta (closest first). The caller decides which
    assignment to accept.

    Parameters
    ----------
    peak_energies_kev : 1-D array of detected peak centres in keV
    tolerance_kev     : match window half-width (default 0.15 keV)

    Returns
    -------
    list[PeakAssignment] — one entry per input peak; candidates may be empty.

    Examples
    --------
    >>> r = assign_elements(np.array([6.404, 8.048, 0.525]))
    >>> r[0].candidates[0].symbol   # Fe Kα
    'Fe'
    >>> r[1].candidates[0].symbol   # Cu Kα
    'Cu'
    >>> r[2].candidates[0].symbol   # O Kα
    'O'
    """
    peaks = np.asarray(peak_energies_kev, dtype=np.float64).ravel()
    result = []
    for pk in peaks:
        cands = []
        for sym, line, e in _LINE_TABLE:
            d = abs(pk - e)
            if d <= tolerance_kev:
                cands.append(ElementAssignment(sym, line, e, round(d, 4)))
        cands.sort(key=lambda c: c.delta_kev)
        result.append(PeakAssignment(float(pk), tuple(cands)))
    return result
