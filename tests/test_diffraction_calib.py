"""Diffraction calibration (Diffraction #1): ellipse fit, radius un-distortion,
camera constant. Physics-reference values (no MATLAB golden exists for this)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.diffraction_calib import (
    EllipseFit,
    beam_center,
    camera_constant,
    detect_ring_points,
    fit_ellipse,
    undistort_radii,
)

pytestmark = pytest.mark.diffraction


def _ring_points(cy, cx, a, b, theta, n=120):
    """n points on an ellipse, returned as (row, col)."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ex = a * np.cos(t)
    ey = b * np.sin(t)
    ct, st = np.cos(theta), np.sin(theta)
    x = cx + ct * ex - st * ey
    y = cy + st * ex + ct * ey
    return np.column_stack([y, x])  # (row, col)


def test_fits_a_perfect_circle_as_zero_eccentricity() -> None:
    pts = _ring_points(257, 257, 80.0, 80.0, 0.0)
    fit = fit_ellipse(pts)
    assert fit.eccentricity < 1e-3
    assert fit.center_row == pytest.approx(257, abs=1e-3)
    assert fit.center_col == pytest.approx(257, abs=1e-3)
    assert fit.mean_radius == pytest.approx(80.0, rel=1e-4)


def test_recovers_a_known_affine_stretch() -> None:
    a, b, theta = 100.0, 95.0, np.deg2rad(20.0)
    pts = _ring_points(300, 320, a, b, theta)
    fit = fit_ellipse(pts)
    assert fit.a == pytest.approx(a, rel=1e-3)
    assert fit.b == pytest.approx(b, rel=1e-3)
    assert fit.center_row == pytest.approx(300, abs=1e-2)
    assert fit.center_col == pytest.approx(320, abs=1e-2)
    # angle modulo π (major axis is undirected)
    assert (fit.theta - theta) % np.pi == pytest.approx(0.0, abs=1e-2) or (
        theta - fit.theta
    ) % np.pi == pytest.approx(0.0, abs=1e-2)


def test_undistort_collapses_an_ellipse_to_its_mean_radius() -> None:
    a, b, theta = 100.0, 90.0, np.deg2rad(35.0)
    pts = _ring_points(256, 256, a, b, theta)
    fit = fit_ellipse(pts)
    corrected = undistort_radii(pts, fit)
    # every point now sits at (nearly) the same circular radius
    assert np.allclose(corrected, fit.mean_radius, rtol=1e-2)
    assert np.std(corrected) < 0.5  # was a/b spread before


def test_camera_constant_and_inverse_d() -> None:
    # a standard ring of d=2.338 Å fit to radius 80 px → C = 187.04 px·Å
    c = camera_constant(2.338, 80.0)
    assert c == pytest.approx(2.338 * 80.0)
    # another ring at 120 px → d = C/120
    assert c / 120.0 == pytest.approx(2.338 * 80.0 / 120.0)
    assert np.isnan(camera_constant(0.0, 80.0))  # invalid d


def test_beam_center_matches_index_convention() -> None:
    assert beam_center((512, 512)) == (257, 257)  # floor(512/2)+1
    assert beam_center((511, 513)) == (256, 257)


def test_detect_ring_points_finds_a_synthetic_circle() -> None:
    # a bright annulus at radius ~40 around the image centre
    n = 129
    yy, xx = np.ogrid[:n, :n]
    cy = cx = n // 2
    r = np.hypot(yy - cy, xx - cx)
    img = np.exp(-((r - 40.0) ** 2) / (2 * 3.0**2))  # gaussian ring
    pts = detect_ring_points(img, r_min=10, r_max=60, n_angles=72)
    assert len(pts) > 50
    fit = fit_ellipse(pts)
    assert fit.mean_radius == pytest.approx(40.0, abs=1.5)
    assert fit.eccentricity < 0.1


def test_fit_requires_enough_points() -> None:
    with pytest.raises(ValueError, match="≥5"):
        fit_ellipse(np.zeros((3, 2)))


def test_radius_at_is_axis_consistent() -> None:
    fit = EllipseFit(0.0, 0.0, 100.0, 50.0, 0.0)
    # along the major axis (theta=0 → angle 0) radius = a; along +90° = b
    assert float(fit.radius_at(0.0)) == pytest.approx(100.0)
    assert float(fit.radius_at(np.pi / 2)) == pytest.approx(50.0)
