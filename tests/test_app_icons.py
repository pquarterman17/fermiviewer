"""App-icon source and generated-asset integrity."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def test_favicon_contains_cat_and_diffraction_motifs() -> None:
    svg = (ROOT / "frontend" / "public" / "favicon.svg").read_text()
    assert "Black cat peeking over the aperture rim" in svg
    assert "Electron-microscope aperture" in svg
    assert svg.count("<circle") >= 8


def test_readme_uses_accessible_logo_lockup() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    logo_path = ROOT / "docs" / "images" / "fermiviewer-logo.svg"
    logo = logo_path.read_text(encoding="utf-8")

    assert 'src="docs/images/fermiviewer-logo.svg"' in readme
    assert 'alt="FermiViewer — electron microscopy image analysis"' in readme
    assert "<title" in logo and "<desc" in logo
    assert "FermiViewer" in logo


def test_native_icon_dimensions_and_transparency() -> None:
    icons = ROOT / "src-tauri" / "icons"
    expected = {
        "icon.png": (512, 512),
        "32x32.png": (32, 32),
        "128x128.png": (128, 128),
        "128x128@2x.png": (256, 256),
    }
    for name, size in expected.items():
        with Image.open(icons / name) as image:
            assert image.size == size
            assert image.convert("RGBA").getpixel((0, 0))[3] == 0

    with Image.open(icons / "icon.ico") as image:
        assert image.format == "ICO"
    with Image.open(icons / "icon.icns") as image:
        assert image.format == "ICNS"
