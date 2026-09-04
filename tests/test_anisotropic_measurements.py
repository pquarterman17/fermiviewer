"""Lengths and angles that used to take one pixel scale for two axes.

`DataStruct.pixel_size` is the COLUMN scale alone -- `pixel_cal` returns
``axes[1]``. Three measurements multiplied by it anyway:

* `calc/defects.count_defect_lines` -- Ham's density is ``2N / L``, and
  `L` summed the vertical test lines' ROW extents using the column scale;
* `calc/export.measure_annotations` -- distance, profile and polyline
  labels hypot'd the pixel components and scaled the result, which is the
  length of the wrong triangle, and the angle label arctan2'd raw pixel
  components;
* `calc/eds_maps.composition_profile` -- the distance axis of a diagonal
  line profile, same wrong triangle.

Every expectation below is closed-form physical geometry computed from
the inputs, or an invariance a real measurement must satisfy. None of it
re-evaluates the expression under test.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pytest

from fermiviewer.calc.calibration import (
    physical_angle_rad,
    physical_length,
    resolve_spacing,
)
from fermiviewer.calc.defects import count_defect_lines
from fermiviewer.calc.eds_maps import composition_profile
from fermiviewer.calc.export import measure_annotations

#: 3 units per row, 4 per column -- deliberately unequal, and deliberately
#: not a ratio that a 3-4-5 triangle would flatter.
ANISO = (3.0, 4.0)


def _pt(x: float, y: float) -> dict[str, float]:
    """A measure point in the client's normalised store format."""
    return {"x": x, "y": y}


def _num(label: str) -> float:
    """The numeric part of a rendered annotation label."""
    m = re.match(r"^\s*(-?[\d.]+(?:e[-+]?\d+)?)", label)
    assert m, f"no number in {label!r}"
    return float(m.group(1))


# ── the primitive ────────────────────────────────────────────────────────


def test_scaling_must_happen_before_the_pythagorean_sum() -> None:
    """The whole defect in one line.

    A displacement of 30 columns and 40 rows on (row 3, col 4) pixels
    spans 120 physical units each way, so it is 120*sqrt(2) = 169.7 long.
    Hypot-then-scale gives hypot(30, 40) * 4 = 200 -- a 17.8% overstatement
    that carries the right unit and looks entirely plausible.
    """
    assert physical_length(30, 40, ANISO) == pytest.approx(120 * math.sqrt(2))
    assert physical_length(30, 40, ANISO) != pytest.approx(math.hypot(30, 40) * 4)


def test_an_angle_is_not_spared_by_being_dimensionless() -> None:
    """A 45-degree line on the pixel grid is not 45 degrees in the
    specimen unless the pixels are square. On 1:3 pixels it rises at
    arctan(3) = 71.6 degrees."""
    got = math.degrees(physical_angle_rad(10, 10, (3.0, 1.0)))
    assert got == pytest.approx(math.degrees(math.atan(3.0)))


def test_square_pixels_reduce_to_hypot_times_the_scale() -> None:
    """The backward-compatibility identity: with equal extents the new
    expression IS the old one, so no isotropic number moves."""
    for s in (0.5, 1.0, 7.25):
        assert physical_length(30, 40, (s, s)) == pytest.approx(
            math.hypot(30, 40) * s, rel=1e-15
        )


@pytest.mark.parametrize(
    ("spacing", "pixel_size", "expected"),
    [
        ((2.0, 5.0), 9.0, (2.0, 5.0)),          # explicit spacing wins
        (None, 9.0, (9.0, 9.0)),                # isotropic fallback
        ((float("nan"), float("nan")), 9.0, (9.0, 9.0)),  # uncalibrated axes
        ((0.0, 5.0), 9.0, (9.0, 9.0)),          # a zero extent is not a scale
        (None, 0.0, (1.0, 1.0)),                # nor is a zero pixel_size
        (None, float("nan"), (1.0, 1.0)),
    ],
)
def test_precedence_and_fallback(
    spacing: tuple[float, float] | None, pixel_size: float,
    expected: tuple[float, float],
) -> None:
    """`pixel_spacing` returns ``(nan, nan)`` for uncalibrated or
    unit-mismatched axes, so that is the live path, not a corner. Falling
    through to 1 rather than multiplying a length by zero or NaN is the
    same rule #203 settled on."""
    assert resolve_spacing(spacing, pixel_size) == expected


# ── calc/defects: Ham line-intercept total length ────────────────────────


def _line_image(h: int = 120, w: int = 120) -> np.ndarray:
    rng = np.random.default_rng(7)
    img = rng.normal(1.0, 0.05, (h, w))
    img[:, 20:24] = 8.0
    img[:, 60:64] = 8.0
    img[30:34, :] = 8.0
    return img


