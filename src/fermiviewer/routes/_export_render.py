"""PIL raster baking helpers for the /export route.

Extracted from routes/export.py to keep that file under the 500-line
god-module ceiling (test_repo_integrity.py). Not a public API — import
via routes/export.py only.

SVG vector composition (which shares `fmt_tick` / `_seg_angle` with this
module) lives in ``_export_svg.py`` — split out to keep both files under
the ceiling — and ``build_svg`` is re-exported below.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

from fermiviewer.calc.export import Annotation, ScaleBar, colorbar_strip

# ── font loading (item #48) ──────────────────────────────────────────

_DEFAULT_FONT_SIZE = 20  # matches ScaleBarCard default

def _load_font(size: int) -> FreeTypeFont | None:
    """Load JetBrains Mono Regular at `size` px via vendored TTF.

    Returns None on any failure so the caller can fall back to PIL's
    built-in bitmap font (no crash on missing/corrupt TTF)."""
    try:
        from fermiviewer.assets.fonts import jetbrains_mono_regular
        ttf = jetbrains_mono_regular()
        return ImageFont.truetype(str(ttf), size=size)
    except Exception:  # noqa: BLE001 — font load failures are non-fatal
        return None


# ── PIL raster baking ────────────────────────────────────────────────

def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Parse a #rrggbb hex string → (r, g, b).  Falls back to white on error."""
    c = color.lstrip("#")
    if len(c) == 6:
        try:
            return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
        except ValueError:
            pass
    return (255, 255, 255)


def draw_scale_bar(img: Image.Image, bar: ScaleBar,
                   font_size: int = _DEFAULT_FONT_SIZE) -> None:
    """Bake the scale bar + label into `img` in-place.

    Bar and label colour come from bar.color (hex, default "#ffffff" — white,
    preserving byte-identical output when color is absent/default).
    `font_size` is the already-scaled size (on-screen px × export scale).
    Falls back to PIL's default bitmap font if the TTF cannot be loaded.
    """
    rgb = _hex_to_rgb(bar.color)
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [bar.x, bar.y, bar.x + bar.width, bar.y + bar.height],
        fill=rgb,
    )
    font = _load_font(font_size)
    label_y = bar.y - font_size - 2  # keep gap above the bar regardless of size
    if font is not None:
        draw.text((bar.x, label_y), bar.label, fill=rgb,
                  font=font, stroke_width=1, stroke_fill=(0, 0, 0))
    else:
        draw.text((bar.x, bar.y - 14), bar.label, fill=rgb,
                  stroke_width=1, stroke_fill=(0, 0, 0))


def _dashed_line(draw: ImageDraw.ImageDraw, a: tuple[float, float],
                 b: tuple[float, float], color: tuple[int, int, int],
                 width: int, dash: float = 6.0, gap: float = 4.0) -> None:
    """PIL has no dash support — draw the segments (profile lines)."""
    total = float(np.hypot(b[0] - a[0], b[1] - a[1]))
    if total <= 0:
        return
    ux, uy = (b[0] - a[0]) / total, (b[1] - a[1]) / total
    pos = 0.0
    while pos < total:
        end = min(pos + dash, total)
        draw.line([(a[0] + ux * pos, a[1] + uy * pos),
                   (a[0] + ux * end, a[1] + uy * end)],
                  fill=color, width=width)
        pos = end + gap


def _draw_end_glyph(draw: ImageDraw.ImageDraw, cx: float, cy: float,
                    sym: str, color: tuple[int, int, int], r: int = 5,
                    ang: float = 0.0) -> None:
    """Draw a measurement endpoint glyph (bar / circle / square / cross)
    at (cx, cy). Mirrors the SVG EndpointGlyph in MeasureOverlay.tsx.
    `ang` is the adjacent-segment direction (radians) — the "bar" glyph
    is a dimension-style tick drawn perpendicular to it."""
    if sym == "bar":
        bl = r + 2
        ux, uy = -math.sin(ang), math.cos(ang)
        draw.line([(cx + bl * ux, cy + bl * uy),
                   (cx - bl * ux, cy - bl * uy)], fill=color, width=2)
    elif sym == "circle":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    elif sym == "square":
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    elif sym == "cross":
        draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=color, width=2)
        draw.line([(cx + r, cy - r), (cx - r, cy + r)], fill=color, width=2)
    # "none" → no glyph


def _seg_angle(pts: Sequence[tuple[float, float]], i: int) -> float:
    """Direction (radians) of the segment adjacent to pts[i]."""
    if len(pts) < 2:
        return 0.0
    nb = pts[1] if i == 0 else pts[i - 1]
    return math.atan2(nb[1] - pts[i][1], nb[0] - pts[i][0])


def _draw_glyphs(draw: ImageDraw.ImageDraw,
                 pts: Sequence[tuple[float, float]], sym: str,
                 color: tuple[int, int, int]) -> None:
    for i, pt in enumerate(pts):
        _draw_end_glyph(draw, pt[0], pt[1], sym, color,
                        ang=_seg_angle(pts, i))


def _draw_box_kind(draw: ImageDraw.ImageDraw, an: Annotation,
                   color: tuple[int, int, int], lw: int = 2) -> None:
    p = an.points
    x0 = min(p[0][0], p[1][0])
    y0 = min(p[0][1], p[1][1])
    x1 = max(p[0][0], p[1][0])
    y1 = max(p[0][1], p[1][1])
    if an.kind in ("ellipse", "circle"):
        draw.ellipse([x0, y0, x1, y1], outline=color, width=lw)
    else:
        draw.rectangle([x0, y0, x1, y1], outline=color, width=lw)


