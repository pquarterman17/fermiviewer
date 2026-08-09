"""io.metadata accessors — getGrayscale / getStageTilt ports."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.io.metadata import (
    databar_content_rows,
    get_stage_tilt,
    stage_tilt_from_image_tags,
    to_grayscale,
)

pytestmark = pytest.mark.parser


def test_to_grayscale_bt601() -> None:
    rgb = np.zeros((2, 2, 3))
    rgb[..., 0] = 100  # pure red
    gray = to_grayscale(rgb)
    np.testing.assert_allclose(gray, 29.9)
    # 2-D passthrough
    flat = np.arange(6, dtype=np.float64).reshape(2, 3)
    np.testing.assert_array_equal(to_grayscale(flat), flat)
    with pytest.raises(ValueError):
        to_grayscale(np.zeros((2, 2, 2)))


def test_get_stage_tilt_heuristics() -> None:
    # FEI radians (|v| < pi) convert to degrees
    tilt, src = get_stage_tilt({"acq": {"Stage": {"StageT": 0.5}}})
    assert tilt == pytest.approx(np.degrees(0.5))
    assert src == "StageT"
    # FEI value already in degrees passes through
    tilt, _ = get_stage_tilt({"Stage": {"Tilt": 45.0}})
    assert tilt == pytest.approx(45.0)
    # Bruker key is always degrees, even small values
    tilt, src = get_stage_tilt({"semParams": {"stageTilt_deg": 2.0}})
    assert tilt == pytest.approx(2.0)
    assert src == "stageTilt_deg"
    # absent
    tilt, src = get_stage_tilt({"nothing": 1})
    assert np.isnan(tilt) and src == ""


def test_get_stage_tilt_prefers_the_normalized_key() -> None:
    """`stage_tilt_deg` is what a parser writes once it has applied its
    format's own deg/rad convention — it must outrank the guesswork keys."""
    tilt, src = get_stage_tilt({"stage_tilt_deg": 52.0, "StageT": 0.9075712})
    assert tilt == pytest.approx(52.0)
    assert src == "stage_tilt_deg"


def test_get_stage_tilt_finds_bruker_snake_case_key() -> None:
    """io/bcf.py writes `stage_tilt_deg` under `sem_params`; the table used
    to list only the camelCase `stageTilt_deg`, so no real .bcf ever matched."""
    tilt, src = get_stage_tilt({"sem_params": {"stage_tilt_deg": 2.0}})
    assert tilt == pytest.approx(2.0)   # degrees, NOT 2 rad = 114.6°
    assert src == "stage_tilt_deg"


def test_get_stage_tilt_skips_nan_values() -> None:
    tilt, src = get_stage_tilt({"stage_tilt_deg": float("nan"), "Tilt": 45.0})
    assert tilt == pytest.approx(45.0)
    assert src == "Tilt"


def test_stage_tilt_from_image_tags_per_format_units() -> None:
    # Gatan DM3/DM4/DM5: a dotted leaf, in degrees
    assert stage_tilt_from_image_tags(
        {"Microscope Info.Stage Position.Stage Alpha": 24.9505}
    ) == pytest.approx(24.9505)
    # Velox EMD (Thermo Fisher): radians, and stored as a string
    assert stage_tilt_from_image_tags(
        {"Stage.AlphaTilt": "-0.21967"}
    ) == pytest.approx(np.degrees(-0.21967))
    # a DM tag whose value is not numeric must not be mistaken for a tilt
    assert np.isnan(stage_tilt_from_image_tags(
        {"Microscope Info.Stage Position.Stage Alpha": "n/a"}
    ))
    assert np.isnan(stage_tilt_from_image_tags({}))
    assert np.isnan(stage_tilt_from_image_tags({"Optics.Voltage": 200000}))


# ── databar geometry ──────────────────────────────────────────────────

def test_databar_content_rows_prefers_declared_resolution() -> None:
    """A Helios frame: 1103 rows on disk, 1024 scanned, 79 of databar.
    `image_rows` IS the scanned height, so it wins over the subtraction."""
    meta = {"image_rows": 1024.0, "databar_height": 79.0}
    assert databar_content_rows(meta, 1103) == 1024


def test_databar_content_rows_falls_back_to_bar_height() -> None:
    """Files that record only the bar height still get an exact cut."""
    assert databar_content_rows({"databar_height": 79.0}, 1103) == 1024
    # strings are coerced, not isinstance-rejected (vendor tags vary)
    assert databar_content_rows({"databar_height": "79"}, 1103) == 1024


def test_databar_content_rows_is_none_without_a_bar() -> None:
    """Every non-FEI format, and FEI files whose declared resolution equals
    the array — the caller reads None as "nothing to avoid or crop"."""
    assert databar_content_rows({}, 512) is None
    assert databar_content_rows({"parser": "tiff"}, 512) is None
    # no bar: declared resolution == array height
    assert databar_content_rows({"image_rows": 512.0}, 512) is None


def test_databar_content_rows_rejects_impossible_geometry() -> None:
    """Garbage must not produce a crop that would empty or grow the image.
    A bar at least as tall as the frame, or a resolution taller than the
    array, are both inconsistent — fall through rather than trust them."""
    assert databar_content_rows({"databar_height": 1103.0}, 1103) is None
    assert databar_content_rows({"databar_height": 2000.0}, 1103) is None
    assert databar_content_rows({"image_rows": 4096.0}, 1103) is None
    assert databar_content_rows({"databar_height": 0.0}, 1103) is None
    assert databar_content_rows({"databar_height": -79.0}, 1103) is None
    assert databar_content_rows({"databar_height": "n/a"}, 1103) is None
    assert databar_content_rows({"databar_height": None}, 1103) is None
    # an inconsistent image_rows still falls through to a usable bar height
    assert databar_content_rows(
        {"image_rows": 4096.0, "databar_height": 79.0}, 1103
    ) == 1024
