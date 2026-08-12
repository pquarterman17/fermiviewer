"""ZAF's Z and A factor math, extracted from `calc.eds.zaf_correction` so it
has a name and an import path (SPECTRAL_WORKSPACE_PLAN #19).

Before this module existed the mac-matrix build and the Z/A formulas lived
inline in `zaf_correction`'s iteration loop — fine for the route, but it meant
nothing outside that function could evaluate absorption at a KNOWN
composition and thickness without retyping the formulas. The synthetic-data
generator needs exactly that (planting a thickness-dependent ZAF factor into
`eds-thickness` so the cube is a real absorption oracle), and the fixtures
rule is import-don't-transcribe: a second copy of `1 + (meanZ/z − 1)(1−e^{−t/200})`
in `tools/` would drift from this one silently. `zaf_correction` now calls
this module; the arithmetic did not move, only its address.
"""

from __future__ import annotations

import warnings

import numpy as np

from fermiviewer.calc.elements import ELEMENTS, bulk_density

__all__ = ["mac_matrix", "zaf_factors"]


def mac_matrix(elements: list[str]) -> np.ndarray:
    """Emitter x absorber mass-absorption-coefficient matrix (cm^2/g).

    A missing MAC (unknown Kalpha or element data for either side of the
    pair) is filled with 100.0 rather than left NaN — `zaf_factors` treats an
    unmodelled pair as moderate self-absorption, not a reason to abort the
    correction for every OTHER element in the same cube.
    """
    # Imported here, not at module level: `eds.zaf_correction` imports THIS
    # module, so a top-level `from fermiviewer.calc.eds import
    # mass_absorption_coeff` would be circular. By call time (never at import
    # time) `calc.eds` is always fully loaded.
    from fermiviewer.calc.eds import mass_absorption_coeff

    n = len(elements)
    mac = np.empty((n, n))
    for i, em in enumerate(elements):
        for j, ab in enumerate(elements):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mac[i, j] = mass_absorption_coeff(em, ab)
    mac[~np.isfinite(mac)] = 100.0
    return mac


def zaf_factors(
    elements: list[str],
    w_mean: np.ndarray,
    thickness_nm: float,
    take_off_angle_deg: float,
    density: float = float("nan"),
    *,
    mac: np.ndarray | None = None,
    z_numbers: np.ndarray | None = None,
    densities: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Z and A factors at one mean weight-fraction estimate `w_mean`.

    Z: mean-Z scaling damped by 1−exp(−t/200); A: χ/(1−e^−χ) absorption with
    χ = (MAC·w̄)·ρ·t·csc(takeoff). `zaf_correction` calls this once per
    iteration with the current `w_mean`; the generator calls it once at the
    KNOWN true composition to plant absorption into a synthetic cube. Pass
    `mac`/`z_numbers`/`densities` to reuse work across repeated calls on the
    same element list — each is rebuilt from `elements` when omitted.
    """
    if z_numbers is None:
        z_numbers = np.array(
            [float(ELEMENTS[s][0]) if s in ELEMENTS else 1.0 for s in elements]
        )
    if densities is None:
        densities = np.array(
            [bulk_density(s) if s in ELEMENTS and bulk_density(s) else 5.0
             for s in elements],
            dtype=np.float64,
        )
        densities[~np.isfinite(densities) | (densities <= 0)] = 5.0
    if mac is None:
        mac = mac_matrix(elements)

    csc = 1.0 / np.sin(np.deg2rad(take_off_angle_deg))
    t_cm = thickness_nm * 1e-7
    n = len(elements)

    mean_z = float((w_mean * z_numbers).sum())
    z_scale = 1 - np.exp(-thickness_nm / 200)
    z_f = np.where(z_numbers > 0, 1 + (mean_z / z_numbers - 1) * z_scale, 1.0)

    rho = density if np.isfinite(density) and density > 0 else float(
        (w_mean * densities).sum()
    )
    if not np.isfinite(rho) or rho <= 0:
        rho = 5.0

    chi = (mac @ w_mean) * rho * t_cm * csc
    a_f = np.ones(n)
    big = np.abs(chi) >= 1e-6
    a_f[big] = chi[big] / (1 - np.exp(-chi[big]))

    return z_f, a_f
