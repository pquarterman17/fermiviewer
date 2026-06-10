"""PIL baking + SVG vector composition helpers for the /export route.

Extracted from routes/export.py to keep that file under the 500-line
god-module ceiling (test_repo_integrity.py). Not a public API — import
via routes/export.py only.
"""

from __future__ import annotations

import base64
import io
import math
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw

from fermiviewer.calc.export import Annotation, ScaleBar, colorbar_strip


# ── PIL raster baking ────────────────────────────────────────────────

def draw_scale_bar(img: Image.Image, bar: ScaleBar) -> None:
    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [bar.x, bar.y, bar.x + bar.width, bar.y + bar.height],
        fill=(255, 255, 255),
    )
    draw.text((bar.x, bar.y - 14), bar.label, fill=(255, 255, 255),
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
                    sym: str, color: tuple[int, int, int], r: int = 5) -> None:
    """Draw a measurement endpoint glyph (circle / square / cross) at (cx, cy).
    Mirrors the SVG EndpointGlyph in MeasureOverlay.tsx."""
    if sym == "circle":
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    elif sym == "square":
        draw.rectangle([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    elif sym == "cross":
        draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=color, width=2)
        draw.line([(cx + r, cy - r), (cx - r, cy + r)], fill=color, width=2)
    # "none" → no glyph


def draw_annotations(img: Image.Image, annos: list[Annotation],
                     color: tuple[int, int, int]) -> None:
    draw = ImageDraw.Draw(img)
    for an in annos:
        p = an.points
        sym = an.end_symbol
        if an.kind in ("roi", "box", "ellipse", "circle"):
            x0 = min(p[0][0], p[1][0])
            y0 = min(p[0][1], p[1][1])
            x1 = max(p[0][0], p[1][0])
            y1 = max(p[0][1], p[1][1])
            if an.kind in ("ellipse", "circle"):
                draw.ellipse([x0, y0, x1, y1], outline=color, width=2)
            else:
                draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
        elif an.kind == "text":
            pass  # caption only — drawn below
        elif an.kind == "arrow":
            a, b = p[0], p[1]
            draw.line([a, b], fill=color, width=2)
            ang = float(np.arctan2(b[1] - a[1], b[0] - a[0]))
            head = 9.0
            for da in (-0.45, 0.45):
                draw.line(
                    [b, (b[0] - head * np.cos(ang + da),
                         b[1] - head * np.sin(ang + da))],
                    fill=color, width=2,
                )
            _draw_end_glyph(draw, p[0][0], p[0][1], sym, color)
        elif an.kind == "angle":
            draw.line([p[0], p[1], p[2]], fill=color, width=2)
            for pt in p:
                _draw_end_glyph(draw, pt[0], pt[1], sym, color)
        elif an.kind == "polyline":
            for i in range(len(p) - 1):
                _dashed_line(draw, p[i], p[i + 1], color, 2)
            for pt in p:
                _draw_end_glyph(draw, pt[0], pt[1], sym, color)
        elif an.dashed:
            _dashed_line(draw, p[0], p[1], color, 2)
            for pt in p[:2]:
                _draw_end_glyph(draw, pt[0], pt[1], sym, color)
        else:
            draw.line([p[0], p[1]], fill=color, width=2)
            for pt in p[:2]:
                _draw_end_glyph(draw, pt[0], pt[1], sym, color)
        draw.text(an.label_xy, an.label, fill=color,
                  stroke_width=2, stroke_fill=(0, 0, 0))


def fmt_tick(v: float) -> str:
    a = abs(v)
    if a != 0 and (a < 0.01 or a >= 1e5):
        return f"{v:.2e}"
    return f"{v:.4g}"


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
                   r: float = 5.0) -> list[str]:
    """SVG elements for an endpoint glyph. Mirrors _draw_end_glyph()."""
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


