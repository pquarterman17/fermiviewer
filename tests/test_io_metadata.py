"""io.metadata accessors — getGrayscale / getStageTilt ports."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.io.metadata import (
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
