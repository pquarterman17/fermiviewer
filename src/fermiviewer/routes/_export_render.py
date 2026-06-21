"""PIL baking + SVG vector composition helpers for the /export route.

Extracted from routes/export.py to keep that file under the 500-line
god-module ceiling (test_repo_integrity.py). Not a public API — import
via routes/export.py only.
"""

from __future__ import annotations

import base64
import io
import math
from collections.abc import Sequence
from xml.sax.saxutils import escape

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

def _svg_end_glyph(cx: float, cy: float, sym: str, color: str,
                   r: float = 5.0, ang: float = 0.0) -> list[str]:
    """SVG elements for an endpoint glyph. Mirrors _draw_end_glyph()."""
    if sym == "bar":
        bl = r + 2
        ux, uy = -math.sin(ang), math.cos(ang)
        return [
            f'<line x1="{cx + bl * ux:.1f}" y1="{cy + bl * uy:.1f}" '
            f'x2="{cx - bl * ux:.1f}" y2="{cy - bl * uy:.1f}" '
            f'stroke="{color}" stroke-width="2"/>',
        ]
    if sym == "circle":
        return [f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" '
                f'fill="none" stroke="{color}" stroke-width="2"/>']
    if sym == "square":
        return [f'<rect x="{cx - r:.1f}" y="{cy - r:.1f}" '
                f'width="{r * 2:.1f}" height="{r * 2:.1f}" '
                f'fill="none" stroke="{color}" stroke-width="2"/>']
    if sym == "cross":
        return [
            f'<line x1="{cx - r:.1f}" y1="{cy - r:.1f}" '
            f'x2="{cx + r:.1f}" y2="{cy + r:.1f}" '
            f'stroke="{color}" stroke-width="2"/>',
            f'<line x1="{cx + r:.1f}" y1="{cy - r:.1f}" '
            f'x2="{cx - r:.1f}" y2="{cy + r:.1f}" '
            f'stroke="{color}" stroke-width="2"/>',
        ]
    return []  # "none"


def _svg_colorbar_parts(img: Image.Image,
                        cbar: tuple[bool, float, float], cmap: str) -> list[str]:
    """SVG <image>/<text> elements for the right-edge colorbar gutter."""
    strip = colorbar_strip(cmap, img.height, 20)
    sb = io.BytesIO()
    Image.fromarray(strip, mode="RGB").save(sb, format="PNG")
    s64 = base64.b64encode(sb.getvalue()).decode()
    cb_x = img.width + 5
    tx = cb_x + 24
    return [
        f'<image x="{cb_x}" width="20" height="{img.height}" '
        f'href="data:image/png;base64,{s64}"/>',
        f'<text x="{tx}" y="12" fill="white" font-family="monospace" '
        f'font-size="11">{escape(fmt_tick(cbar[2]))}</text>',
        f'<text x="{tx}" y="{img.height - 3}" fill="white" '
        f'font-family="monospace" font-size="11">'
        f'{escape(fmt_tick(cbar[1]))}</text>',
    ]


def _svg_caption_parts(img: Image.Image, total_w: int, band_h: int,
                       lines: list[str], font: int, pad: int,
                       line_h: int) -> list[str]:
    """SVG band rect + <text> lines for the report caption."""
    out = [
        f'<rect x="0" y="{img.height}" width="{total_w}" '
        f'height="{band_h}" fill="#141414"/>'
    ]
    ty = img.height + pad + font
    for ln in lines:
        out.append(
            f'<text x="{pad}" y="{ty}" fill="#ebebeb" '
            f'font-family="\'JetBrains Mono\', monospace" '
            f'font-size="{font}">{escape(ln)}</text>'
        )
        ty += line_h
    return out


