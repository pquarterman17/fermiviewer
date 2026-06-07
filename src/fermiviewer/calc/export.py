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

__all__ = ["ScaleBar", "render_rgb", "render_u16", "scale_bar_geometry"]


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
