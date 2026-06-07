"""Export rendering — pure numpy composition for the /export endpoint.

Mirrors the WebGL display pipeline (window/gamma/LUT, calc/render.py
semantics) at integer upscale factors, and computes scale-bar geometry
for overlay baking. Text rendering and file encoding live in the route
layer (PIL/tifffile are I/O concerns).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.colormaps import build_lut
from fermiviewer.calc.render import window_level

__all__ = [
    "Annotation",
    "ScaleBar",
    "measure_annotations",
    "render_rgb",
    "render_u16",
    "scale_bar_geometry",
]


def _upscale(arr: np.ndarray, scale: int) -> np.ndarray:
    """Nearest-neighbour integer upscale (pixel-exact, like the stage)."""
    if scale == 1:
        return arr
    return np.repeat(np.repeat(arr, scale, axis=0), scale, axis=1)


def render_rgb(
    raster: np.ndarray,
    lo: float | None = None,
    hi: float | None = None,
    gamma: float = 1.0,
    cmap: str = "gray",
    scale: int = 1,
) -> np.ndarray:
    """Windowed + gamma + colormapped uint8 RGB at an integer scale.

    lo/hi are in REAL intensity units (None → full range), matching
    calc.render.window_level — the wire layer converts the client's
    normalized window using the raster min/max.
    """
    if not 1 <= scale <= 4:
        raise ValueError("scale must be in [1, 4]")
    t = window_level(raster, lo, hi, gamma)
    idx = (t * 255.0 + 0.5).astype(np.uint8)
    rgb = build_lut(cmap)[idx]
    return _upscale(rgb, scale)


def render_u16(
    raster: np.ndarray,
    lo: float | None = None,
    hi: float | None = None,
    gamma: float = 1.0,
    scale: int = 1,
) -> np.ndarray:
    """Windowed 16-bit grayscale (TIFF-16 export; no colormap)."""
    if not 1 <= scale <= 4:
        raise ValueError("scale must be in [1, 4]")
    t = window_level(raster, lo, hi, gamma)
    return _upscale((t * 65535.0 + 0.5).astype(np.uint16), scale)


@dataclass(frozen=True)
class ScaleBar:
    """Bar geometry in OUTPUT pixels + its label text."""

    x: int
    y: int
    width: int
    height: int
    label: str


def _nice_length(max_phys: float) -> float:
    """Largest 1/2/5×10ⁿ below max_phys (mirrors lib/geometry.ts)."""
    exp = float(np.floor(np.log10(max_phys)))
    base = 10.0**exp
    for m in (5.0, 2.0, 1.0):
        if m * base <= max_phys:
            return float(m * base)
    return float(base / 2.0)


@dataclass(frozen=True)
class Annotation:
    """One measurement in OUTPUT pixels, ready for any renderer
    (PIL baking or SVG elements). Mirrors MeasureOverlay.tsx exactly:
    line for distance, dashed line for profile, polyline for angle
    (vertex = pts[1]), rect for roi; same label text and offsets."""

    kind: str                                  # distance|profile|angle|roi
    points: tuple[tuple[float, float], ...]    # (x, y) output px
    label: str
    label_xy: tuple[float, float]
    dashed: bool = False


def _fmt(v: float) -> str:
    """Mirror MeasureOverlay's fmt(): 4 sig figs, exponential outside
    [0.01, 1e5)."""
    if not np.isfinite(v):
        return "—"
    a = abs(v)
    if a != 0 and (a < 0.01 or a >= 1e5):
        return f"{v:.2e}"
    return f"{v:.4g}"


def measure_annotations(
    measures: list[dict],
    img_h: int,
    img_w: int,
    pixel_size: float | None,
    pixel_unit: str,
    scale: int,
    raster: np.ndarray | None = None,
) -> list[Annotation]:
    """Measures (normalized 0–1 pts, the client's store format) →
    output-pixel annotations. `raster` (source resolution) enables the
    on-screen μ/σ label for ROIs; without it ROIs get W×H dims."""
    out: list[Annotation] = []
    for m in measures:
        kind = str(m.get("kind", ""))
        pts_n = [(float(p["x"]), float(p["y"])) for p in m.get("pts", [])]
        if len(pts_n) < 2:
            continue
        ipts = [(x * img_w, y * img_h) for x, y in pts_n]       # image px
        opts = tuple((x * scale, y * scale) for x, y in ipts)   # output px

        if kind in ("distance", "profile"):
            d = float(np.hypot(ipts[1][0] - ipts[0][0],
                               ipts[1][1] - ipts[0][1]))
            label = (f"{_fmt(d * pixel_size)} {pixel_unit}"
                     if pixel_size else f"{_fmt(d)} px")
            mid = ((opts[0][0] + opts[1][0]) / 2 + 8,
                   (opts[0][1] + opts[1][1]) / 2 - 8)
            out.append(Annotation(kind, opts[:2], label, mid,
                                  dashed=kind == "profile"))
        elif kind == "polyline" and len(ipts) >= 2:
            total = float(sum(
                np.hypot(ipts[i + 1][0] - ipts[i][0],
                         ipts[i + 1][1] - ipts[i][1])
                for i in range(len(ipts) - 1)
            ))
            label = (f"{_fmt(total * pixel_size)} {pixel_unit}"
                     if pixel_size else f"{_fmt(total)} px")
            last = opts[-1]
            out.append(Annotation(kind, opts, label,
                                  (last[0] + 10, last[1] - 10), dashed=True))
        elif kind == "angle" and len(ipts) >= 3:
            v, a, b = ipts[1], ipts[0], ipts[2]
            a1 = np.arctan2(a[1] - v[1], a[0] - v[0])
            a2 = np.arctan2(b[1] - v[1], b[0] - v[0])
            deg = abs(float(a1 - a2)) * 180.0 / np.pi
            if deg > 180.0:
                deg = 360.0 - deg
            out.append(Annotation(kind, opts[:3], f"{deg:.1f}°",
                                  (opts[1][0] + 10, opts[1][1] - 10)))
        elif kind == "roi":
            (x0, y0), (x1, y1) = ipts[0], ipts[1]
            if raster is not None:
                r0, r1 = sorted((int(y0), int(y1)))
                c0, c1 = sorted((int(x0), int(x1)))
                sel = raster[max(r0, 0):r1 + 1, max(c0, 0):c1 + 1]
                label = (f"μ {_fmt(float(sel.mean()))} · "
                         f"σ {_fmt(float(sel.std()))}"
                         if sel.size else "—")
            else:
                w_px, h_px = abs(x1 - x0), abs(y1 - y0)
                label = f"{_fmt(w_px)} × {_fmt(h_px)} px"
            lx = min(opts[0][0], opts[1][0])
            ly = min(opts[0][1], opts[1][1]) - 6
            out.append(Annotation(kind, opts[:2], label, (lx, ly)))
    return out


def scale_bar_geometry(
    out_w: int,
    out_h: int,
    pixel_size: float,
    pixel_unit: str,
    scale: int,
) -> ScaleBar:
    """Scale bar sized to ≤ ~25 % of the output width, bottom-left.

    pixel_size is per SOURCE pixel; the output is `scale`× finer.
    """
    eff_px = pixel_size / scale  # physical size per output pixel
    phys = _nice_length(0.25 * out_w * eff_px)
    width = max(1, round(phys / eff_px))
    height = max(2, out_h // 80)
    margin = max(8, out_w // 50)
    label = f"{phys:g} {pixel_unit}"
    return ScaleBar(
        x=margin,
        y=out_h - margin - height,
        width=width,
        height=height,
        label=label,
    )