def test_every_test_line_across_a_physically_square_roi_is_equal() -> None:
    """The oracle that needs no formula.

    A ROI of 40 rows and 120 columns on (row 3, col 1) pixels is 120 by
    120 in the specimen. So it does not matter which way round the
    extents go: every test line, horizontal or vertical, is exactly 120
    long, and the total is simply the line count times 120.

    Under the single-scale form the vertical lines came out 40 long
    instead of 120 -- and only the TOTAL enters Ham's ``2N / L``, so the
    error lands straight on the reported density.
    """
    res = count_defect_lines(
        _line_image(), roi=(1, 1, 40, 120), grid_spacing=20,
        pixel_size=1.0, spacing=(3.0, 1.0),
    )
    n_lines = res.h_rows.size + res.v_cols.size
    assert n_lines >= 4, "fixture must place lines along both axes"
    assert res.total_line_length == pytest.approx(n_lines * 120.0)


def test_defect_line_length_pairs_each_axis_with_its_own_extent() -> None:
    """The same claim on a ROI that is square in NEITHER space, so
    swapping the two extents cannot pass by symmetry -- 120 rows against
    80 columns, and 3 against 4."""
    res = count_defect_lines(
        _line_image(), roi=(1, 1, 120, 80), grid_spacing=25,
        pixel_size=4.0, spacing=ANISO,
    )
    n_h, n_v = res.h_rows.size, res.v_cols.size
    assert res.total_line_length == pytest.approx(
        n_h * 80 * ANISO[1] + n_v * 120 * ANISO[0]
    )
    # neither the single-scale form nor the swapped pairing
    assert res.total_line_length != pytest.approx(
        n_h * 80 * 4.0 + n_v * 120 * 4.0
    )
    assert res.total_line_length != pytest.approx(
        n_h * 80 * ANISO[0] + n_v * 120 * ANISO[1]
    )


def test_defect_density_survives_transposing_the_sampling() -> None:
    """Transposing the image and swapping the pixel extents describes the
    SAME specimen, so a physical density must not move. The ROI is square
    in pixels so the two runs place the same number of test lines."""
    img = _line_image()
    a = count_defect_lines(
        img, roi=(1, 1, 120, 120), grid_spacing=40, spacing=(3.0, 4.0)
    )
    b = count_defect_lines(
        img.T.copy(), roi=(1, 1, 120, 120), grid_spacing=40, spacing=(4.0, 3.0)
    )
    assert a.total_line_length == pytest.approx(b.total_line_length)
    assert a.intersection_count == b.intersection_count
    assert a.density == pytest.approx(b.density)


def test_defects_square_pixels_are_unchanged() -> None:
    """`pixel_size` alone must still mean what it meant."""
    img = _line_image()
    kw = {"roi": (1, 1, 120, 120), "grid_spacing": 40}
    legacy = count_defect_lines(img, pixel_size=2.5, **kw)
    explicit = count_defect_lines(img, spacing=(2.5, 2.5), **kw)
    assert legacy.total_line_length == explicit.total_line_length
    assert legacy.total_line_length == pytest.approx(
        (legacy.h_rows.size + legacy.v_cols.size) * 120 * 2.5
    )


# ── calc/export: measurement labels ──────────────────────────────────────


def _distance_label(spacing: tuple[float, float] | None, **kw: object) -> float:
    """Label number for a 30-column, 40-row segment on a 100x100 image."""
    measures = [{"kind": "distance", "pts": [_pt(0.1, 0.1), _pt(0.4, 0.5)]}]
    annos = measure_annotations(
        measures, 100, 100, 4.0, "nm", 1.0, spacing=spacing, **kw
    )
    return _num(annos[-1].label)


def test_distance_label_measures_the_physical_segment() -> None:
    """0.1->0.4 of 100 columns is 30 columns; 0.1->0.5 of 100 rows is 40
    rows. On (3, 4) pixels that is 120 by 120, so 169.7 nm -- not the 200
    the hypot-then-scale form printed onto the exported figure."""
    assert _distance_label(ANISO) == pytest.approx(120 * math.sqrt(2), rel=1e-3)
    assert _distance_label(None) == pytest.approx(math.hypot(30, 40) * 4.0, rel=1e-3)


def test_polyline_label_sums_physical_segments() -> None:
    """A polyline is the sum of its segments, each of which has the same
    problem; summing pixel lengths first and scaling once is wrong for
    every segment that is not axis-aligned."""
    measures = [{
        "kind": "polyline",
        "pts": [_pt(0.1, 0.1), _pt(0.4, 0.5), _pt(0.7, 0.1)],
    }]
    annos = measure_annotations(
        measures, 100, 100, 4.0, "nm", 1.0, spacing=ANISO
    )
    one = physical_length(30, 40, ANISO)
    assert _num(annos[-1].label) == pytest.approx(2 * one, rel=1e-3)