def build_svg(img: Image.Image, bar: ScaleBar | None,
              annos: list[Annotation], color: str,
              cbar: tuple[bool, float, float] = (False, 0.0, 1.0),
              cmap: str = "gray") -> str:
    """Full-res PNG embedded as <image> + vector overlay elements."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    total_w = img.width + (81 if cbar[0] else 0)  # pad+strip+labels
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{total_w}" height="{img.height}" '
        f'viewBox="0 0 {total_w} {img.height}">',
        f'<image width="{img.width}" height="{img.height}" '
        f'href="data:image/png;base64,{b64}"/>',
    ]
    if cbar[0]:
        strip = colorbar_strip(cmap, img.height, 20)
        sb = io.BytesIO()
        Image.fromarray(strip, mode="RGB").save(sb, format="PNG")
        s64 = base64.b64encode(sb.getvalue()).decode()
        cb_x = img.width + 5
        parts.append(
            f'<image x="{cb_x}" width="20" height="{img.height}" '
            f'href="data:image/png;base64,{s64}"/>'
        )
        tx = cb_x + 24
        parts.append(
            f'<text x="{tx}" y="12" fill="white" font-family="monospace" '
            f'font-size="11">{escape(fmt_tick(cbar[2]))}</text>'
        )
        parts.append(
            f'<text x="{tx}" y="{img.height - 3}" fill="white" '
            f'font-family="monospace" font-size="11">'
            f'{escape(fmt_tick(cbar[1]))}</text>'
        )
    text_attrs = ('font-family="monospace" font-size="12" '
                  'paint-order="stroke" stroke="rgba(0,0,0,0.75)" '
                  'stroke-width="3"')

    if bar is not None:
        parts.append(
            f'<rect x="{bar.x}" y="{bar.y}" width="{bar.width}" '
            f'height="{bar.height}" fill="white"/>'
        )
        parts.append(
            f'<text x="{bar.x}" y="{bar.y - 5}" fill="white" '
            f'{text_attrs}>{escape(bar.label)}</text>'
        )

    for an in annos:
        p = an.points
        sym = an.end_symbol
        if an.kind in ("ellipse", "circle"):
            cx = (p[0][0] + p[1][0]) / 2
            cy = (p[0][1] + p[1][1]) / 2
            parts.append(
                f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" '
                f'rx="{abs(p[1][0] - p[0][0]) / 2:.1f}" '
                f'ry="{abs(p[1][1] - p[0][1]) / 2:.1f}" fill="none" '
                f'stroke="{color}" stroke-width="2"/>'
            )
        elif an.kind in ("roi", "box"):
            x0 = min(p[0][0], p[1][0])
            y0 = min(p[0][1], p[1][1])
            w = abs(p[1][0] - p[0][0])
            h = abs(p[1][1] - p[0][1])
            parts.append(
                f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" '
                f'height="{h:.1f}" fill="none" stroke="{color}" '
                f'stroke-width="2"/>'
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
            parts.append(
                f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" '
                f'x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            parts.append(
                f'<polyline points="{wings[0]} {b[0]:.1f},{b[1]:.1f} '
                f'{wings[1]}" fill="none" stroke="{color}" '
                f'stroke-width="2"/>'
            )
            parts.extend(_svg_end_glyph(p[0][0], p[0][1], sym, color))
        elif an.kind in ("angle", "polyline"):
            pts_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in p)
            dash = ' stroke-dasharray="6 4"' if an.dashed else ""
            parts.append(
                f'<polyline points="{pts_str}" fill="none" '
                f'stroke="{color}" stroke-width="2"{dash}/>'
            )
            for pt in p:
                parts.extend(_svg_end_glyph(pt[0], pt[1], sym, color))
        else:
            dash = ' stroke-dasharray="6 4"' if an.dashed else ""
            parts.append(
                f'<line x1="{p[0][0]:.1f}" y1="{p[0][1]:.1f}" '
                f'x2="{p[1][0]:.1f}" y2="{p[1][1]:.1f}" '
                f'stroke="{color}" stroke-width="2"{dash}/>'
            )
            for pt in p[:2]:
                parts.extend(_svg_end_glyph(pt[0], pt[1], sym, color))
        parts.append(
            f'<text x="{an.label_xy[0]:.1f}" y="{an.label_xy[1]:.1f}" '
            f'fill="{color}" {text_attrs}>{escape(an.label)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)
