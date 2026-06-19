"""Diffraction: spot detection, kinematic simulation, phase indexing.

Port of fermi-viewer's findDiffractionSpots / simulateDiffraction /
indexDiffraction. Pixel coordinates are MATLAB-style 1-based throughout
this module (golden parity), and the simulate/index centre conventions
differ by 0.5 px INTENTIONALLY (simulate: H/2+0.5; index: floor(H/2)+1)
— calibrated behaviour, do not "fix".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import fftconvolve

from fermiviewer.calc.crystal import PHASES, Phase, electron_wavelength, find_phase, plane_spacings
from fermiviewer.calc.elements import atomic_number

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
) -> SimResult:
    """Kinematic zone-axis pattern (port of simulateDiffraction.m).

    |F|² from the atomic basis (Z as scattering-factor proxy); phases
    without a basis fall back to flat intensity + centering extinctions.
    """
    phase = find_phase(phase_name)
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
    if basis:
        basis_z = np.array([atomic_number(sym) for sym, *_ in basis], dtype=np.float64)
        basis_frac = np.array([[x, y, z] for _, x, y, z in basis])

    rows: list[tuple[int, int, int, float, float]] = []
    rng = range(-max_hkl, max_hkl + 1)
    for h in rng:
        for k in rng:
            for l in rng:  # noqa: E741
                if h == k == l == 0 or abs(h * uvw[0] + k * uvw[1] + l * uvw[2]) > 0.5:
                    continue
                if not basis and _simulate_extinct(h, k, l, phase.centering):
                    continue
                g = h * a_star + k * b_star + l * c_star
                g_mag = float(np.linalg.norm(g))
                if g_mag < np.finfo(float).eps:
                    continue
                if basis:
                    ph = 2 * np.pi * (basis_frac @ [h, k, l])
                    f_hkl = (basis_z * np.exp(1j * ph)).sum()
                    inten = float((f_hkl * np.conj(f_hkl)).real)
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

    db = list(PHASES)
    if phases:
        sel = [p for p in db if p.name in phases]
        db = sel or db

    cands: list[IndexCandidate] = []
    for ph in db:
        refl = plane_spacings(
            ph.a, b=ph.b, c=ph.c, alpha=ph.alpha, beta=ph.beta, gamma=ph.gamma,
            centering=ph.centering, max_hkl=max_hkl, lam=float("nan"),
        )
        m_hkl, m_d, m_ref = [], [], []
        for i in range(n_spots):
            if not valid[i]:
                continue
            frac = np.abs(refl.d - d_meas[i]) / refl.d
            j = int(frac.argmin())
            if frac[j] < tolerance:
                m_hkl.append(refl.hkl[j])
                m_d.append(d_meas[i])
                m_ref.append(refl.d[j])
        n_m = len(m_d)
        hkl_arr = np.array(m_hkl) if m_hkl else np.zeros((0, 3))
        cands.append(IndexCandidate(
            ph.name, ph.formula, n_m / max(n_spots, 1), n_m, n_spots,
            hkl_arr, np.array(m_d), np.array(m_ref),
            _zone_axis(hkl_arr) if n_m >= 2 else (float("nan"),) * 3,
        ))

    def mean_err(c: IndexCandidate) -> float:
        if c.n_matched == 0:
            return np.inf
        return float(np.mean(np.abs(c.matched_d - c.ref_d) / c.ref_d))

    cands.sort(key=lambda c: (-c.score, mean_err(c)))
    return cands[: min(top_n, len(cands))]
