"""Pure-math tests for the center-of-mass resolution policy
(calc/fourd/com.py, PLAN_4DSTEM #7).

`com_shift_maps` (calc/fourd/virtual.py) already owns the actual
first-moment centroid computation and has its own pure tests in
test_fourd_geometry.py — these tests exercise ONLY com.py's own job: the
caller-supplied-vs-auto center resolution policy, and that it correctly
carries `com_shift_maps`'s documented degenerate case (zero/non-positive
total intensity -> 0 shift) through the delegation.

No corpus, no server: hand-checkable synthetic grids/cubes only.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.fourd.com import com_maps

_DET = 21  # odd so a centered disk has an exact integer-coordinate center
_CENTER = (10.0, 10.0)


def _shifted_disk(dy: float, dx: float) -> np.ndarray:
    ky = np.arange(_DET, dtype=np.float64)[:, None]
    kx = np.arange(_DET, dtype=np.float64)[None, :]
    dist = np.hypot(ky - (_CENTER[0] + dy), kx - (_CENTER[1] + dx))
    return (dist <= 2.0).astype(np.float64)


_SHIFTS = [(0.0, 0.0), (2.0, -1.0), (-3.0, 4.0)]


def _shifted_disk_cube() -> np.ndarray:
    """scan_shape (3, 1): one shifted disk per scan row."""
    return np.stack([_shifted_disk(dy, dx) for dy, dx in _SHIFTS])[:, None, :, :]


def _symmetric_mean_pattern() -> np.ndarray:
    """A disk centered EXACTLY at `_CENTER` — pattern_center resolves it to
    `_CENTER` exactly, so the auto-center path is checkable against the
    same expected shifts as the explicit-center path."""
    return _shifted_disk(0.0, 0.0)


# ════════════════════════════════════════════════════════════════════
# known-shift tracking
# ════════════════════════════════════════════════════════════════════


def test_com_maps_tracks_known_shift_with_explicit_center() -> None:
    cube = _shifted_disk_cube()
    com_y, com_x = com_maps([(0, cube)], center=_CENTER)
    for i, (dy, dx) in enumerate(_SHIFTS):
        assert com_y[i, 0] == pytest.approx(dy, abs=0.05)
        assert com_x[i, 0] == pytest.approx(dx, abs=0.05)


def test_com_maps_auto_center_matches_explicit_center() -> None:
    """center=None, seeded from a mean_pattern whose true centroid is
    exactly `_CENTER`, must reproduce the same shifts as passing `_CENTER`
    explicitly — proving the auto-seed actually reaches `com_shift_maps`."""
    cube = _shifted_disk_cube()
    mean_pattern = _symmetric_mean_pattern()
    auto_y, auto_x = com_maps([(0, cube)], center=None, mean_pattern=mean_pattern)
    manual_y, manual_x = com_maps([(0, cube)], center=_CENTER)
    np.testing.assert_array_equal(auto_y, manual_y)
    np.testing.assert_array_equal(auto_x, manual_x)
    for i, (dy, dx) in enumerate(_SHIFTS):
        assert auto_y[i, 0] == pytest.approx(dy, abs=0.05)
        assert auto_x[i, 0] == pytest.approx(dx, abs=0.05)


def test_com_maps_explicit_center_overrides_auto() -> None:
    """A caller-supplied center wins outright, even when a mean_pattern
    that would auto-seed a DIFFERENT center is also passed in."""
    cube = _shifted_disk_cube()
    off_center_mean = _shifted_disk(5.0, -5.0)  # pattern_center != _CENTER
    with_explicit, _ = com_maps(
        [(0, cube)], center=_CENTER, mean_pattern=off_center_mean
    )
    would_be_auto, _ = com_maps([(0, cube)], center=None, mean_pattern=off_center_mean)
    # the explicit-center result must match the known shifts (i.e. ignore
    # the misleading mean_pattern), and must differ from what auto-center
    # would have produced from that same mean_pattern.
    for i, (dy, _dx) in enumerate(_SHIFTS):
        assert with_explicit[i, 0] == pytest.approx(dy, abs=0.05)
    assert not np.allclose(with_explicit, would_be_auto)


def test_com_maps_requires_mean_pattern_when_center_is_none() -> None:
    cube = _shifted_disk_cube()
    with pytest.raises(ValueError, match="center is None"):
        com_maps([(0, cube)], center=None, mean_pattern=None)


# ════════════════════════════════════════════════════════════════════
# degenerate intensity (com_shift_maps's documented 0-shift contract),
# exercised through com.py's own delegation
# ════════════════════════════════════════════════════════════════════


def test_com_maps_zero_intensity_returns_zero_shift_explicit_center() -> None:
    cube = np.zeros((1, 1, 5, 5))
    com_y, com_x = com_maps([(0, cube)], center=(2.0, 2.0))
    assert com_y[0, 0] == 0.0
    assert com_x[0, 0] == 0.0


def test_com_maps_zero_intensity_returns_zero_shift_auto_center() -> None:
    """All-zero patterns AND an all-zero mean_pattern: pattern_center falls
    back to the detector's geometric center, and com_shift_maps still
    reports 0 shift for the zero-intensity pattern regardless."""
    cube = np.zeros((1, 1, 5, 5))
    mean_pattern = np.zeros((5, 5))
    com_y, com_x = com_maps([(0, cube)], center=None, mean_pattern=mean_pattern)
    assert com_y[0, 0] == 0.0
    assert com_x[0, 0] == 0.0


def test_com_maps_non_positive_intensity_returns_zero_shift() -> None:
    """A uniformly NEGATIVE pattern has non-positive total intensity —
    `com_shift_maps` documents this as a 0-shift case too (not just exact
    zero), and that must survive com.py's delegation unchanged."""
    cube = np.full((1, 1, 5, 5), -3.0)
    com_y, com_x = com_maps([(0, cube)], center=(2.0, 2.0))
    assert com_y[0, 0] == 0.0
    assert com_x[0, 0] == 0.0
