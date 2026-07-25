"""Regenerate FermiViewer desktop icons from the cat-aperture design.

The web favicon is the editable vector source. Pillow draws the same small
set of flat primitives at high resolution so native PNG/ICO/ICNS assets do
not require an SVG renderer or a platform-specific design application.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "src-tauri" / "icons"
SCALE = 4
CANVAS = 512


def _box(values: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    # Unpacked rather than tuple(... for ...), which is tuple[int, ...] to a
    # type checker and loses the fixed 4-length the return type promises.
    x0, y0, x1, y1 = values
    return (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE)


def _points(values: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(x * SCALE, y * SCALE) for x, y in values]


def draw_icon() -> Image.Image:
    image = Image.new("RGBA", (CANVAS * SCALE, CANVAS * SCALE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle(_box((8, 8, 504, 504)), radius=104 * SCALE,
                           fill="#16141d")
    draw.ellipse(_box((68, 47, 444, 423)), fill="#8b5cf6")
    draw.ellipse(_box((92, 71, 420, 399)), fill="#211936")
    draw.ellipse(_box((101, 80, 411, 390)), outline="#7b679c",
                 width=6 * SCALE)

    for x, y, radius in [
        (256, 151, 13), (256, 96, 7), (190, 118, 8), (322, 118, 8),
        (158, 184, 8), (354, 184, 8), (202, 218, 7), (310, 218, 7),
    ]:
        draw.ellipse(_box((x - radius, y - radius, x + radius, y + radius)),
                     fill="#c4b5fd")

    outline = "#594878"
    black = "#050509"
    ear_width = 8 * SCALE
    draw.polygon(_points([(143, 349), (154, 260), (222, 319), (204, 359)]),
                 fill=black)
    draw.line(_points([(143, 349), (154, 260), (222, 319)]), fill=outline,
              width=ear_width, joint="curve")
    draw.polygon(_points([(369, 349), (358, 260), (290, 319), (308, 359)]),
                 fill=black)
    draw.line(_points([(369, 349), (358, 260), (290, 319)]), fill=outline,
              width=ear_width, joint="curve")
    draw.polygon(_points([(164, 281), (202, 315), (159, 331)]), fill="#8b5cf6")
    draw.polygon(_points([(348, 281), (310, 315), (353, 331)]), fill="#8b5cf6")

    draw.ellipse(_box((130, 282, 382, 464)), fill=black, outline=outline,
                 width=8 * SCALE)
    for cx in (207, 305):
        draw.ellipse(_box((cx - 25, 335, cx + 25, 397)), fill="#b9a4ff")
        draw.ellipse(_box((cx - 12, 352, cx + 12, 390)), fill="#09080d")
        draw.ellipse(_box((cx - 11, 354, cx - 1, 364)), fill="#ffffff")
    draw.polygon(_points([(247, 402), (256, 409), (265, 402), (256, 397)]),
                 fill="#a78bfa")

    for cx in (137, 375):
        draw.ellipse(_box((cx - 38, 366, cx + 38, 450)), fill=black,
                     outline=outline, width=8 * SCALE)
    for x in (127, 143, 365, 381):
        draw.line(_points([(x, 405), (x, 429)]), fill="#8b5cf6",
                  width=5 * SCALE)

    return image.resize((CANVAS, CANVAS), Image.Resampling.LANCZOS)


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    icon = draw_icon()
    icon.save(ICON_DIR / "icon.png")
    for size, name in [
        (32, "32x32.png"),
        (128, "128x128.png"),
        (256, "128x128@2x.png"),
    ]:
        icon.resize((size, size), Image.Resampling.LANCZOS).save(
            ICON_DIR / name
        )
    icon.save(
        ICON_DIR / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
               (64, 64), (128, 128), (256, 256)],
    )
    icon.save(ICON_DIR / "icon.icns")


if __name__ == "__main__":
    main()
