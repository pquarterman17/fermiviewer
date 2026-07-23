"""EDS hypercube map helpers: element maps, pixel/ROI spectra.

Port of elementMap.m / pixelSpectrum.m / extractElementMaps.m.
Self-consistency oracle: pixel_spectrum(cube, all-True mask) equals the
cube column-sum (the BCF sum-spectrum invariant).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eds import line_energy

__all__ = [
    "composition_profile",
    "virtual_dark_field","ElementMapEntry", "element_map", "extract_element_maps", "pixel_spectrum"]


def _side_windows(
    energy: np.ndarray, e_lo: float, e_hi: float, bg_width: float, bg_gap: float
) -> tuple[np.ndarray, np.ndarray]:
    """The two flanking background windows shared by the linear and
    bremsstrahlung background estimators."""
    pw = e_hi - e_lo
    bw = pw if (np.isnan(bg_width) or bg_width <= 0) else bg_width
    gap = max(bg_gap, 0.0)
    lo = (energy >= e_lo - gap - bw) & (energy < e_lo - gap)
    hi = (energy > e_hi + gap) & (energy <= e_hi + gap + bw)
    return lo, hi


def _kramers_bg_map(
    cube_d: np.ndarray,
    energy: np.ndarray,
    peak: np.ndarray,
    peak_sum: np.ndarray,
    e_lo: float,
    e_hi: float,
    e0_kev: float,
    bg_width: float,
    bg_gap: float,
) -> np.ndarray:
    """Per-pixel net map under a Kramers bremsstrahlung continuum.

    The continuum *shape* is fixed pure Kramers (E0−E)/E (zero above the
    Duane–Hunt cutoff e0_kev); only its per-pixel amplitude is solved, as
    the closed-form least-squares scale of that shape to the flanking
    background channels. Vectorised over all pixels — an O(pixels) linear
    solve, never a per-pixel curve fit — then the continuum integral over
    the peak window is subtracted from the window sum.
    """
    if not np.isfinite(e0_kev):
        raise ValueError("bg='bremsstrahlung' requires a finite e0_kev (beam energy, keV)")
    if e0_kev <= e_hi:
        raise ValueError("e0_kev (beam energy) must exceed the peak window upper edge")
    lo, hi = _side_windows(energy, e_lo, e_hi, bg_width, bg_gap)
    side = lo | hi
    if not side.any():
        return peak_sum
    c = np.where(
        energy < e0_kev,
        np.maximum(e0_kev - energy, 0.0) / np.maximum(energy, 1e-9),
        0.0,
    )
    c_side = c[side]
    denom = float(c_side @ c_side)
    if denom <= 0:
        return peak_sum
    amp = (cube_d[:, :, side] * c_side).sum(axis=2) / denom   # (h, w)
    out = peak_sum - amp * float(c[peak].sum())
    return np.asarray(np.maximum(out, 0.0))


def element_map(
    cube: np.ndarray,
    energy: np.ndarray,
    e_lo: float,
    e_hi: float,
    bg: str = "none",
    bg_width: float = float("nan"),
    bg_gap: float = 0.0,
    e0_kev: float = float("nan"),
) -> np.ndarray:
    """Energy-window integration map (port of elementMap.m).

    ``bg`` selects the background model subtracted from the window sum:
    ``"none"`` (raw sum), ``"linear"`` (two-sided linear from the flanking
    windows), or ``"bremsstrahlung"`` (physical Kramers continuum; needs
    ``e0_kev``, the beam energy / Duane–Hunt cutoff). Default stays
    ``"none"``; goldens are unaffected.
    """
    if e_hi < e_lo:
        e_lo, e_hi = e_hi, e_lo
    cube = np.asarray(cube)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    h, w, c = cube.shape
    if energy.size != c:
        raise ValueError("energy length must equal cube channel count")

    peak = (energy >= e_lo) & (energy <= e_hi)
    if not peak.any():
        return np.zeros((h, w))
    # Sum only the channels each window needs, accumulating in float64.
    # Converting the whole cube to float64 up front (the previous approach)
    # allocated and copied the entire multi-GB cube on every element-map call;
    # a narrow window touches a fraction of a percent of it. Numerically
    # identical — float64 accumulation over the same channels.
    def window_sum(mask: np.ndarray) -> np.ndarray:
        return np.asarray(cube[:, :, mask].sum(axis=2, dtype=np.float64))

    peak_sum: np.ndarray = window_sum(peak)

    bg_l = bg.lower()
    if bg_l == "bremsstrahlung":
        # the Kramers continuum fit reads many channels — materialize here only
        cube_d = np.asarray(cube, dtype=np.float64)
        return _kramers_bg_map(
            cube_d, energy, peak, peak_sum, e_lo, e_hi, e0_kev, bg_width, bg_gap
        )
    if bg_l != "linear":
        return peak_sum

    lo, hi = _side_windows(energy, e_lo, e_hi, bg_width, bg_gap)
    n_peak = int(peak.sum())

    if lo.any() and hi.any():
        lo_rate = window_sum(lo) / lo.sum()
        hi_rate = window_sum(hi) / hi.sum()
        out = peak_sum - 0.5 * (lo_rate + hi_rate) * n_peak
    elif lo.any():
        out = peak_sum - window_sum(lo) / lo.sum() * n_peak
    elif hi.any():
        out = peak_sum - window_sum(hi) / hi.sum() * n_peak
    else:
        out = peak_sum
    return np.asarray(np.maximum(out, 0.0))


def pixel_spectrum(
    cube: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray | None = None,
) -> np.ndarray:
    """Pixel-list or boolean-mask summed spectrum (port of pixelSpectrum.m).

    rows may be a [H, W] boolean mask (cols ignored), or 1-based row
    indices paired with cols.
    """
    cube = np.asarray(cube)
    h, w, c = cube.shape
    flat = np.asarray(cube, dtype=np.float64).reshape(h * w, c)

    rows = np.asarray(rows)
    if rows.dtype == bool:
        if rows.shape != (h, w):
            raise ValueError(f"mask must be [{h} x {w}]")
        out: np.ndarray = flat[rows.ravel()].sum(axis=0)
        return out

    if cols is None:
        raise ValueError("cols required when rows is an index list")
    r = np.round(np.asarray(rows, dtype=np.float64)).astype(int).ravel()
    cc = np.round(np.asarray(cols, dtype=np.float64)).astype(int).ravel()
    if r.size != cc.size:
        raise ValueError("rows and cols must have equal length")
    keep = (r >= 1) & (r <= h) & (cc >= 1) & (cc <= w)
    r, cc = r[keep], cc[keep]
    if r.size == 0:
        return np.zeros(c)
    summed: np.ndarray = flat[(r - 1) * w + (cc - 1)].sum(axis=0)
    return summed


@dataclass(frozen=True)
class ElementMapEntry:
    symbol: str
    line: str
    energy_kev: float
    window: tuple[float, float]
    map: np.ndarray
    total: float


def extract_element_maps(
    cube: np.ndarray,
    energy: np.ndarray,
    elements: list[str],
    half_window: float = 0.085,
    bg: str = "linear",
    beam_kv: float = float("inf"),
    e0_kev: float = float("nan"),
) -> list[ElementMapEntry]:
    """Per-element maps at each element's principal line (port of
    extractElementMaps.m). Unknown / out-of-range lines warn and skip.

    ``bg="bremsstrahlung"`` requires ``e0_kev`` (beam energy, keV)."""
    energy = np.asarray(energy, dtype=np.float64).ravel()
    e_min, e_max = float(energy.min()), float(energy.max())
    out: list[ElementMapEntry] = []
    for sym in elements:
        if not sym:
            continue
        e, line = line_energy(sym, beam_kv=beam_kv)
        if np.isnan(e):
            warnings.warn(f"no known line for '{sym}' — skipped", stacklevel=2)
            continue
        if not e_min <= e <= e_max:
            warnings.warn(
                f"{sym} {line}α line ({e:.3f} keV) outside the energy axis — skipped",
                stacklevel=2,
            )
            continue
        m = element_map(cube, energy, e - half_window, e + half_window,
                        bg=bg, e0_kev=e0_kev)
        out.append(ElementMapEntry(sym, line, e, (e - half_window, e + half_window),
                                   m, float(m.sum())))
    return out


def virtual_dark_field(
    img: np.ndarray,
    mask_center: tuple[float, float],
    mask_radius: float = 10.0,
    mask_shape: str = "circle",
    inner_radius: float = 0.0,
) -> np.ndarray:
    """Virtual dark-field image via FFT aperture masking — ported.

    mask_center is (row, col), 1-based, on the fftshifted FFT.
    """
    if mask_shape not in ("circle", "annulus"):
        raise ValueError("mask_shape must be 'circle' or 'annulus'")
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape
    f = np.fft.fftshift(np.fft.fft2(d))

    rr = np.arange(1, h + 1, dtype=np.float64)[:, None]
    cc = np.arange(1, w + 1, dtype=np.float64)[None, :]
    dist = np.hypot(rr - mask_center[0], cc - mask_center[1])
    if mask_shape == "circle":
        mask = dist <= mask_radius
    else:
        mask = (dist >= inner_radius) & (dist <= mask_radius)

    out: np.ndarray = np.abs(np.fft.ifft2(np.fft.ifftshift(f * mask)))
    return out


def composition_profile(
    atomic_pct_maps: list[np.ndarray],
    elements: list[str],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    n_points: int = 200,
    pixel_size: float = 1.0,
    width: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Width-averaged line profile through element at% maps — ported.

    Coordinates are 1-based (x=col, y=row) like the MATLAB interp2 call.
    Returns (distance, atomic_pct[M, n_elements]).
    """
    from scipy.ndimage import map_coordinates

    if len(atomic_pct_maps) != len(elements):
        raise ValueError("maps and elements must have the same length")
    maps = [np.asarray(m, dtype=np.float64) for m in atomic_pct_maps]
    h, w = maps[0].shape
    for m in maps[1:]:
        if m.shape != (h, w):
            raise ValueError("all maps must be the same size")

    m_pts = int(n_points)
    xi = np.linspace(x1, x2, m_pts)
    yi = np.linspace(y1, y2, m_pts)
    dx = x2 - x1
    dy = y2 - y1
    line_len = float(np.hypot(dx, dy))
    if line_len == 0:
        return np.zeros(m_pts), np.zeros((m_pts, len(maps)))

    perp_x = -dy / line_len
    perp_y = dx / line_len
    n_off = max(1, round(width))
    offsets = (
        np.array([0.0])
        if n_off == 1
        else np.linspace(-(n_off - 1) / 2, (n_off - 1) / 2, n_off)
    )

    out = np.zeros((m_pts, len(maps)))
    for i, mp in enumerate(maps):
        acc = np.zeros(m_pts)
        for off in offsets:
            xq = np.clip(xi + off * perp_x, 1, w)
            yq = np.clip(yi + off * perp_y, 1, h)
            # 1-based coords -> 0-based for map_coordinates (bilinear)
            acc += map_coordinates(mp, [yq - 1, xq - 1], order=1)
        out[:, i] = acc / n_off

    distance = np.linspace(0, line_len, m_pts) * pixel_size
    return distance, out
