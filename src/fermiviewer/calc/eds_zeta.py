"""EDS ζ-factor (Watanabe-Williams) quantification (PLAN_SPECTRAL_QUANT #7).

Cliff-Lorimer works on intensity *ratios*, so it yields composition but
never thickness and cannot correct its own absorption. The ζ-factor
method instead relates each element's net intensity *absolutely* to
mass-thickness via the electron dose::

    C_i · ρt = ζ_i · I_i / D_e

Summing over elements (ΣC_i = 1) gives the mass-thickness for free,

    ρt = Σ_j ζ_j · I_j / D_e,          C_i = ζ_i I_i / Σ_j ζ_j I_j,

and the known ρt then feeds a self-consistent thin-film absorption
correction (iterated): the measured intensity of element i is restored
by A_i = χ_i ρt / (1 − exp(−χ_i ρt)) with χ_i = cosec(α)·Σ_j (μ/ρ)_i^j w_j.

Units: ζ carries kg·m⁻² (per electron per photon) — Watanabe's SI
convention — so ρt comes out in kg/m². The k↔ζ bridge k_ij = ζ_i/ζ_j
lets one absolute ζ (e.g. for Si) scale the built-in 200 kV k-factor
table into estimated ζ values (:func:`zeta_from_k_factors`); rigorous
work supplies per-element ζ from standards.

Pure library (numpy only); no fastapi/pydantic/route imports.

References
----------
Watanabe & Williams, *J. Microsc.* **221** (2006) 89-109 (the ζ-factor
method); Goldstein et al., *SEM and X-ray Microanalysis*, 4th ed.
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eds import _resolve_k, mass_absorption_coeff
from fermiviewer.calc.elements import ELEMENTS, atomic_mass

__all__ = [
    "ELECTRON_CHARGE_C",
    "ZetaResult",
    "detector_solid_angle_sr",
    "dose_electrons",
    "zeta_from_k_factors",
    "zeta_quantify",
]

ELECTRON_CHARGE_C = 1.602176634e-19   # exact (2019 SI)

# mass-absorption coefficients come from eds.mass_absorption_coeff in
# cm²/g; χ·ρt must be dimensionless with ρt in kg/m², so convert.
_CM2_PER_G_TO_M2_PER_KG = 0.1


def dose_electrons(probe_current_na: float, live_time_s: float) -> float:
    """Total electron dose D_e = I·τ/e for a probe current and live time.

    Parameters
    ----------
    probe_current_na : beam current in nA.
    live_time_s : acquisition live time in seconds.

    Examples
    --------
    >>> round(dose_electrons(1.0, 1.0) / 1e9, 4)   # 1 nA·s
    6.2415
    """
    if probe_current_na <= 0 or live_time_s <= 0:
        raise ValueError("probe current and live time must be positive")
    return probe_current_na * 1e-9 * live_time_s / ELECTRON_CHARGE_C


def detector_solid_angle_sr(active_area_mm2: float, distance_mm: float) -> float:
    """Detector solid angle Ω ≈ A/d² (sr), small-angle approximation.

    ζ factors are detector-specific (they absorb Ω/4π and the detector
    efficiency); when re-using ζ values measured at a reference geometry,
    scale them by Ω_ref/Ω — ζ ∝ 1/Ω.
    """
    if active_area_mm2 <= 0 or distance_mm <= 0:
        raise ValueError("area and distance must be positive")
    return active_area_mm2 / distance_mm**2


def zeta_from_k_factors(
    elements: Sequence[str],
    zeta_si: float,
    k_factors: np.ndarray | None = None,
) -> np.ndarray:
    """Estimate per-element ζ from one absolute ζ_Si + relative k-factors.

    Both systems relate composition to intensity, so k_ij = ζ_i/ζ_j
    exactly; with the built-in 200 kV table (k relative to Si) this is
    ζ_i = k_i · ζ_Si. One measured standard fixes the absolute scale.

    Parameters
    ----------
    elements : element symbols.
    zeta_si : absolute ζ for Si-Kα on THIS detector/voltage (kg/m²).
    k_factors : optional explicit k values (relative to Si) overriding
        the built-in 200 kV table.
    """
    if zeta_si <= 0:
        raise ValueError("zeta_si must be positive")
    k = _resolve_k(list(elements), k_factors)
    return k * zeta_si


@dataclass(frozen=True)
class ZetaResult:
    """Outcome of :func:`zeta_quantify`. Maps are NaN off-mask.

    ``mass_thickness_maps`` is ρt in kg/m² (multiply by 1e5 for µg/cm²);
    ``thickness_map_nm`` needs a supplied density and is None without one.
    ``absorption_factors`` are the converged field-mean A_i (≥ 1; all 1.0
    when absorption correction is off).
    """

    atomic_pct_maps: list[np.ndarray]
    weight_pct_maps: list[np.ndarray]
    elements: list[str]
    zeta_factors: np.ndarray
    mask: np.ndarray
    mean_atomic_pct: np.ndarray
    mean_weight_pct: np.ndarray
    mass_thickness_map: np.ndarray          # kg/m²
    mean_mass_thickness: float              # kg/m²
    thickness_map_nm: np.ndarray | None
    mean_thickness_nm: float                # NaN without a density
    absorption_factors: np.ndarray
    dose: float


def _mac_matrix(elements: Sequence[str]) -> np.ndarray:
    """(emitter, absorber) MAC matrix in m²/kg; NaN → a bland 10 m²/kg."""
    n = len(elements)
    mac = np.empty((n, n))
    for i, em in enumerate(elements):
        for j, ab in enumerate(elements):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mac[i, j] = mass_absorption_coeff(em, ab)
    mac[~np.isfinite(mac)] = 100.0
    return mac * _CM2_PER_G_TO_M2_PER_KG


def _iterate(
    cube: np.ndarray,
    zeta: np.ndarray,
    dose: float,
    mask: np.ndarray,
    *,
    mac: np.ndarray | None,
    csc: float,
    n_iter: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fixed-point loop: (w, ρt) → absorption A → restored intensities.

    Returns per-pixel weight fractions, ρt (kg/m²), and the field-mean
    absorption factors (ones when ``mac is None`` = correction off).
    """
    n = cube.shape[2]
    a_f = np.ones(n)
    gen = cube.copy()                       # generated-intensity estimate
    rho_t = np.zeros(mask.shape)
    w = np.zeros_like(gen)
    for _ in range(n_iter):
        q = gen * zeta                      # ζ_i·I_i per pixel
        q_sum = q.sum(axis=2)
        rho_t = q_sum / dose                # kg/m²
        safe = np.where(q_sum > 0, q_sum, 1.0)
        w = q / safe[:, :, None]
        if mac is None:
            break
        # χ_i(px) = csc·Σ_j MAC[i,j]·w_j(px);  x = χ·ρt;  A = x/(1−e⁻ˣ)
        chi = np.einsum("ij,yxj->yxi", mac, w) * csc
        x = chi * rho_t[:, :, None]
        a_map = np.ones_like(x)
        big = np.abs(x) >= 1e-6
        a_map[big] = x[big] / (1.0 - np.exp(-x[big]))
        gen = cube * a_map
        a_flat = a_map.reshape(-1, n)[mask.ravel()]
        a_f = a_flat.mean(axis=0) if a_flat.size else np.ones(n)
    return w, rho_t, a_f