def test_angle_label_is_the_specimen_angle_not_the_grid_angle() -> None:
    """Vertex at the origin, one arm along +columns and one at 45 degrees
    on the grid. On (3, 1) pixels the second arm really rises at
    arctan(3) = 71.6 degrees, so the annotation must read that."""
    measures = [{
        "kind": "angle",
        "pts": [_pt(0.3, 0.1), _pt(0.1, 0.1), _pt(0.3, 0.3)],
    }]
    annos = measure_annotations(
        measures, 100, 100, 1.0, "nm", 1.0, spacing=(3.0, 1.0)
    )
    assert _num(annos[-1].label) == pytest.approx(
        math.degrees(math.atan(3.0)), abs=0.05
    )
    square = measure_annotations(
        measures, 100, 100, 1.0, "nm", 1.0, spacing=(1.0, 1.0)
    )
    assert _num(square[-1].label) == pytest.approx(45.0, abs=0.05)


def test_uncalibrated_export_still_reports_pixels() -> None:
    """`pixel_size=None` is the client's "no calibration" signal and must
    keep printing px, whatever `spacing` says -- the label's unit and its
    number have to come from the same decision."""
    measures = [{"kind": "distance", "pts": [_pt(0.1, 0.1), _pt(0.4, 0.5)]}]
    annos = measure_annotations(
        measures, 100, 100, None, "nm", 1.0, spacing=ANISO
    )
    assert annos[-1].label.endswith("px")
    assert _num(annos[-1].label) == pytest.approx(math.hypot(30, 40), rel=1e-3)


def test_tilt_correction_still_applies_and_commutes() -> None:
    """The tilt factor is a scalar on one component and the pixel extent
    is another, so they commute -- correcting before the physical sum
    must equal scaling a corrected pixel component."""
    measures = [{"kind": "distance", "pts": [_pt(0.1, 0.1), _pt(0.4, 0.5)]}]
    annos = measure_annotations(
        measures, 100, 100, 4.0, "nm", 1.0, spacing=ANISO,
        tilt_angle_deg=30.0, tilt_axis="Y", tilt_geometry="surface",
    )
    f = 1.0 / math.cos(math.radians(30.0))
    assert _num(annos[-1].label) == pytest.approx(
        math.hypot(30 * 4.0, 40 * f * 3.0), rel=1e-3
    )


# ── calc/eds_maps: line-profile distance axis ────────────────────────────


def test_composition_profile_distance_is_a_physical_length() -> None:
    """The profile runs 30 columns and 40 rows; its physical length is
    169.7, not hypot(30, 40) scaled by one number."""
    maps = [np.ones((100, 100)), np.zeros((100, 100))]
    dist, pct = composition_profile(
        maps, ["Fe", "O"], 10.0, 10.0, 40.0, 50.0,
        n_points=64, pixel_size=4.0, spacing=ANISO,
    )
    assert dist[0] == 0.0
    assert dist[-1] == pytest.approx(physical_length(30, 40, ANISO))
    assert dist[-1] != pytest.approx(math.hypot(30, 40) * 4.0)
    assert pct.shape == (64, 2)


def test_composition_profile_sampling_is_untouched() -> None:
    """Only the distance AXIS is physical. The line and its width-average
    offsets index the maps, so they must stay in pixel coordinates -- a
    'fix' that scaled `line_len` too would silently resample the data.
    """
    rng = np.random.default_rng(11)
    maps = [rng.normal(5.0, 1.0, (100, 100))]
    args = (maps, ["Fe"], 10.0, 10.0, 40.0, 50.0)
    _, flat = composition_profile(*args, n_points=64, width=3.0)
    _, aniso = composition_profile(
        *args, n_points=64, width=3.0, spacing=ANISO
    )
    np.testing.assert_array_equal(flat, aniso)


def test_composition_profile_square_pixels_are_unchanged() -> None:
    maps = [np.ones((100, 100))]
    a, _ = composition_profile(
        maps, ["Fe"], 10.0, 10.0, 40.0, 50.0, n_points=32, pixel_size=2.5
    )
    b, _ = composition_profile(
        maps, ["Fe"], 10.0, 10.0, 40.0, 50.0, n_points=32, spacing=(2.5, 2.5)
    )
    np.testing.assert_allclose(a, b, rtol=1e-15)
    assert a[-1] == pytest.approx(math.hypot(30, 40) * 2.5)
