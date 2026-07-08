"""Kinematic zone-axis diffraction simulation (split from diffraction.py).

Port of fermi-viewer's simulateDiffraction.m. Pixel coordinates are
MATLAB-style 1-based, and the beam centre convention (``H/2+0.5``)
INTENTIONALLY differs from ``index_spots``'s ``floor(H/2)+1`` —
calibrated behaviour, do not "fix" (see diffraction.py's module
docstring for the full note).

Kept out of ``diffraction.py`` (was 491 lines) to respect the 500-line
god-module ceiling — following the precedent set by the earlier
calibration split (``diffraction_calib.py``). Re-exported from
diffraction.py so existing imports are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.crystal import Phase, electron_wavelength, find_phase
from fermiviewer.calc.scattering_factors import (
    build_basis_model,
    reflection_intensity,
)

__all__ = ["SimResult", "Spot", "simulate"]


@dataclass(frozen=True)
class Spot:
    hkl: tuple[int, int, int]
    d_spacing: float          # Å (NaN for the direct beam)
    intensity: float          # normalised |F|²
    pixel_row: float          # 1-based
    pixel_col: float


@dataclass(frozen=True)
class SimResult:
    spots: tuple[Spot, ...]   # spots[0] is the direct beam
    image: np.ndarray
    phase_name: str
    formula: str
    zone_axis: tuple[int, int, int]
    lam: float


def _simulate_extinct(h: int, k: int, l: int, centering: str) -> bool:  # noqa: E741
    match centering.upper():
        case "F":
            return not ((h + k) % 2 == 0 and (h + l) % 2 == 0 and (k + l) % 2 == 0)
        case "I":
            return (h + k + l) % 2 != 0
        case "C":
            return (h + k) % 2 != 0
        case "A":
            return (k + l) % 2 != 0
        case "B":
            return (h + l) % 2 != 0
        case "R":
            return (-h + k + l) % 3 != 0
        case _:
            return False


def _lattice_vectors(p: Phase) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    al, be, ga = np.deg2rad([p.alpha, p.beta, p.gamma])
    a_vec = p.a * np.array([1.0, 0.0, 0.0])
    b_vec = p.b * np.array([np.cos(ga), np.sin(ga), 0.0])
    cx = p.c * np.cos(be)
    cy = p.c * (np.cos(al) - np.cos(be) * np.cos(ga)) / np.sin(ga)
    cz = np.sqrt(max(p.c**2 - cx**2 - cy**2, 0.0))
    c_vec = np.array([cx, cy, cz])
    vol = float(np.dot(a_vec, np.cross(b_vec, c_vec)))
    return (np.cross(b_vec, c_vec) / vol,
            np.cross(c_vec, a_vec) / vol,
            np.cross(a_vec, b_vec) / vol)


def _add_blob(img: np.ndarray, row_c: float, col_c: float,
              amp: float, sigma: float, k_half: int) -> None:
    h, w = img.shape
    r0, c0 = round(row_c), round(col_c)
    r_min, r_max = max(1, r0 - k_half), min(h, r0 + k_half)
    c_min, c_max = max(1, c0 - k_half), min(w, c0 + k_half)
    if r_min > r_max or c_min > c_max:
        return
    rr = np.arange(r_min, r_max + 1)[:, None]
    cc = np.arange(c_min, c_max + 1)[None, :]
    img[r_min - 1 : r_max, c_min - 1 : c_max] += amp * np.exp(
        -((rr - row_c) ** 2 + (cc - col_c) ** 2) / (2 * sigma**2)
    )


def simulate(
    phase_name: str,
    zone_axis: tuple[int, int, int] = (0, 0, 1),
    acc_voltage: float = 200,
    camera_length: float = 200,
    pixel_size: float = 0.05,
    image_size: tuple[int, int] = (512, 512),
    max_hkl: int = 5,
    min_intensity: float = 0.01,
    spot_sigma: float = 3,
    scattering_model: str = "fe",
    debye_waller_B: float | None = None,  # noqa: N803 — B is the physics symbol
    phase: Phase | None = None,
) -> SimResult:
    """Kinematic zone-axis pattern (port of simulateDiffraction.m).

    |F|² is summed over the atomic basis. The per-atom weight is chosen
    by *scattering_model*:

    * ``"fe"`` (default): real electron scattering factors f_e(s) from
      the Doyle--Turner parameterisation (Acta Cryst. A24 (1968) 390),
      evaluated at ``s = 1 / (2 d) = |g| / 2`` per reflection. This is
      the physically correct weighting — high-angle reflections are
      down-weighted by the falling f_e(s), and chemically distinct atoms
      (e.g. Ga vs As) get different amplitudes. Elements absent from the
      Doyle--Turner table raise a KeyError.
    * ``"z"``: legacy atomic-number proxy (weight = Z, s-independent).
      Pinned for golden parity; the frozen MATLAB simulate golden was
      captured with this model.

    Phases without an atomic basis fall back to flat intensity +
    centering extinctions (unaffected by *scattering_model*).

    Thermal damping (optional): when *debye_waller_B* is not None each
    atomic weight is multiplied by ``exp(-B s^2)``. Pass a float B (A^2)
    to use one isotropic B for every atom, or the sentinel ``-1.0`` to
    use per-element room-temperature defaults
    (``default_debye_waller_B``). The default ``None`` leaves behaviour
    unchanged (no damping).

    Args:
        scattering_model: ``"fe"`` (Doyle--Turner, default) or ``"z"``
            (atomic-number proxy).
        debye_waller_B: isotropic B in A^2, or ``-1.0`` for per-element
            defaults, or ``None`` (default) to disable thermal damping.
    """
    # an explicit Phase (e.g. a custom/CIF phase from the registry) wins;
    # otherwise resolve the name against the built-in database
    phase = phase if phase is not None else find_phase(phase_name)
    lam = float(electron_wavelength(acc_voltage))
    a_star, b_star, c_star = _lattice_vectors(phase)

    uvw = np.asarray(zone_axis, dtype=np.float64)
    ref = np.array([1.0, 0, 0]) if (
        abs(uvw[0]) <= abs(uvw[1]) and abs(uvw[0]) <= abs(uvw[2])
    ) else np.array([0.0, 1, 0])
    e1 = np.cross(uvw, ref)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(uvw, e1)
    e2 /= np.linalg.norm(e2)

    basis = phase.basis
    bm = build_basis_model(basis, debye_waller_B) if basis else None

    rows: list[tuple[int, int, int, float, float]] = []
    rng = range(-max_hkl, max_hkl + 1)
    for h in rng:
        for k in rng:
            for l in rng:  # noqa: E741
                if h == k == l == 0 or abs(h * uvw[0] + k * uvw[1] + l * uvw[2]) > 0.5:
                    continue
                if bm is None and _simulate_extinct(h, k, l, phase.centering):
                    continue
                g = h * a_star + k * b_star + l * c_star
                g_mag = float(np.linalg.norm(g))
                if g_mag < np.finfo(float).eps:
                    continue
                if bm is not None:
                    # s = sinθ/λ = |g|/2 = 1/(2d)
                    inten = reflection_intensity(bm, (h, k, l), g_mag / 2.0,
                                                 scattering_model)
                else:
                    inten = 1.0
                rows.append((h, k, l, 1.0 / g_mag, inten))

    height, width = image_size
    center_row = height / 2 + 0.5           # NOTE: differs from index — intentional
    center_col = width / 2 + 0.5
    img = np.zeros((height, width))
    spots = [Spot((0, 0, 0), float("nan"), 1.0, center_row, center_col)]

    if rows:
        arr = np.array(rows)
        intens_arr = arr[:, 4]
        peak = float(intens_arr.max())
        inten_norm = intens_arr / peak if peak > 0 else intens_arr
        keep = inten_norm >= min_intensity
        scale = lam * camera_length / pixel_size
        k_half = int(np.ceil(4 * spot_sigma))
        for (h, k, l), d, w_i in zip(  # noqa: E741
            arr[keep, :3].astype(int), arr[keep, 3], inten_norm[keep], strict=True
        ):
            g = h * a_star + k * b_star + l * c_star
            col = center_col + float(np.dot(g, e1)) * scale
            row = center_row + float(np.dot(g, e2)) * scale
            spots.append(Spot((int(h), int(k), int(l)), float(d), float(w_i), row, col))
            _add_blob(img, row, col, float(w_i), spot_sigma, k_half)

    _add_blob(img, center_row, center_col, 1.0, spot_sigma, int(np.ceil(4 * spot_sigma)))
    np.minimum(img, 1.0, out=img)

    za = (int(zone_axis[0]), int(zone_axis[1]), int(zone_axis[2]))
    return SimResult(tuple(spots), img, phase.name, phase.formula, za, lam)
