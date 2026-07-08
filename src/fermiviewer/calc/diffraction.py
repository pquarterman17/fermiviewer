"""Diffraction: spot detection, kinematic simulation, phase indexing.

Port of fermi-viewer's findDiffractionSpots / simulateDiffraction /
indexDiffraction. Pixel coordinates are MATLAB-style 1-based throughout
this module (golden parity), and the simulate/index centre conventions
differ by 0.5 px INTENTIONALLY (simulate: H/2+0.5; index: floor(H/2)+1)
— calibrated behaviour, do not "fix".

Ellipse-fit calibration was split out earlier to ``diffraction_calib.py``
(see that module's docstring). Kinematic simulation (``Spot``/``SimResult``/
``simulate``) is likewise split out to ``diffraction_simulate.py`` — was 491
lines here — and re-exported below so existing imports are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import fftconvolve

from fermiviewer.calc.crystal import PHASES, Phase, electron_wavelength, plane_spacings
from fermiviewer.calc.diffraction_simulate import (
    SimResult,
    Spot,
    simulate,
)  # re-export — moved to diffraction_simulate.py to respect the 500-line ceiling

__all__ = [
    "IndexCandidate", "SimResult", "Spot",
    "apply_roi", "d_spacing_to_radius",
    "find_spots", "index_spots", "simulate",
]


# ════════════════════════════════════════════════════════════════════
# ROI helpers
# ════════════════════════════════════════════════════════════════════

def apply_roi(
    img: np.ndarray,
    roi: dict | None,
) -> tuple[np.ndarray, tuple[int, int]]:
    """Crop *img* to an analysis ROI and return (cropped, (row0, col0)).

    roi format (from the frontend):
      {"kind": "rect",   "r0": int, "c0": int, "r1": int, "c1": int}
      {"kind": "circle", "cr": int, "cc": int, "radius": int}

    If roi is None or malformed the full image is returned with offset (0, 0).

    The origin offset is in 0-based pixel coords so callers can map spot
    positions in the cropped image back to the full-image frame.
    """
    if roi is None:
        return img, (0, 0)
    kind = roi.get("kind")
    h, w = img.shape[:2]
    if kind == "rect":
        r0 = max(0, int(roi["r0"]))
        c0 = max(0, int(roi["c0"]))
        r1 = min(h, int(roi["r1"]))
        c1 = min(w, int(roi["c1"]))
        if r1 <= r0 or c1 <= c0:
            return img, (0, 0)
        return img[r0:r1, c0:c1], (r0, c0)
    if kind == "circle":
        cr = int(roi["cr"])
        cc = int(roi["cc"])
        rad = int(roi["radius"])
        r0 = max(0, cr - rad)
        c0 = max(0, cc - rad)
        r1 = min(h, cr + rad + 1)
        c1 = min(w, cc + rad + 1)
        patch = img[r0:r1, c0:c1].copy()
        # zero pixels outside the circle
        rr, cc_ = np.ogrid[r0:r1, c0:c1]
        mask = (rr - cr) ** 2 + (cc_ - cc) ** 2 > rad ** 2
        patch[mask] = 0.0
        return patch, (r0, c0)
    return img, (0, 0)


def d_spacing_to_radius(
    d_ang: float,
    img_size: tuple[int, int],
    pixel_size: float = 1.0,
    camera_length: float = float("nan"),
    acc_voltage: float = 200,
) -> float:
    """Convert a d-spacing (Å) to a ring radius in pixels.

    Two geometry modes (verbatim from drawRingOverlay.m):

    **FFT mode** (``camera_length`` is NaN):
        Each pixel step in the centred FFT = 1 / (W * pixel_size) in
        reciprocal space, so d = W * pixel_size / R  →  R = W * pixel_size / d.
        Units: pixel_size in the same real-space unit as d (Å here).

    **TEM camera mode** (``camera_length`` in mm, ``pixel_size`` in mm/px):
        Bragg's law in the small-angle limit:
            sin θ = λ / (2 d)
            R [px] = L [mm] * tan(2θ) / pixel_size [mm/px]
        where λ is the relativistic electron wavelength at *acc_voltage* kV.

    Returns NaN when sinθ > 1 (d too small for the beam energy) or d ≤ 0.

    Args:
        d_ang:        d-spacing in Ångströms (> 0).
        img_size:     (rows, cols) of the full image in pixels.
        pixel_size:   calibrated pixel size.  FFT mode: Å/px.
                      TEM mode: mm/px.
        camera_length: effective camera length in mm (NaN → FFT mode).
        acc_voltage:  TEM accelerating voltage in kV (TEM mode only).

    Returns:
        Ring radius in pixels (float), or NaN if physically invalid.

    Example:
        >>> # FFT mode: 512×512, pixel 0.195 nm/px (0.0195 nm = 0.195 Å/step)
        >>> d_spacing_to_radius(2.338, (512, 512), pixel_size=0.0195)
        # ~5.4 px
    """
    if d_ang <= 0:
        return float("nan")
    if np.isnan(camera_length):
        # FFT mode: R = W * pixel_size / d
        return float(img_size[1] * pixel_size / d_ang)
    # TEM camera mode (drawRingOverlay.m verbatim):
    #   sin θ = λ / (2 d);  R = L * tan(2 arcsin(sin θ)) / pixel_size
    lam = float(electron_wavelength(acc_voltage))  # Å
    sin_theta = lam / (2.0 * d_ang)
    if sin_theta > 1.0:
        return float("nan")
    r_mm = camera_length * np.tan(2.0 * np.arcsin(sin_theta))  # mm
    return float(r_mm / pixel_size)  # px


# ════════════════════════════════════════════════════════════════════
def find_spots(
    img: np.ndarray,
    min_radius: float = 10,
    threshold: float = 0.05,
    min_separation: float = 8,
    max_spots: int = 50,
    sigma: float = 1.5,
) -> np.ndarray:
    """Bright-spot detection (port of findDiffractionSpots.m).

    Returns [N, 2] (row, col), 1-based, intensity-sorted with greedy
    min-separation suppression; the centre region (< min_radius) is
    excluded (direct beam).
    """
    hw = int(np.ceil(3 * sigma))
    ax = np.arange(-hw, hw + 1)
    xx, yy = np.meshgrid(ax, ax)
    kernel = np.exp(-0.5 * (xx**2 + yy**2) / sigma**2)
    kernel /= kernel.sum()
    smoothed = fftconvolve(np.asarray(img, dtype=np.float64), kernel, mode="same")

    n_rows, n_cols = smoothed.shape
    pad = np.full((n_rows + 2, n_cols + 2), -np.inf)
    pad[1:-1, 1:-1] = smoothed
    is_max = np.ones((n_rows, n_cols), dtype=bool)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            is_max &= smoothed >= pad[1 + dr : n_rows + 1 + dr, 1 + dc : n_cols + 1 + dc]

    global_max = smoothed.max()
    if global_max <= 0:
        return np.zeros((0, 2))
    is_max &= smoothed >= threshold * global_max

    center_row = n_rows // 2 + 1            # 1-based
    center_col = n_cols // 2 + 1
    rows, cols = np.nonzero(is_max)
    rows, cols = rows + 1, cols + 1         # → 1-based
    if rows.size == 0:
        return np.zeros((0, 2))

    r = np.hypot(rows - center_row, cols - center_col)
    keep = r >= min_radius
    rows, cols = rows[keep], cols[keep]
    if rows.size == 0:
        return np.zeros((0, 2))

    intens = smoothed[rows - 1, cols - 1]
    order = np.argsort(-intens, kind="stable")
    rows, cols = rows[order], cols[order]

    accepted = np.zeros(rows.size, dtype=bool)
    suppressed = np.zeros(rows.size, dtype=bool)
    for i in range(rows.size):
        if suppressed[i]:
            continue
        accepted[i] = True
        if accepted.sum() >= max_spots:
            break
        d2 = (rows[i + 1 :] - rows[i]) ** 2 + (cols[i + 1 :] - cols[i]) ** 2
        suppressed[i + 1 :] |= d2 < min_separation**2
    return np.column_stack([rows[accepted], cols[accepted]]).astype(np.float64)


# ════════════════════════════════════════════════════════════════════
# Spot / SimResult / simulate now live in diffraction_simulate.py (re-exported
# above) — kinematic zone-axis pattern simulation, split out to respect the
# 500-line ceiling.
# ════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class IndexCandidate:
    phase_name: str
    formula: str
    score: float
    n_matched: int
    n_spots: int
    matched_hkl: np.ndarray
    matched_d: np.ndarray
    ref_d: np.ndarray
    zone_axis: tuple[float, float, float]
    # index into the input `positions` for each matched spot, so callers can
    # map a match back to its (row, col) for overlay labels / a report (#37)
    matched_idx: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))


def _zone_axis(hkl: np.ndarray) -> tuple[float, float, float]:
    best = (float("nan"),) * 3
    best_norm = np.inf
    rng = range(-3, 4)
    for u in rng:
        for v in rng:
            for w in rng:
                if u == v == w == 0:
                    continue
                if np.all(hkl @ [u, v, w] == 0):
                    n = float(np.linalg.norm([u, v, w]))
                    if n < best_norm:
                        best_norm = n
                        best = (float(u), float(v), float(w))
    return best


def index_spots(
    positions: np.ndarray,
    img_size: tuple[int, int],
    pixel_size: float = 1.0,
    camera_length: float = float("nan"),
    acc_voltage: float = 200,
    tolerance: float = 0.05,
    max_hkl: int = 5,
    phases: list[str] | None = None,
    top_n: int = 5,
    extra_phases: list[Phase] | None = None,
) -> list[IndexCandidate]:
    """Match measured spots to database phases (port of indexDiffraction.m).

    positions are 1-based (row, col). With camera_length (mm) +
    pixel_size (mm/px), d in Å via d = λL/r; candidates score by matched
    fraction, ties broken by mean relative d-error.
    """
    positions = np.asarray(positions, dtype=np.float64)
    n_spots = positions.shape[0]
    center = (img_size[0] // 2 + 1, img_size[1] // 2 + 1)
    r = np.hypot(positions[:, 0] - center[0], positions[:, 1] - center[1])

    if np.isnan(camera_length):
        with np.errstate(divide="ignore"):
            d_meas = (img_size[1] * pixel_size) / r
    else:
        lam = float(electron_wavelength(acc_voltage))
        with np.errstate(divide="ignore"):
            d_meas = (lam * camera_length * 1e7) / (r * pixel_size * 1e7)
    valid = np.isfinite(d_meas) & (r > 0)

    db = list(PHASES) + list(extra_phases or [])  # custom/CIF phases participate
    if phases:
        sel = [p for p in db if p.name in phases]
        db = sel or db

    cands: list[IndexCandidate] = []
    for ph in db:
        refl = plane_spacings(
            ph.a, b=ph.b, c=ph.c, alpha=ph.alpha, beta=ph.beta, gamma=ph.gamma,
            centering=ph.centering, max_hkl=max_hkl, lam=float("nan"),
        )
        m_hkl, m_d, m_ref, m_idx = [], [], [], []
        for i in range(n_spots):
            if not valid[i]:
                continue
            frac = np.abs(refl.d - d_meas[i]) / refl.d
            j = int(frac.argmin())
            if frac[j] < tolerance:
                m_hkl.append(refl.hkl[j])
                m_d.append(d_meas[i])
                m_ref.append(refl.d[j])
                m_idx.append(i)  # which input spot this match came from
        n_m = len(m_d)
        hkl_arr = np.array(m_hkl) if m_hkl else np.zeros((0, 3))
        cands.append(IndexCandidate(
            ph.name, ph.formula, n_m / max(n_spots, 1), n_m, n_spots,
            hkl_arr, np.array(m_d), np.array(m_ref),
            _zone_axis(hkl_arr) if n_m >= 2 else (float("nan"),) * 3,
            np.array(m_idx, dtype=int),
        ))

    def mean_err(c: IndexCandidate) -> float:
        if c.n_matched == 0:
            return np.inf
        return float(np.mean(np.abs(c.matched_d - c.ref_d) / c.ref_d))

    cands.sort(key=lambda c: (-c.score, mean_err(c)))
    return cands[: min(top_n, len(cands))]
