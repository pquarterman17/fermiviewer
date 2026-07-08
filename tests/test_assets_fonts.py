"""Unit tests for fermiviewer.assets.fonts and its two downstream font
loaders (routes/_export_render.py + calc/montage.py).

test_api_export.py's test_vendored_font_path already covers the happy
dev-layout path (TTF present at src/fermiviewer/assets/fonts/). This file
covers the remaining branches: the PyInstaller-frozen (_MEIPASS) layout,
the last-resort "return the expected path even though it's missing" case,
and — the actual point of `jetbrains_mono_regular` existing at all — that
a missing/corrupt TTF never crashes a caller, it just falls through to
PIL's built-in bitmap font.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest
from PIL import Image

from fermiviewer.assets import fonts

pytestmark = pytest.mark.api


# ── jetbrains_mono_regular() path resolution ────────────────────────────


def test_dev_layout_is_found_by_default() -> None:
    """Sanity check for the other tests in this file: the real dev-layout
    TTF must exist so `_HERE`-based candidates are exercised elsewhere by
    contrast (this is the same assertion as test_vendored_font_path)."""
    path = fonts.jetbrains_mono_regular()
    assert path.exists()
    assert path.name == "JetBrainsMono-Regular.ttf"


def test_frozen_pyinstaller_layout_is_found_when_dev_candidate_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When the dev/wheel candidate under `_HERE` doesn't exist, but
    sys._MEIPASS is set (frozen PyInstaller build) and the font is staged
    there, resolve to the frozen path."""
    fake_here = tmp_path / "assets"
    fake_here.mkdir()  # no "fonts" subdir -> dev candidate can't exist
    monkeypatch.setattr(fonts, "_HERE", fake_here)

    meipass = tmp_path / "meipass"
    frozen_dir = meipass / "fermiviewer" / "assets" / "fonts"
    frozen_dir.mkdir(parents=True)
    frozen_ttf = frozen_dir / "JetBrainsMono-Regular.ttf"
    frozen_ttf.write_bytes(b"not-a-real-ttf-just-bytes")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

    result = fonts.jetbrains_mono_regular()
    assert result == frozen_ttf
    assert result.exists()


def test_last_resort_path_returned_when_nothing_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Neither the dev candidate nor a frozen layout exists (no
    sys._MEIPASS at all) -> falls through to the last-resort candidate
    path, which the caller must handle being absent."""
    fake_here = tmp_path / "assets"
    fake_here.mkdir()
    monkeypatch.setattr(fonts, "_HERE", fake_here)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    result = fonts.jetbrains_mono_regular()
    assert result == fake_here / "fonts" / "JetBrainsMono-Regular.ttf"
    assert not result.exists()


def test_meipass_set_but_font_missing_falls_back_to_last_resort(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """sys._MEIPASS is set but the frozen TTF isn't actually staged there
    (e.g. a broken build) -> falls through to the same last-resort
    candidate as the no-_MEIPASS case, not an exception."""
    fake_here = tmp_path / "assets"
    fake_here.mkdir()
    monkeypatch.setattr(fonts, "_HERE", fake_here)
    monkeypatch.setattr(
        sys, "_MEIPASS", str(tmp_path / "empty_meipass"), raising=False
    )

    result = fonts.jetbrains_mono_regular()
    assert result == fake_here / "fonts" / "JetBrainsMono-Regular.ttf"
    assert not result.exists()


# ── downstream fallback chain: missing TTF must never crash a caller ───


def test_export_render_load_font_returns_none_on_missing_ttf(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from fermiviewer.routes import _export_render

    missing = tmp_path / "nope.ttf"
    monkeypatch.setattr(
        fonts, "jetbrains_mono_regular", lambda: missing
    )
    assert _export_render._load_font(20) is None


def test_montage_load_font_returns_none_on_missing_ttf(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from fermiviewer.calc import montage

    missing = tmp_path / "nope.ttf"
    monkeypatch.setattr(
        fonts, "jetbrains_mono_regular", lambda: missing
    )
    assert montage._load_font(14) is None


def test_draw_scale_bar_falls_back_to_pil_default_without_crashing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """End-to-end: with no usable TTF, draw_scale_bar must still bake a
    bar + label using PIL's built-in bitmap font (the `else` branch of
    `if font is not None` in routes/_export_render.py:draw_scale_bar)."""
    from fermiviewer.calc.export import ScaleBar
    from fermiviewer.routes._export_render import draw_scale_bar

    missing = tmp_path / "nope.ttf"
    monkeypatch.setattr(
        fonts, "jetbrains_mono_regular", lambda: missing
    )
    img = Image.new("RGB", (100, 60), (0, 0, 0))
    bar = ScaleBar(x=10, y=40, width=30, height=4, label="20 nm")
    draw_scale_bar(img, bar, font_size=20)  # must not raise
    assert img.getextrema() != ((0, 0), (0, 0), (0, 0))  # something got drawn


def test_montage_label_bakes_via_pil_default_without_ttf(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Same fallback chain exercised through calc/montage.py's own
    `_load_font` + `_bake_label`, via the public `montage()` entry
    point."""
    from fermiviewer.calc.montage import montage

    missing = tmp_path / "nope.ttf"
    monkeypatch.setattr(
        fonts, "jetbrains_mono_regular", lambda: missing
    )
    frames = [np.zeros((48, 80)) + float(i) for i in range(2)]
    out_labeled = montage(frames, cols=2, labels=["a", "b"], gap=2)
    out_unlabeled = montage(frames, cols=2, labels=None, gap=2)
    assert out_labeled.shape == out_unlabeled.shape
    assert not np.array_equal(out_labeled, out_unlabeled)
