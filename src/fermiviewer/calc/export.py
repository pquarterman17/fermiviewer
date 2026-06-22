"""Export rendering — pure numpy composition for the /export endpoint.

Mirrors the WebGL display pipeline (window/gamma/LUT, calc/render.py
semantics) at integer upscale factors, and computes scale-bar geometry
for overlay baking. Text rendering and file encoding live in the route
layer (PIL/tifffile are I/O concerns).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.colormaps import build_label_lut, build_lut
from fermiviewer.calc.render import window_level

__all__ = [
    "Annotation",
    "ScaleBar",
    "colorbar_strip",
    "measure_annotations",
    "render_rgb",
    "render_u16",
    "scale_bar_geometry",
]


def colorbar_strip(
    cmap: str, height: int, width: int = 20
) -> np.ndarray:
    """Vertical colorbar strip (port of addColorbar.m's strip half):
    max value at the TOP, uint8 RGB [height, width, 3]. Label text is
    the caller's concern (mirrors the MATLAB design, which returns
    label metadata instead of burning text)."""
    lut = build_lut(cmap)                       # [256, 3] uint8
    idx = np.linspace(255, 0, max(height, 2)).astype(np.uint8)
    out: np.ndarray = np.repeat(lut[idx][:, None, :], width, axis=1)
    return out


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
    n_labels: int | None = None,
) -> np.ndarray:
    """Windowed + gamma + colormapped uint8 RGB at an integer scale.

    lo/hi are in REAL intensity units (None → full range), matching
    calc.render.window_level — the wire layer converts the client's
    normalized window using the raster min/max.

    For the discrete grain palette (cmap="label"), pass n_labels (the
    map's max id + 1) so the band count matches the stage exactly; the
    caller windows lo=0/hi=n_labels-1 so each integer id lands on its band.
    """
    if not 1 <= scale <= 4:
        raise ValueError("scale must be in [1, 4]")
    t = window_level(raster, lo, hi, gamma)
    idx = (t * 255.0 + 0.5).astype(np.uint8)
    lut = build_label_lut(n_labels) if cmap == "label" and n_labels else build_lut(cmap)
    rgb = lut[idx]
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
    """Bar geometry in OUTPUT pixels + its label text.

    color: hex string (default "#ffffff" → white, matches legacy behaviour).
    label_override: if set, replaces the auto-derived unit label text.
    """

    x: int
    y: int
    width: int
    height: int
    label: str
    color: str = "#ffffff"           # bar + label colour (audit #10)
    label_override: str | None = None  # unit-override text (audit #10)


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
    end_symbol: str = "none"  # circle|cross|square|none


def _fmt(v: float) -> str:
    """Mirror MeasureOverlay's fmt(): 4 sig figs, exponential outside
    [0.01, 1e5)."""
    if not np.isfinite(v):
        return "—"
    a = abs(v)
    if a != 0 and (a < 0.01 or a >= 1e5):
        return f"{v:.2e}"
    return f"{v:.4g}"


def _tilt_seg_len(
    p0: tuple[float, float],
    p1: tuple[float, float],
    tilt_angle_deg: float,
    tilt_axis: str,
    tilt_geometry: str,
) -> float:
    """Segment length with the measure_distance tilt correction:
    in-tilt-axis component × 1/sin θ (cross-section) or 1/cos θ
    (surface). No-op at θ=0. Mirrors calc/profiles.measure_distance."""
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    if tilt_angle_deg:
        rad = float(np.radians(tilt_angle_deg))
        f = (1.0 / np.cos(rad) if tilt_geometry == "surface"
             else 1.0 / np.sin(rad))
        if tilt_axis.upper() == "X":
            dx *= f
        else:
            dy *= f
    return float(np.hypot(dx, dy))


def _box_outline(
    m: dict,
    kind: str,
    ipts: list[tuple[float, float]],
    opts: tuple[tuple[float, float], ...],
    scale: float,
) -> list[Annotation]:
    """Box profiles (width set) bake the averaging-box outline around
    the dashed centerline — mirrors MeasureOverlay. Empty list for
    plain profiles/distances."""
    box_w = m.get("width")
    if kind != "profile" or not box_w:
        return []
    ang = np.arctan2(ipts[1][1] - ipts[0][1], ipts[1][0] - ipts[0][0])
    half = float(box_w) / 2.0 * scale
    ox = float(-np.sin(ang)) * half
    oy = float(np.cos(ang)) * half
    (ax, ay), (bx, by) = opts[0], opts[1]
    corners = ((ax + ox, ay + oy), (bx + ox, by + oy),
               (bx - ox, by - oy), (ax - ox, ay - oy))
    return [Annotation("outline", corners, "", (0.0, 0.0),
                       end_symbol="none")]


def measure_annotations(
    measures: list[dict],
    img_h: int,
    img_w: int,
    pixel_size: float | None,
    pixel_unit: str,
    scale: float,
    raster: np.ndarray | None = None,
    tilt_angle_deg: float = 0.0,
    tilt_axis: str = "Y",
    tilt_geometry: str = "cross-section",
) -> list[Annotation]:
    """Measures (normalized 0–1 pts, the client's store format) →
    output-pixel annotations. `raster` (source resolution) enables the
    on-screen μ/σ label for ROIs; without it ROIs get W×H dims.
    Non-zero `tilt_angle_deg` applies the measure_distance correction
    to distance/profile/polyline LABELS (geometry is drawn as-is),
    matching the on-screen corrected labels."""
    out: list[Annotation] = []
    for m in measures:
        kind = str(m.get("kind", ""))
        text = str(m.get("text") or "")
        end_symbol = str(m.get("endSymbol") or m.get("end_symbol") or "none")
        pts_n = [(float(p["x"]), float(p["y"])) for p in m.get("pts", [])]
        if len(pts_n) < (1 if kind == "text" else 2):
            continue
        ipts = [(x * img_w, y * img_h) for x, y in pts_n]       # image px
        opts = tuple((x * scale, y * scale) for x, y in ipts)   # output px

        if kind == "text":
            out.append(Annotation(kind, opts[:1], text,
                                  (opts[0][0] + 6, opts[0][1] - 6),
                                  end_symbol=end_symbol))
            continue
        if kind == "arrow":
            out.append(Annotation(kind, opts[:2], text,
                                  (opts[0][0] + 8, opts[0][1] - 8),
                                  end_symbol=end_symbol))
            continue
        if kind in ("box", "circle"):
            lx = min(opts[0][0], opts[1][0])
            ly = min(opts[0][1], opts[1][1]) - 6
            out.append(Annotation(kind, opts[:2], text, (lx, ly),
                                  end_symbol=end_symbol))
            continue

        if kind in ("distance", "profile"):
            d = _tilt_seg_len(ipts[0], ipts[1], tilt_angle_deg,
                              tilt_axis, tilt_geometry)
            label = (f"{_fmt(d * pixel_size)} {pixel_unit}"
                     if pixel_size else f"{_fmt(d)} px")
            mid = ((opts[0][0] + opts[1][0]) / 2 + 8,
                   (opts[0][1] + opts[1][1]) / 2 - 8)
            out.extend(_box_outline(m, kind, ipts, opts, scale))
            out.append(Annotation(kind, opts[:2], label, mid,
                                  dashed=kind == "profile",
                                  end_symbol=end_symbol))
        elif kind == "polyline" and len(ipts) >= 2:
            total = float(sum(
                _tilt_seg_len(ipts[i], ipts[i + 1], tilt_angle_deg,
                              tilt_axis, tilt_geometry)
                for i in range(len(ipts) - 1)
            ))
            label = (f"{_fmt(total * pixel_size)} {pixel_unit}"
                     if pixel_size else f"{_fmt(total)} px")
            last = opts[-1]
            out.append(Annotation(kind, opts, label,
                                  (last[0] + 10, last[1] - 10), dashed=True,
                                  end_symbol=end_symbol))
        elif kind == "angle" and len(ipts) >= 3:
            v, a, b = ipts[1], ipts[0], ipts[2]
            a1 = np.arctan2(a[1] - v[1], a[0] - v[0])
            a2 = np.arctan2(b[1] - v[1], b[0] - v[0])
            deg = abs(float(a1 - a2)) * 180.0 / np.pi
            if deg > 180.0:
                deg = 360.0 - deg
            out.append(Annotation(kind, opts[:3], f"{deg:.1f}°",
                                  (opts[1][0] + 10, opts[1][1] - 10),
                                  end_symbol=end_symbol))
        elif kind in ("roi", "ellipse"):
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
            out.append(Annotation(kind, opts[:2], label, (lx, ly),
                                  end_symbol=end_symbol))
    return out


def _bar_label(phys: float, unit: str) -> str:
    """Scale-bar label with sub-unit step-down — mirrors fmtSub() in
    Stage.tsx (Å preferred over pm below 1 nm, EM convention)."""
    chains: dict[str, list[tuple[str, float]]] = {
        "µm": [("nm", 1e3), ("Å", 1e4)],
        "um": [("nm", 1e3), ("Å", 1e4)],
        "nm": [("Å", 10.0), ("pm", 1e3)],
    }
    if phys < 1:
        for u, f in chains.get(unit, []):
            if phys * f >= 1:
                return f"{float(f'{phys * f:.3g}'):g} {u}"
    return f"{float(f'{phys:.3g}'):g} {unit}"


# Conversion factors to nm (same basis as lib/geometry.ts unitToNm)
_TO_NM: dict[str, float] = {
    "pm": 1e-3, "Å": 0.1, "nm": 1.0, "µm": 1e3, "um": 1e3,
    "mm": 1e6, "m": 1e9,
}


def _bar_label_with_unit(phys: float, src_unit: str, tgt_unit: str) -> str:
    """Express `phys` (in src_unit) using `tgt_unit` for the label.

    Falls back to the auto label when the conversion is unknown.
    Mirrors the frontend unitToNm table (lib/geometry.ts).
    """
    f_src = _TO_NM.get(src_unit)
    f_tgt = _TO_NM.get(tgt_unit)
    if f_src is None or f_tgt is None:
        return _bar_label(phys, src_unit)
    converted = phys * f_src / f_tgt
    return f"{float(f'{converted:.3g}'):g} {tgt_unit}"


def scale_bar_geometry(
    out_w: int,
    out_h: int,
    pixel_size: float,
    pixel_unit: str,
    scale: float,
    *,
    norm_x: float | None = None,
    norm_y: float | None = None,
    length_phys: float | None = None,
    thickness: int | None = None,
    color: str = "#ffffff",
    unit_override: str | None = None,
) -> ScaleBar:
    """Scale bar sized to ≤ ~25 % of the output width.

    pixel_size is per SOURCE pixel; the output is `scale`× finer.

    Optional keyword overrides (all backward-compatible defaults):
    - norm_x / norm_y: normalised position (0–1) in the output image.
    - length_phys: physical bar length in pixel_unit; None → auto.
    - thickness: bar height in output px; None → auto.
    - color: hex bar/label colour (audit #10); default "#ffffff" (white).
    - unit_override: force a specific unit string in the label (audit #10);
      None → auto-derived via _bar_label (EM sub-unit step-down).
    """
    eff_px = pixel_size / scale  # physical size per output pixel
    phys = length_phys if length_phys is not None else _nice_length(0.25 * out_w * eff_px)
    width = max(1, round(phys / eff_px))
    height = thickness if thickness is not None else max(2, out_h // 80)
    margin = max(8, out_w // 50)

    if norm_x is not None and norm_y is not None:
        x = max(margin, min(out_w - width - margin, round(norm_x * out_w)))
        y = max(margin + height, min(out_h - margin - height, round(norm_y * out_h)))
    else:
        x = margin
        y = out_h - margin - height

    if unit_override is not None:
        # Apply unit step-down relative to the override unit so that
        # e.g. "force Å" still auto-picks a nice round number in Å.
        label = _bar_label(phys, pixel_unit)
        # Replace the auto-unit suffix with the requested one, keeping
        # the numeric prefix (the same phys value expressed in the new
        # unit via _bar_label-style rounding).
        label = _bar_label_with_unit(phys, pixel_unit, unit_override)
    else:
        label = _bar_label(phys, pixel_unit)
    return ScaleBar(
        x=x,
        y=y,
        width=width,
        height=height,
        label=label,
        color=color,
    )
