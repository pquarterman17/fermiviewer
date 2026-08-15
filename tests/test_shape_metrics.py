"""calc/shape_metrics.py — pure-layer tests (SHAPE_ANALYSIS_PLAN Wave 1
#1/#2). No FastAPI/IO here; API-level wiring is covered by
test_api_particles_shape.py.

CONTRACT NOTE (flagged for the integrator, not worked around here):
SHAPE_ANALYSIS_PLAN.md Convention #2 states the mandatory pins as
"large synthetic disk -> circularity ~= 1" and "filled square -> ~=
pi/4 ~= 0.785". The disk pin holds exactly as specified. The square
pin does NOT hold under the Convention #1-mandated metric source
(`skimage.measure.regionprops_table`'s `perimeter_crofton`, the same
call `grains.grain_stats` makes, with its hardcoded `directions=4`):
that estimator has a documented directional bias for axis-aligned
polygons and converges to ~0.874 for a large square, not pi/4 ~=
0.785 -- an ~11% gap, verified here to be stable from side=21 through
side=1601 (monotonically decreasing toward ~0.874, never approaching
0.785 at any size). `test_square_circularity_pin` below pins the
VERIFIED value instead of the plan's claimed value so it still catches
a real regression (e.g. reverting to the raw unweighted polygonal
perimeter, which lands far outside this window too).
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.shape_metrics import (
    ClassThresholds,
    classify_shapes,
    shape_descriptors,
)

pytestmark = [pytest.mark.imaging]


def _disk(radius: int) -> np.ndarray:
    pad = 5
    yy, xx = np.mgrid[-radius - pad : radius + pad + 1, -radius - pad : radius + pad + 1]
    return ((xx**2 + yy**2) <= radius**2).astype(np.int64)


def _square(side: int) -> np.ndarray:
    return np.ones((side, side), dtype=np.int64)


def _rotated_rod(
    shape: tuple[int, int], center: tuple[float, float],
    a: float, b: float, theta: float,
) -> np.ndarray:
    """Filled ellipse (semi-axes a >= b) whose major axis sits at angle
    `theta` from the row axis, matching skimage's orientation convention
    by construction (verified empirically against regionprops_table)."""
    rr, cc = np.mgrid[0 : shape[0], 0 : shape[1]].astype(np.float64)
    dr = rr - center[0]
    dc = cc - center[1]
    u = dr * np.cos(theta) + dc * np.sin(theta)
    v = -dr * np.sin(theta) + dc * np.cos(theta)
    return ((u / a) ** 2 + (v / b) ** 2 <= 1.0).astype(np.int64)


# ── mandatory Convention #2 pins ────────────────────────────────────────


def test_disk_circularity_pin() -> None:
    """Large synthetic disk -> circularity ~= 1 within a few % (mandatory
    pin; catches a regression to the naive polygonal-perimeter trap,
    which yields ~0.79-0.9 for a disk depending on the naive definition
    used, never within a couple percent of 1)."""
    d = shape_descriptors(_disk(radius=100))
    assert d.circularity[0] == pytest.approx(1.0, rel=0.02)


def test_square_circularity_pin() -> None:
    """Filled square -> stable, verified crofton-circularity (~0.874-0.876
    across a wide size range) -- see the module docstring for why this is
    NOT the pi/4 the plan's Convention #2 claims, and why pinning the
    verified value still catches a real regression."""
    d = shape_descriptors(_square(side=301))
    assert d.circularity[0] == pytest.approx(0.8755, abs=0.01)
    # explicitly NOT pi/4 under the mandated crofton estimator -- guards
    # against someone "fixing" this test back to the plan's unreachable
    # claim without re-deriving the perimeter source.
    assert d.circularity[0] != pytest.approx(np.pi / 4, abs=0.02)


def test_square_circularity_stable_across_size() -> None:
    """The square pin isn't a fluke of one size — same ballpark from a
    modest square up through a very large one."""
    for side in (61, 101, 201, 401, 801):
        d = shape_descriptors(_square(side))
        assert 0.86 < d.circularity[0] < 0.90, (side, d.circularity[0])


# ── orientation + aspect ratio ──────────────────────────────────────────


@pytest.mark.parametrize(
    "theta_deg", [0.0, 22.9, -40.0, 60.0, -75.0, 89.0]
)
def test_rod_orientation_matches_construction(theta_deg: float) -> None:
    theta = np.deg2rad(theta_deg)
    lab = _rotated_rod((220, 220), (110.0, 110.0), a=70.0, b=8.0, theta=theta)
    d = shape_descriptors(lab)
    assert d.orientation_rad[0] == pytest.approx(theta, abs=np.deg2rad(1.0))
    # skimage convention range
    assert -np.pi / 2 < d.orientation_rad[0] <= np.pi / 2 + 1e-9
    assert d.aspect_ratio[0] == pytest.approx(70.0 / 8.0, rel=0.05)


def test_axis_aligned_rod_orientation_row_vs_col() -> None:
    # long along columns (row axis is the SHORT one) -> perpendicular to
    # the row axis -> orientation pi/2
    horizontal = np.zeros((101, 101), dtype=np.int64)
    horizontal[48:53, 10:91] = 1
    dh = shape_descriptors(horizontal)
    assert dh.orientation_rad[0] == pytest.approx(np.pi / 2, abs=1e-6)

    # long along rows -> aligned WITH the row axis -> orientation 0
    vertical = np.zeros((101, 101), dtype=np.int64)
    vertical[10:91, 48:53] = 1
    dv = shape_descriptors(vertical)
    assert dv.orientation_rad[0] == pytest.approx(0.0, abs=1e-6)

    # same construction (just transposed) -> identical aspect ratio
    assert dh.aspect_ratio[0] == pytest.approx(dv.aspect_ratio[0], rel=1e-9)


# ── degenerate cases ─────────────────────────────────────────────────


def test_single_pixel_aspect_ratio_is_nan() -> None:
    """Degenerate minor axis (single-pixel region) -> NaN, never
    Infinity/huge — the wire layer maps this to `null` (Convention #4)."""
    lab = np.zeros((10, 10), dtype=np.int64)
    lab[5, 5] = 1
    d = shape_descriptors(lab)
    assert np.isnan(d.aspect_ratio[0])
    assert np.isfinite(d.circularity[0])
    assert np.isfinite(d.orientation_rad[0])
    assert np.isfinite(d.solidity[0])


def test_shape_descriptors_empty_labels() -> None:
    d = shape_descriptors(np.zeros((5, 5), dtype=np.int64))
    assert d.circularity.shape == (0,)
    assert d.aspect_ratio.shape == (0,)


def test_shape_descriptors_row_order_matches_label_order() -> None:
    """Multiple regions: rows come back ascending-by-label, positionally
    aligned with a paired RegionStats list (same guarantee grain_stats
    relies on)."""
    lab = np.zeros((30, 60), dtype=np.int64)
    lab[2:8, 2:8] = 1          # small square, label 1
    lab[2:28, 30:38] = 2        # tall rod, label 2
    d = shape_descriptors(lab)
    assert d.aspect_ratio.shape == (2,)
    # label 2 (tall rod) has a much larger aspect ratio than label 1
    assert d.aspect_ratio[1] > d.aspect_ratio[0]


# ── classify_shapes: boundary edges + precedence ───────────────────────

DEFAULTS = ClassThresholds()


def _classify_one(aspect: float, circ: float, solidity: float) -> str:
    return classify_shapes(
        np.array([aspect]), np.array([circ]), np.array([solidity])
    )[0]


def test_aggregate_solidity_boundary() -> None:
    # just below 0.85 -> aggregate, regardless of otherwise sphere-like values
    assert _classify_one(1.0, 0.99, 0.849999) == "aggregate"
    # exactly 0.85 -> NOT aggregate (strict <); falls through to sphere-like
    assert _classify_one(1.0, 0.99, 0.85) == "sphere-like"
    # just above 0.85 -> not aggregate
    assert _classify_one(1.0, 0.99, 0.850001) != "aggregate"


def test_rod_aspect_boundary() -> None:
    # just below 2.5 -> not rod (and not sphere since aspect isn't < 1.3)
    assert _classify_one(2.499999, 0.5, 0.95) == "intermediate"
    # exactly 2.5 -> rod (inclusive)
    assert _classify_one(2.5, 0.5, 0.95) == "rod-like"
    # just above -> rod
    assert _classify_one(2.500001, 0.5, 0.95) == "rod-like"


def test_sphere_aspect_boundary() -> None:
    # just below 1.3 with high circularity -> sphere
    assert _classify_one(1.299999, 0.9, 0.95) == "sphere-like"
    # exactly 1.3 -> NOT sphere (strict <)
    assert _classify_one(1.3, 0.9, 0.95) == "intermediate"
    # just above -> not sphere
    assert _classify_one(1.300001, 0.9, 0.95) == "intermediate"


def test_sphere_circularity_boundary() -> None:
    # just below 0.85 -> not sphere
    assert _classify_one(1.0, 0.849999, 0.95) == "intermediate"
    # exactly 0.85 -> NOT sphere (strict >)
    assert _classify_one(1.0, 0.85, 0.95) == "intermediate"
    # just above -> sphere
    assert _classify_one(1.0, 0.850001, 0.95) == "sphere-like"


def test_aggregate_trumps_rod_and_sphere_precedence() -> None:
    """Aggregate is checked FIRST — a low-solidity region that would
    otherwise qualify as rod-like or sphere-like is still aggregate."""
    assert _classify_one(aspect=5.0, circ=0.5, solidity=0.5) == "aggregate"
    assert _classify_one(aspect=1.0, circ=0.95, solidity=0.5) == "aggregate"


def test_null_aspect_ratio_falls_to_intermediate_unless_aggregate() -> None:
    assert _classify_one(aspect=float("nan"), circ=0.9, solidity=0.95) == (
        "intermediate"
    )
    assert _classify_one(aspect=float("nan"), circ=0.9, solidity=0.5) == (
        "aggregate"
    )


def test_classify_shapes_vectorized_matches_scalar_calls() -> None:
    aspect = np.array([5.0, 1.0, np.nan, 1.0, 2.5, 1.3])
    circ = np.array([0.5, 0.9, 0.9, 0.5, 0.6, 0.9])
    solidity = np.array([0.9, 0.9, 0.9, 0.5, 0.9, 0.9])
    got = classify_shapes(aspect, circ, solidity)
    expected = [
        _classify_one(a, c, s) for a, c, s in zip(aspect, circ, solidity, strict=True)
    ]
    assert got == expected
    assert got == [
        "rod-like", "sphere-like", "intermediate", "aggregate", "rod-like",
        "intermediate",
    ]


def test_classify_shapes_custom_thresholds_are_honoured() -> None:
    loose = ClassThresholds(
        aggregate_max_solidity=0.5, rod_min_aspect=10.0,
        sphere_max_aspect=5.0, sphere_min_circularity=0.5,
    )
    # a value that is "rod-like" under defaults becomes "sphere-like"
    # under loosened sphere thresholds (aspect 3.0 < sphere_max_aspect=5.0)
    assert _classify_one(3.0, 0.6, 0.9) == "rod-like"  # sanity under defaults
    assert classify_shapes(
        np.array([3.0]), np.array([0.6]), np.array([0.9]), loose,
    )[0] == "sphere-like"
    # a solidity that used to trigger aggregate no longer does
    assert classify_shapes(
        np.array([1.0]), np.array([0.9]), np.array([0.6]), loose,
    )[0] == "sphere-like"


def test_default_thresholds_match_frozen_contract() -> None:
    assert DEFAULTS.aggregate_max_solidity == 0.85
    assert DEFAULTS.rod_min_aspect == 2.5
    assert DEFAULTS.sphere_max_aspect == 1.3
    assert DEFAULTS.sphere_min_circularity == 0.85