def _svg_annotation_parts(an: Annotation, color: str,
                          text_attrs: str, line_width: int = 2) -> list[str]:
    """SVG vector elements (+ label) for one measurement annotation.
    Mirrors draw_annotations() on the raster side."""
    p = an.points
    sym = an.end_symbol
    lw = line_width
    if an.kind == "outline":
        # box-profile averaging box: closed polygon, no label/glyphs
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in p)
        return [f'<polygon points="{pts_str}" fill="none" '
                f'stroke="{color}" stroke-width="{lw}"/>']
    out: list[str] = []
    if an.kind in ("ellipse", "circle"):
        cx = (p[0][0] + p[1][0]) / 2
        cy = (p[0][1] + p[1][1]) / 2
        out.append(
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
            f'rx="{abs(p[1][0] - p[0][0]) / 2:.1f}" '
            f'ry="{abs(p[1][1] - p[0][1]) / 2:.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{lw}"/>'
        )
    elif an.kind in ("roi", "box"):
        x0 = min(p[0][0], p[1][0])
        y0 = min(p[0][1], p[1][1])
        out.append(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" '
            f'width="{abs(p[1][0] - p[0][0]):.1f}" '
            f'height="{abs(p[1][1] - p[0][1]):.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{lw}"/>'
        )
    elif an.kind == "text":
        pass  # caption only — <text> emitted below
    elif an.kind == "arrow":
        a, b = p[0], p[1]
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        head = 9.0
        wings = " ".join(
            f"{b[0] - head * math.cos(ang + da):.1f},"
            f"{b[1] - head * math.sin(ang + da):.1f}"
            for da in (-0.45, 0.45)
        ).split(" ")
        out.append(
            f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" '
            f'x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
            f'stroke="{color}" stroke-width="{lw}"/>'
        )
        out.append(
            f'<polyline points="{wings[0]} {b[0]:.1f},{b[1]:.1f} '
            f'{wings[1]}" fill="none" stroke="{color}" stroke-width="{lw}"/>'
        )
        out.extend(_svg_end_glyph(p[0][0], p[0][1], sym, color,
                                  ang=_seg_angle(p, 0)))
    elif an.kind in ("angle", "polyline"):
        pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in p)
        dash = ' stroke-dasharray="6 4"' if an.dashed else ""
        out.append(
            f'<polyline points="{pts_str}" fill="none" '
            f'stroke="{color}" stroke-width="{lw}"{dash}/>'
        )
        for i, pt in enumerate(p):
            out.extend(_svg_end_glyph(pt[0], pt[1], sym, color,
                                      ang=_seg_angle(p, i)))
    else:
        dash = ' stroke-dasharray="6 4"' if an.dashed else ""
        out.append(
            f'<line x1="{p[0][0]:.1f}" y1="{p[0][1]:.1f}" '
            f'x2="{p[1][0]:.1f}" y2="{p[1][1]:.1f}" '
            f'stroke="{color}" stroke-width="{lw}"{dash}/>'
        )
        for i, pt in enumerate(p[:2]):
            out.extend(_svg_end_glyph(pt[0], pt[1], sym, color,
                                      ang=_seg_angle(p, i)))
    out.append(
        f'<text x="{an.label_xy[0]:.1f}" y="{an.label_xy[1]:.1f}" '
        f'fill="{color}" {text_attrs}>{escape(an.label)}</text>'
    )
    return out


def build_svg(img: Image.Image, bar: ScaleBar | None,
              annos: list[Annotation], color: str,
              cbar: tuple[bool, float, float] = (False, 0.0, 1.0),
              cmap: str = "gray",
              font_size: int = _DEFAULT_FONT_SIZE,
              measure_font_size: int = 12, measure_line_width: int = 2,
              caption: str | None = None) -> str:
    """Full-res PNG embedded as <image> + vector overlay elements.

    `font_size` sets the scale-bar label font size (already scaled by the
    export scale factor). `measure_font_size` / `measure_line_width` style the
    measurement labels + strokes to match the on-screen overlay. `caption`, if
    given, is rendered as a dark band of <text> lines below the figure.
    """
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    total_w = img.width + (81 if cbar[0] else 0)  # pad+strip+labels
    cap_lines = (
        [ln for ln in caption.splitlines() if ln.strip()] if caption else []
    )
    cap_font, cap_pad, cap_line_h = 13, 6, 17
    band_h = (cap_pad * 2 + cap_line_h * len(cap_lines)) if cap_lines else 0
    total_h = img.height + band_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="{total_h}" '
        f'viewBox="0 0 {total_w} {total_h}">',
        f'<image width="{img.width}" height="{img.height}" '
        f'href="data:image/png;base64,{b64}"/>',
    ]
    if cbar[0]:
        parts.extend(_svg_colorbar_parts(img, cbar, cmap))
    # measurement labels: size matches the on-screen overlay (default 12)
    text_attrs = (f'font-family="\'JetBrains Mono\', monospace" '
                  f'font-size="{measure_font_size}" paint-order="stroke" '
                  'stroke="rgba(0,0,0,0.75)" stroke-width="3"')
    # scale-bar label: user-controlled font size + same family
    sb_font_attrs = (
        f'font-family="\'JetBrains Mono\', monospace" font-size="{font_size}" '
        f'paint-order="stroke" stroke="rgba(0,0,0,0.75)" stroke-width="3"'
    )

    if bar is not None:
        bar_fill = bar.color  # honours the color override (audit #10)
        parts.append(
            f'<rect x="{bar.x}" y="{bar.y}" width="{bar.width}" '
            f'height="{bar.height}" fill="{bar_fill}"/>'
        )
        label_y = bar.y - 5  # consistent gap above the bar
        parts.append(
            f'<text x="{bar.x}" y="{label_y}" fill="{bar_fill}" '
            f'{sb_font_attrs}>{escape(bar.label)}</text>'
        )

    for an in annos:
        parts.extend(_svg_annotation_parts(an, color, text_attrs,
                                            measure_line_width))

    if cap_lines:
        parts.extend(_svg_caption_parts(img, total_w, band_h, cap_lines,
                                        cap_font, cap_pad, cap_line_h))

    parts.append("</svg>")
    return "\n".join(parts)
