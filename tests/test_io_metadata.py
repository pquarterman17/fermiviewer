"""io.metadata accessors — getGrayscale / getStageTilt ports."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.io.metadata import get_stage_tilt, to_grayscale

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
