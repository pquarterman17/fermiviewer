"""Pure-math tests for DPC / charge-density (calc/fourd/dpc.py, PLAN_4DSTEM #8).

Two kinds of check, per the task brief: an analytic UNIFORM field (constant
COM shift -> constant magnitude/direction, and EXACTLY zero divergence —
Gauss's law for a field with no sources in view), and an analytic
non-uniform (linear/"radial", point-charge-like) field with a KNOWN
non-zero divergence, so the charge-density path is actually exercised and
not just its null case.

No corpus, no server: hand-checkable synthetic arrays only.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from fermiviewer.calc.fourd.dpc import (
    calibrated_field_mrad,
    divergence_map,
    dpc_direction,
    dpc_magnitude,
    dpc_maps,
)

# ════════════════════════════════════════════════════════════════════
# calibrated_field_mrad
# ════════════════════════════════════════════════════════════════════


def test_calibrated_field_mrad_scales_com_shift_by_calibration() -> None:
    com_y = np.array([[1.0, -2.0], [3.0, 0.0]])
    com_x = np.array([[0.5, 4.0], [-1.0, 2.0]])
    field_y, field_x = calibrated_field_mrad(com_y, com_x, mrad_per_px=2.5)
    np.testing.assert_allclose(field_y, com_y * 2.5)
    np.testing.assert_allclose(field_x, com_x * 2.5)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), -0.001])
def test_calibrated_field_mrad_rejects_non_positive_or_nonfinite(bad: float) -> None:
    com_y = np.zeros((2, 2))
    com_x = np.zeros((2, 2))
    with pytest.raises(ValueError, match="mrad_per_px"):
        calibrated_field_mrad(com_y, com_x, mrad_per_px=bad)


# ════════════════════════════════════════════════════════════════════
# dpc_magnitude / dpc_direction
# ════════════════════════════════════════════════════════════════════


def test_dpc_magnitude_matches_hypot() -> None:
    field_y = np.array([3.0, 6.0, 0.0])
    field_x = np.array([4.0, 8.0, -5.0])
    magnitude = dpc_magnitude(field_y, field_x)
    np.testing.assert_allclose(magnitude, [5.0, 10.0, 5.0])


@pytest.mark.parametrize(
    "field_y,field_x,expected_rad",
    [
        (0.0, 1.0, 0.0),
        (1.0, 0.0, math.pi / 2),
        (0.0, -1.0, math.pi),
        (-1.0, 0.0, -math.pi / 2),
    ],
)
def test_dpc_direction_matches_atan2_ky_kx_convention(
    field_y: float, field_x: float, expected_rad: float
) -> None:
    direction = dpc_direction(np.array([field_y]), np.array([field_x]))
    assert direction[0] == pytest.approx(expected_rad)


def test_dpc_direction_is_invariant_under_isotropic_calibration() -> None:
    """The angle of a vector is unchanged by scaling both components by the
    SAME positive factor — direction computed from raw COM pixels must
    equal direction computed from the mrad-calibrated field."""
    com_y = np.array([[3.0, -1.0], [0.0, 5.0]])
    com_x = np.array([[-4.0, 2.0], [1.0, -5.0]])
    raw_direction = dpc_direction(com_y, com_x)
    field_y, field_x = calibrated_field_mrad(com_y, com_x, mrad_per_px=7.25)
    calibrated_direction = dpc_direction(field_y, field_x)
    np.testing.assert_allclose(calibrated_direction, raw_direction)


# ════════════════════════════════════════════════════════════════════
# divergence_map / dpc_maps — uniform field (null case)
# ════════════════════════════════════════════════════════════════════


def _uniform_com_maps(
    shape: tuple[int, int], dy: float, dx: float
) -> tuple[np.ndarray, np.ndarray]:
    return np.full(shape, dy), np.full(shape, dx)


def test_uniform_com_field_gives_constant_magnitude_and_direction() -> None:
    """A uniform E-field produces a CONSTANT COM shift everywhere — the
    calibrated magnitude and direction must therefore be constant too."""
    shape = (4, 5)
    dy, dx = 3.0, -2.0
    com_y, com_x = _uniform_com_maps(shape, dy, dx)
    maps = dpc_maps(com_y, com_x, mrad_per_px=2.0)

    expected_mag = math.hypot(dy, dx) * 2.0
    expected_dir = math.atan2(dy, dx)
    np.testing.assert_allclose(maps.magnitude_mrad, expected_mag)
    np.testing.assert_allclose(maps.direction_rad, expected_dir)


def test_uniform_com_field_has_exactly_zero_divergence() -> None:
    shape = (4, 5)
    com_y, com_x = _uniform_com_maps(shape, 3.0, -2.0)
    maps = dpc_maps(com_y, com_x, mrad_per_px=2.0)
    np.testing.assert_allclose(maps.divergence, 0.0, atol=1e-12)


def test_divergence_map_of_uniform_field_is_zero_directly() -> None:
    """Same check calling `divergence_map` directly (not through `dpc_maps`),
    so a bug isolated to `dpc_maps`'s own wiring can't hide a divergence_map
    bug or vice versa."""
    field_y = np.full((3, 3), 5.0)
    field_x = np.full((3, 3), -1.5)
    div = divergence_map(field_y, field_x)
    np.testing.assert_allclose(div, 0.0, atol=1e-12)


# ════════════════════════════════════════════════════════════════════
# divergence_map / dpc_maps — linear ("radial", point-charge-like) field,
# KNOWN non-zero divergence
# ════════════════════════════════════════════════════════════════════


def test_radial_field_has_known_constant_nonzero_divergence() -> None:
    """F = (y - cy0, x - cx0): the field of a uniform point/line source
    seen through Gauss's law. Analytically div(F) = dy/dy + dx/dx = 1 + 1
    = 2 EVERYWHERE (a linear field has zero curvature, so both the central
    interior differences and the one-sided boundary differences numpy.
    gradient uses are exact — no boundary artifacts to tolerate)."""
    ny, nx = 6, 7
    cy0, cx0 = 2.5, -1.0
    ys = np.arange(ny, dtype=np.float64)[:, None]
    xs = np.arange(nx, dtype=np.float64)[None, :]
    field_y = np.broadcast_to(ys - cy0, (ny, nx)).copy()
    field_x = np.broadcast_to(xs - cx0, (ny, nx)).copy()
    div = divergence_map(field_y, field_x)
    np.testing.assert_allclose(div, 2.0)


def test_radial_com_field_gives_known_scaled_divergence_through_dpc_maps() -> None:
    """Same radial construction, but fed through `dpc_maps` as a COM
    (pixel) field with an explicit calibration — divergence must scale
    linearly with `mrad_per_px` (2 * mrad_per_px), exercising the actual
    charge-density path end-to-end, not just `divergence_map` alone."""
    ny, nx = 5, 6
    cy0, cx0 = 1.0, 2.0
    ys = np.arange(ny, dtype=np.float64)[:, None]
    xs = np.arange(nx, dtype=np.float64)[None, :]
    com_y = np.broadcast_to(ys - cy0, (ny, nx)).copy()
    com_x = np.broadcast_to(xs - cx0, (ny, nx)).copy()
    maps = dpc_maps(com_y, com_x, mrad_per_px=3.0)
    np.testing.assert_allclose(maps.divergence, 2.0 * 3.0)
    # and it is genuinely non-zero, not a degenerate near-zero pass
    assert np.all(np.abs(maps.divergence) > 1.0)


# ════════════════════════════════════════════════════════════════════
# validation
# ════════════════════════════════════════════════════════════════════


def test_divergence_map_rejects_shape_mismatch() -> None:
    field_y = np.zeros((3, 3))
    field_x = np.zeros((3, 4))
    with pytest.raises(ValueError, match="shape mismatch"):
        divergence_map(field_y, field_x)


@pytest.mark.parametrize("shape", [(1, 5), (5, 1), (1, 1)])
def test_divergence_map_rejects_scan_shape_too_small(shape: tuple[int, int]) -> None:
    field_y = np.zeros(shape)
    field_x = np.zeros(shape)
    with pytest.raises(ValueError, match="at least 2 scan positions"):
        divergence_map(field_y, field_x)


def test_dpc_maps_propagates_invalid_calibration() -> None:
    com_y = np.zeros((3, 3))
    com_x = np.zeros((3, 3))
    with pytest.raises(ValueError, match="mrad_per_px"):
        dpc_maps(com_y, com_x, mrad_per_px=0.0)