def zeta_quantify(
    intensity_maps: list[np.ndarray],
    elements: list[str],
    zeta_factors: Sequence[float] | np.ndarray,
    dose: float,
    *,
    take_off_angle_deg: float = 20.0,
    absorption: bool = True,
    density_g_cm3: float | None = None,
    iterations: int = 5,
    mask_threshold: float = 0.0,
) -> ZetaResult:
    """ζ-factor quantification: composition + mass-thickness per pixel.

    Parameters
    ----------
    intensity_maps : per-element net-intensity maps (equal shapes; use
        1×1 arrays for a single summed spectrum).
    elements : symbols aligned with ``intensity_maps``.
    zeta_factors : per-element ζ in kg/m² (see :func:`zeta_from_k_factors`).
    dose : total electron dose D_e (see :func:`dose_electrons`).
    take_off_angle_deg : X-ray take-off angle α ∈ (0, 90).
    absorption : iterate the self-consistent thin-film absorption
        correction A_i = χ_i ρt/(1−exp(−χ_i ρt)).
    density_g_cm3 : optional density to convert ρt → thickness (nm).
    iterations : absorption-loop count (composition and ρt converge fast).
    mask_threshold : pixels with Σ intensity ≤ this are NaN.

    Examples
    --------
    Two elements, no absorption — exact hand check
    (Σζ·I = 500·2000 + 1000·1000 = 2·10⁶ → w = (0.5, 0.5), ρt = 2·10⁻⁴):

    >>> r = zeta_quantify(
    ...     [np.array([[2000.0]]), np.array([[1000.0]])], ["Fe", "O"],
    ...     [500.0, 1000.0], dose=1e10, absorption=False)
    >>> [round(float(w), 3) for w in r.mean_weight_pct]
    [50.0, 50.0]
    >>> round(r.mean_mass_thickness, 8)
    0.0002
    """
    n = len(elements)
    if len(intensity_maps) != n:
        raise ValueError("intensity_maps and elements must have equal length")
    zeta = np.asarray(zeta_factors, dtype=np.float64)
    if zeta.size != n:
        raise ValueError("zeta_factors must match elements length")
    if not np.all(zeta > 0):
        raise ValueError("zeta_factors must be positive")
    if dose <= 0:
        raise ValueError("dose must be positive")
    if not 0 < take_off_angle_deg < 90:
        raise ValueError("take_off_angle_deg must be in (0, 90)")

    cube = np.stack([np.asarray(m, dtype=np.float64) for m in intensity_maps], axis=2)
    cube = np.clip(cube, 0.0, None)
    mask = cube.sum(axis=2) > mask_threshold

    w, rho_t, a_f = _iterate(
        cube, zeta, dose, mask,
        mac=_mac_matrix(elements) if absorption else None,
        csc=1.0 / np.sin(np.deg2rad(take_off_angle_deg)),
        n_iter=max(1, int(round(iterations))) if absorption else 1,
    )

    masses = np.array([atomic_mass(s) if s in ELEMENTS else 1.0 for s in elements])
    w_over_m = w / masses
    s = w_over_m.sum(axis=2)
    s_safe = np.where(s > 0, s, 1.0)
    at = w_over_m / s_safe[:, :, None]

    w = np.where(mask[:, :, None], w, np.nan)
    at = np.where(mask[:, :, None], at, np.nan)
    rho_t = np.where(mask, rho_t, np.nan)

    valid = mask.ravel()
    at_maps = [at[:, :, i] * 100 for i in range(n)]
    w_maps = [w[:, :, i] * 100 for i in range(n)]
    if valid.any():
        mean_at = np.array([np.nanmean(m.ravel()[valid]) for m in at_maps])
        mean_wt = np.array([np.nanmean(m.ravel()[valid]) for m in w_maps])
    else:
        mean_at = np.full(n, np.nan)
        mean_wt = np.full(n, np.nan)
    mean_rt = float(np.nanmean(rho_t.ravel()[valid])) if valid.any() else float("nan")

    t_map: np.ndarray | None = None
    mean_t = float("nan")
    if density_g_cm3 is not None:
        if density_g_cm3 <= 0:
            raise ValueError("density_g_cm3 must be positive")
        rho_si = density_g_cm3 * 1000.0     # kg/m³
        t_map = rho_t / rho_si * 1e9        # m → nm
        mean_t = mean_rt / rho_si * 1e9

    return ZetaResult(
        atomic_pct_maps=at_maps,
        weight_pct_maps=w_maps,
        elements=list(elements),
        zeta_factors=zeta,
        mask=mask,
        mean_atomic_pct=mean_at,
        mean_weight_pct=mean_wt,
        mass_thickness_map=rho_t,
        mean_mass_thickness=mean_rt,
        thickness_map_nm=t_map,
        mean_thickness_nm=mean_t,
        absorption_factors=a_f,
        dose=float(dose),
    )
