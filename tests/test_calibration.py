"""Pixel-extent helpers in `calc.calibration`."""

from __future__ import annotations

import math

import pytest

from fermiviewer.calc.calibration import line_axis_scales

pytestmark = pytest.mark.imaging




def test_line_axis_scales_projects_onto_the_drawn_direction() -> None:
    """A box profile's depth runs along the LINE, so on anisotropic pixels
    neither the row nor the column extent is its scale.

    `growth_axis_scales` only answers for a stack aligned to the image axes.
    Using it for a free line put sigma_w and the correlation length in the
    wrong units for any angle off the axes.
    """
    spacing = (4.0, 1.0)   # 4 nm rows, 1 nm columns

    # straight down the rows: the row extent, and columns across
    assert line_axis_scales(1.0, 0.0, 1.0, spacing) == pytest.approx((4.0, 1.0))
    # straight across the columns: the transpose
    assert line_axis_scales(0.0, 1.0, 1.0, spacing) == pytest.approx((1.0, 4.0))
    # at 45 degrees a step covers sqrt((4/√2)² + (1/√2)²) ≈ 2.92 nm --
    # neither 4 nor 1, which is the whole point
    along, across = line_axis_scales(1.0, 1.0, 1.0, spacing)
    assert along == pytest.approx(math.hypot(4.0, 1.0) / math.sqrt(2))
    assert across == pytest.approx(along)          # symmetric at 45 deg
    assert 1.0 < along < 4.0

    # no usable spacing: both fall back to pixel_size, so a square-pixel or
    # uncalibrated image behaves exactly as before
    assert line_axis_scales(1.0, 1.0, 0.7, None) == pytest.approx((0.7, 0.7))
