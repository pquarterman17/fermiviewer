"""calc/shape_fit.py -- direct least-squares circle/ellipse fits
(SHAPE_ANALYSIS_PLAN Tier-2 item #5).

Ellipse geometry is reused from `calc/diffraction_calib.py` (already
pin-tested there: see test_diffraction_calib.py); this file's ellipse
tests focus on the wrapper's own contract -- the RMS residual and the
(cy, cx, a, b, theta_rad) field mapping -- not re-proving the underlying
conic-fit math.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.shape_fit import CircleFit, EllipseFitResult, fit_circle, fit_ellipse

pytestmark = pytest.mark.imaging


def _circle_points(cy, cx, r, n=200):
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.column_stack([cy + r * np.sin(t), cx + r * np.cos(t)])


def _ellipse_points(cy, cx, a, b, theta, n=200):
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    ex, ey = a * np.cos(t), b * np.sin(t)
    ct, st = np.cos(theta), np.sin(theta)
    row = cy + st * ex + ct * ey
    col = cx + ct * ex - st * ey
    return np.column_stack([row, col])


# ── circle fit ───────────────────────────────────────────────────────


def test_circle_fit_recovers_center_and_radius_with_noise() -> None:
    rng = np.random.default_rng(0)
    cy, cx, r = 50.0, 30.0, 12.0
    pts = _circle_points(cy, cx, r, n=300)
    noise_sigma = 0.05
    noisy = pts + rng.normal(scale=noise_sigma, size=pts.shape)

    fit = fit_circle(noisy)
    assert isinstance(fit, CircleFit)
    assert fit.cy == pytest.approx(cy, abs=0.05)
    assert fit.cx == pytest.approx(cx, abs=0.05)
    assert fit.r == pytest.approx(r, abs=0.05)
    # RMS should track the injected noise level, not be wildly off
    assert fit.rms == pytest.approx(noise_sigma, rel=0.5)


def test_circle_fit_exact_points_have_near_zero_rms() -> None:
    pts = _circle_points(10.0, -4.0, 7.0, n=64)
    fit = fit_circle(pts)
    assert fit.rms < 1e-8


def test_circle_fit_needs_at_least_three_points() -> None:
    """Pins the exact message (not just `>= 3`, which the DISTINCT-points
    message below also contains) so this test can't pass merely because
    SOME ValueError fired for an unrelated reason."""
    with pytest.raises(ValueError) as exc_info:
        fit_circle(np.array([[0.0, 0.0], [1.0, 1.0]]))
    assert str(exc_info.value) == "need >= 3 (row, col) points to fit a circle"


def test_circle_fit_rejects_fully_coincident_points() -> None:
    coincident = np.array([[2.0, 2.0], [2.0, 2.0], [2.0, 2.0]])
    with pytest.raises(ValueError, match="DISTINCT"):
        fit_circle(coincident)


def test_circle_fit_rejects_only_two_distinct_locations() -> None:
    two_distinct = np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 1.0]])
    with pytest.raises(ValueError, match="DISTINCT"):
        fit_circle(two_distinct)


def test_circle_fit_on_collinear_points_has_large_rms_not_an_exception() -> None:
    """Collinear (but not coincident) points are algebraically solvable
    (module docstring) -- the poor fit shows up as a large RMS, not a
    raise; a caller that checks `rms` gets the real signal."""
    collinear = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
    fit = fit_circle(collinear)
    assert fit.rms > 0.5


# ── ellipse fit ──────────────────────────────────────────────────────


def test_ellipse_fit_recovers_known_params() -> None:
    cy, cx, a, b, theta = 20.0, 40.0, 15.0, 7.0, 0.4
    pts = _ellipse_points(cy, cx, a, b, theta, n=200)
    fit = fit_ellipse(pts)
    assert isinstance(fit, EllipseFitResult)
    assert fit.cy == pytest.approx(cy, abs=1e-3)
    assert fit.cx == pytest.approx(cx, abs=1e-3)
    assert fit.rms < 1e-6

    # theta/axes are only defined up to the ellipse's own symmetries:
    # (a, b, theta) == (a, b, theta + pi) == (b, a, theta + pi/2). Compare
    # the actual geometry (the set of (semi-axis, axis-angle) pairs) rather
    # than raw field values, so this test doesn't fail on an equivalent
    # parameterization.
    got = sorted([(fit.a, fit.theta_rad % np.pi), (fit.b, (fit.theta_rad + np.pi / 2) % np.pi)])
    want = sorted([(a, theta % np.pi), (b, (theta + np.pi / 2) % np.pi)])
    for (g_axis, g_ang), (w_axis, w_ang) in zip(got, want, strict=True):
        assert g_axis == pytest.approx(w_axis, abs=1e-3)
        angle_diff = min(abs(g_ang - w_ang), np.pi - abs(g_ang - w_ang))
        assert angle_diff == pytest.approx(0.0, abs=1e-3)


def test_ellipse_fit_rms_tracks_noise() -> None:
    rng = np.random.default_rng(1)
    pts = _ellipse_points(0.0, 0.0, 20.0, 9.0, -0.6, n=300)
    noise_sigma = 0.08
    noisy = pts + rng.normal(scale=noise_sigma, size=pts.shape)
    fit = fit_ellipse(noisy)
    assert fit.rms == pytest.approx(noise_sigma, rel=0.6)


def test_ellipse_fit_needs_at_least_five_points() -> None:
    with pytest.raises(ValueError):
        fit_ellipse(np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]))


def test_circle_is_a_valid_degenerate_ellipse_fit() -> None:
    """a == b (theta undefined but must not crash)."""
    pts = _circle_points(5.0, 5.0, 6.0, n=100)
    fit = fit_ellipse(pts)
    assert fit.a == pytest.approx(fit.b, rel=1e-3)
    assert fit.rms < 1e-6
