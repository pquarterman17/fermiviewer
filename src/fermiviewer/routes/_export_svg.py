"""SVG vector composition for the /export route (split from _export_render.py).

Builds the true-vector SVG export: an embedded full-res PNG plus vector
scale bar / measurement-overlay / colorbar / caption elements, mirroring the
PIL raster baking in ``_export_render.py``. Kept out of ``_export_render.py``
(was 496 lines) to keep both files under the 500-line god-module ceiling
(test_repo_integrity.py). Not a public API — import via routes/export.py
only.

``fmt_tick`` / ``_seg_angle`` are shared with ``_export_render.py``; since
that module re-exports ``build_svg`` from here, the cross-imports are done
lazily (inside the functions that need them) so the two modules can be
imported in either order without a circular-import error.
"""

from __future__ import annotations

import base64
import io
import math
from xml.sax.saxutils import escape

from PIL import Image

from fermiviewer.calc.export import Annotation, ScaleBar, colorbar_strip

_DEFAULT_FONT_SIZE = 20  # matches ScaleBarCard default; mirrors _export_render.py


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
    from fermiviewer.routes._export_render import fmt_tick

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
    from fermiviewer.routes._export_render import _seg_angle

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
