"""Surface roughness parameters — W3 tranche 3 (ported verbatim).

ISO-style scalar roughness (Ra/Rq/Rz/Rsk/Rku/Rp/Rv) on optionally
plane-levelled heights, triangulated surface-area ratio, and the
bearing-ratio curve. Reuses calc.filters.plane_level.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.filters import plane_level

__all__ = ["RoughnessResult", "surface_roughness"]


@dataclass(frozen=True)
class RoughnessResult:
    ra: float
    rq: float
    rz: float
    rsk: float
    rku: float
    rp: float
    rv: float
    sar: float
    bearing_heights: np.ndarray  # sorted descending
    bearing_fraction: np.ndarray
    n_pixels: int
    level: str


def surface_roughness(
    img: np.ndarray,
    pixel_size: float = 1.0,
    level: str = "plane",
    mask: np.ndarray | None = None,
) -> RoughnessResult:
    """Roughness statistics; level ∈ {'none', 'plane', 'quadratic'}."""
    d = np.asarray(img, dtype=np.float64)
    h, w = d.shape

    if mask is None:
        m = np.ones((h, w), dtype=bool)
    else:
        m = np.asarray(mask, dtype=bool)
        if m.shape != (h, w):
            raise ValueError("mask must match image shape")
        if not m.any():
            raise ValueError("mask contains no true pixels")

    if level not in ("none", "plane", "quadratic"):
        raise ValueError("level must be 'none', 'plane' or 'quadratic'")

    # NaN-robustness is a deliberate extension beyond the MATLAB reference
    # (same convention as the 2026-06 grain-finding hardening and
    # calc.trace_roughness): a single non-finite pixel used to poison every
    # metric silently (NaN mean -> NaN everything downstream, and lstsq
    # inside plane_level would return NaN coefficients for the WHOLE
    # surface). Drop non-finite samples from the active mask instead, and
    # report NaN/empty when too few valid pixels remain to level/summarize.
    mf = m & np.isfinite(d)
    min_valid = {"none": 1, "plane": 3, "quadratic": 6}[level]
    if int(mf.sum()) < min_valid:
        return RoughnessResult(
            ra=float("nan"), rq=float("nan"), rz=float("nan"),
            rsk=float("nan"), rku=float("nan"), rp=float("nan"), rv=float("nan"),
            sar=float("nan"),
            bearing_heights=np.empty(0), bearing_fraction=np.empty(0),
            n_pixels=int(mf.sum()), level=level,
        )

    if level == "plane":
        d = plane_level(d, order=1, mask=mf).leveled
    elif level == "quadratic":
        d = plane_level(d, order=2, mask=mf).leveled

    z = d[mf]
    zc = z - z.mean()
    rq = float(np.sqrt((zc**2).mean()))

    # surface-area ratio over the FULL image (not masked), triangulated.
    # A NaN corner poisons only the triangle(s) touching it (not the whole
    # sum): exclude non-finite triangles from both the numerator and the
    # projected-area denominator so a few dead pixels don't NaN the ratio.
    ps = pixel_size
    z00 = d[:-1, :-1]
    z01 = d[:-1, 1:]
    z10 = d[1:, :-1]
    z11 = d[1:, 1:]
    tri1 = 0.5 * np.sqrt(
        (ps * (z10 - z00)) ** 2 + (ps * (z01 - z00)) ** 2 + ps**4
    )
    tri2 = 0.5 * np.sqrt(
        (ps * (z10 - z11)) ** 2 + (ps * (z01 - z11)) ** 2 + ps**4
    )
    n_valid_tris = int(np.isfinite(tri1).sum() + np.isfinite(tri2).sum())
    projected = n_valid_tris * 0.5 * ps**2
    sar = float((np.nansum(tri1) + np.nansum(tri2)) / projected) if projected > 0 else 1.0

    heights = np.sort(z)[::-1]
    n = z.size

    return RoughnessResult(
        ra=float(np.abs(zc).mean()),
        rq=rq,
        rz=float(z.max() - z.min()),
        rsk=float((zc**3).mean() / rq**3) if rq > 0 else 0.0,
        rku=float((zc**4).mean() / rq**4) if rq > 0 else 0.0,
        rp=float(zc.max()),
        rv=float(abs(zc.min())),
        sar=sar,
        bearing_heights=heights,
        bearing_fraction=np.arange(1, n + 1) / n,
        n_pixels=n,
        level=level,
    )