def _draw_arrow_kind(draw: ImageDraw.ImageDraw, an: Annotation,
                     color: tuple[int, int, int], lw: int = 2) -> None:
    a, b = an.points[0], an.points[1]
    draw.line([a, b], fill=color, width=lw)
    ang = float(np.arctan2(b[1] - a[1], b[0] - a[0]))
    head = 9.0
    for da in (-0.45, 0.45):
        draw.line(
            [b, (b[0] - head * np.cos(ang + da),
                 b[1] - head * np.sin(ang + da))],
            fill=color, width=lw,
        )
    _draw_end_glyph(draw, a[0], a[1], an.end_symbol, color,
                    ang=math.atan2(b[1] - a[1], b[0] - a[0]))


def draw_annotations(img: Image.Image, annos: list[Annotation],
                     color: tuple[int, int, int], line_width: int = 2,
                     label_font_size: int | None = None) -> None:
    draw = ImageDraw.Draw(img)
    lw = line_width
    font = _load_font(label_font_size) if label_font_size else None
    for an in annos:
        p = an.points
        sym = an.end_symbol
        if an.kind == "outline":
            # box-profile averaging box: closed solid polygon, no label
            draw.polygon([tuple(pt) for pt in p], outline=color, width=lw)
            continue
        if an.kind in ("roi", "box", "ellipse", "circle"):
            _draw_box_kind(draw, an, color, lw)
        elif an.kind == "text":
            pass  # caption only — drawn below
        elif an.kind == "arrow":
            _draw_arrow_kind(draw, an, color, lw)
        elif an.kind == "angle":
            draw.line([p[0], p[1], p[2]], fill=color, width=lw)
            _draw_glyphs(draw, p, sym, color)
        elif an.kind == "polyline":
            for i in range(len(p) - 1):
                _dashed_line(draw, p[i], p[i + 1], color, lw)
            _draw_glyphs(draw, p, sym, color)
        elif an.dashed:
            _dashed_line(draw, p[0], p[1], color, lw)
            _draw_glyphs(draw, p[:2], sym, color)
        else:
            draw.line([p[0], p[1]], fill=color, width=lw)
            _draw_glyphs(draw, p[:2], sym, color)
        draw.text(an.label_xy, an.label, fill=color, font=font,
                  stroke_width=2, stroke_fill=(0, 0, 0))


def fmt_tick(v: float) -> str:
    a = abs(v)
    if a != 0 and (a < 0.01 or a >= 1e5):
        return f"{v:.2e}"
    return f"{v:.4g}"


def _wrap_text(draw: ImageDraw.ImageDraw, line: str,
               font: FreeTypeFont | None, max_w: float) -> list[str]:
    """Greedy word-wrap a single line to `max_w` px. Without a TTF (bitmap
    fallback) we can't measure reliably, so the line is returned as-is."""
    if font is None or not line:
        return [line]
    out: list[str] = []
    cur = ""
    for word in line.split(" "):
        trial = f"{cur} {word}".strip()
        if not cur or draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def caption_band_lines(img: Image.Image, text: str, scale: int) -> list[str]:
    """The wrapped caption lines for `text` at the image width (shared by
    raster + SVG so both bands have identical wrapping)."""
    probe = ImageDraw.Draw(img)
    font = _load_font(max(11, 13 * scale))
    pad = max(6, 5 * scale)
    wrapped: list[str] = []
    for raw in text.splitlines():
        if raw.strip():
            wrapped.extend(_wrap_text(probe, raw, font, img.width - 2 * pad))
    return wrapped


def draw_caption_band(img: Image.Image, text: str,
                      scale: int = 1) -> Image.Image:
    """Return a new image with a caption strip appended below `img`.

    `text` may be multi-line; each line is word-wrapped to the image width.
    The strip is a dark band with light text so it reads cleanly beneath the
    typically-dark EM image edge. Empty/whitespace text → `img` unchanged."""
    lines = caption_band_lines(img, text, scale)
    if not lines:
        return img
    font_size = max(11, 13 * scale)
    font = _load_font(font_size)
    pad = max(6, 5 * scale)
    line_h = font_size + max(2, 2 * scale)
    band_h = pad * 2 + line_h * len(lines)
    out = Image.new("RGB", (img.width, img.height + band_h), (20, 20, 20))
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    y = img.height + pad
    for ln in lines:
        if font is not None:
            draw.text((pad, y), ln, fill=(235, 235, 235), font=font)
        else:
            draw.text((pad, y), ln, fill=(235, 235, 235))
        y += line_h
    return out


def composite_colorbar(img: Image.Image, cmap: str, lo: float,
                       hi: float) -> Image.Image:
    """Paste a right-edge colorbar strip with min/max labels."""
    pad, width, label_w = 5, 20, 56
    strip = colorbar_strip(cmap, img.height, width)
    out = Image.new("RGB", (img.width + pad + width + label_w, img.height))
    out.paste(img, (0, 0))
    out.paste(Image.fromarray(strip, mode="RGB"), (img.width + pad, 0))
    draw = ImageDraw.Draw(out)
    x = img.width + pad + width + 4
    draw.text((x, 2), fmt_tick(hi), fill=(255, 255, 255))
    draw.text((x, img.height - 14), fmt_tick(lo), fill=(255, 255, 255))
    return out


# ── SVG vector composition ───────────────────────────────────────────
# Moved to _export_svg.py (split out to respect the 500-line ceiling) and
# re-exported here so routes/export.py's import list keeps working.
from fermiviewer.routes._export_svg import build_svg  # noqa: E402 — re-export
