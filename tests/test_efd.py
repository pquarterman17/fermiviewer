"""calc/efd.py -- elliptic Fourier shape descriptors (SHAPE_ANALYSIS_PLAN
Tier-2 item #4).

The invariances ARE the point of this module, so this file proves them
directly against synthetic point rings (exact, analytic scale/rotation/
start-point transforms) rather than relying only on the noisier round
trip through rasterize -> trace -> descriptor -- one test at the end does
that full pipeline too, to prove `calc/contours.py` output is actually
compatible.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.contours import trace_outer_contour
from fermiviewer.calc.efd import (
    DEFAULT_N_HARMONICS,
    efd_coefficients,
    efd_descriptor,
    efd_distance,
    normalize_coefficients,
)

pytestmark = pytest.mark.imaging


# ── synthetic ring generators (row, col) ────────────────────────────


def _circle_ring(cy: float, cx: float, r: float, n: int = 100) -> np.ndarray:
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.column_stack([cy + r * np.sin(t), cx + r * np.cos(t)])


def _rect_ring(cy: float, cx: float, w: float, h: float, n: int = 100) -> np.ndarray:
    """An n-point ring roughly evenly spaced around a w x h rectangle
    (elongated when w >> h), centered at (cy, cx), as (row, col)."""
    edges = [(w, 0.0), (0.0, h), (-w, 0.0), (0.0, -h)]
    perim = 2.0 * (w + h)
    pts = [(cy - h / 2.0, cx - w / 2.0)]
    y, x = cy - h / 2.0, cx - w / 2.0
    for dx, dy in edges:
        length = float(np.hypot(dx, dy))
        n_seg = max(1, round(n * length / perim))
        for i in range(1, n_seg + 1):
            pts.append((y + dy * i / n_seg, x + dx * i / n_seg))
        y, x = y + dy, x + dx
    return np.asarray(pts[:-1], dtype=np.float64)


def _rotate(points_rc: np.ndarray, angle: float) -> np.ndarray:
    y, x = points_rc[:, 0], points_rc[:, 1]
    c, s = np.cos(angle), np.sin(angle)
    return np.column_stack([s * x + c * y, c * x - s * y])


def _shift_start(points_rc: np.ndarray, k: int) -> np.ndarray:
    return np.roll(points_rc, -k, axis=0)


# ── invariances ──────────────────────────────────────────────────────


def test_default_harmonic_count_is_ten_and_overridable() -> None:
    """The default is a visible module constant (never a hidden magic
    number) and every call site can override it."""
    assert DEFAULT_N_HARMONICS == 10
    ring = _rect_ring(50, 50, 40, 10, n=100)
    d5 = efd_descriptor(ring, n_harmonics=5)
    d10 = efd_descriptor(ring, n_harmonics=DEFAULT_N_HARMONICS)
    assert d5.n_harmonics == 5
    assert d10.n_harmonics == DEFAULT_N_HARMONICS
    assert d5.coeffs.shape == (5, 4)
    assert d10.coeffs.shape == (10, 4)


def test_scale_invariance() -> None:
    base = _rect_ring(0, 0, 40, 10)
    d0 = efd_descriptor(base)
    scaled = efd_descriptor(base * 3.7)
    assert efd_distance(d0, scaled) < 1e-8


def test_rotation_invariance() -> None:
    base = _rect_ring(0, 0, 40, 10)
    d0 = efd_descriptor(base)
    rotated = efd_descriptor(_rotate(base, 1.234))
    assert efd_distance(d0, rotated) < 1e-8


def test_starting_point_invariance() -> None:
    """Different tracing start vertex on the SAME ring -- including a
    start near the opposite end of the shape's major axis, where the
    theta_1 two-fold ambiguity (module docstring) would show up if it
    were not already resolved by construction."""
    base = _rect_ring(0, 0, 40, 10, n=100)
    d0 = efd_descriptor(base)
    for k in (1, 17, 40, 50, 73, 99):  # 50 is ~half the ring: opposite end
        shifted = efd_descriptor(_shift_start(base, k))
        assert efd_distance(d0, shifted) < 1e-8, f"start shift k={k}"


def test_combined_scale_rotation_start_invariance() -> None:
    base = _rect_ring(0, 0, 40, 10, n=100)
    d0 = efd_descriptor(base)
    transformed = _rotate(_shift_start(base, 33), 0.7) * 2.2
    d1 = efd_descriptor(transformed)
    assert efd_distance(d0, d1) < 1e-8


def test_circle_is_invariant_too() -> None:
    """A circle's first-harmonic ellipse is degenerate (a=b), the
    trickiest case for the theta_1/psi_1 normalization -- pin it
    separately from the rectangle cases above."""
    base = _circle_ring(0, 0, 5.0, n=100)
    d0 = efd_descriptor(base)
    for transform in (
        lambda p: p * 1.5,
        lambda p: _rotate(p, 0.9),
        lambda p: _shift_start(p, 23),
        lambda p: _rotate(_shift_start(p, 47), -1.1) * 0.6,
    ):
        d1 = efd_descriptor(transform(base))
        assert efd_distance(d0, d1) < 1e-6


# ── discrimination ───────────────────────────────────────────────────


def test_circle_vs_elongated_rectangle_is_clearly_nonzero() -> None:
    circ = efd_descriptor(_circle_ring(0, 0, 5.0))
    rect = efd_descriptor(_rect_ring(0, 0, 40, 4))
    assert efd_distance(circ, rect) > 0.3


def test_self_is_most_similar_among_distractors() -> None:
    """A shape must rank most similar to a (scaled/rotated/start-shifted)
    copy of itself among a set of visually different distractors."""
    target = _rect_ring(0, 0, 30, 8, n=100)
    target_copy = _rotate(_shift_start(target, 41), 2.0) * 1.8

    distractors = {
        "circle": _circle_ring(0, 0, 6.0, n=100),
        "square": _rect_ring(0, 0, 15, 15, n=100),
        "thin_rod": _rect_ring(0, 0, 60, 3, n=100),
        "wide_rect": _rect_ring(0, 0, 12, 45, n=100),
    }

    ref = efd_descriptor(target)
    distances = {"self_copy": efd_distance(ref, efd_descriptor(target_copy))}
    for name, ring in distractors.items():
        distances[name] = efd_distance(ref, efd_descriptor(ring))

    best = min(distances, key=lambda k: distances[k])
    assert best == "self_copy", distances


# ── error handling ───────────────────────────────────────────────────


def test_too_few_points_for_harmonic_count_raises() -> None:
    triangle = np.array([[0.0, 0.0], [0.0, 10.0], [10.0, 5.0]])
    with pytest.raises(ValueError, match="need >="):
        efd_coefficients(triangle, n_harmonics=10)
    # but the SAME ring is fine at a harmonic count it can support
    efd_coefficients(triangle, n_harmonics=1)


def test_distance_requires_matching_harmonic_counts() -> None:
    ring = _circle_ring(0, 0, 5.0)
    d5 = efd_descriptor(ring, n_harmonics=5)
    d10 = efd_descriptor(ring, n_harmonics=10)
    with pytest.raises(ValueError, match="n_harmonics"):
        efd_distance(d5, d10)


def test_malformed_points_ndim_raises() -> None:
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        efd_coefficients(np.array([1.0, 2.0, 3.0]), n_harmonics=1)


def test_malformed_points_wrong_column_count_raises() -> None:
    """(N, 3) is not (N, 2) -- without this explicit check the extra
    column is silently ignored downstream rather than rejected (a wrong
    answer, not a crash), so this pins the check itself rather than
    relying on some unrelated numpy error to happen to fire."""
    with pytest.raises(ValueError, match=r"\(N, 2\)"):
        efd_coefficients(np.zeros((10, 3)), n_harmonics=1)


def test_normalize_rejects_wrong_shape() -> None:
    with pytest.raises(ValueError, match=r"\(n_harmonics, 4\)"):
        normalize_coefficients(np.zeros((3, 3)))


# ── real contour-tracing pipeline compatibility ─────────────────────


def test_compatible_with_traced_contour_output() -> None:
    """`calc/contours.py`'s actual output -- rasterize a disk at two
    different positions/sizes, trace both, and check the descriptors
    still land close together despite the discretization + Douglas-
    Peucker simplification each tracing goes through independently."""

    def _disk_mask(shape, cy, cx, r):
        yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
        return (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r

    mask_a = _disk_mask((120, 120), 60, 60, 35)
    mask_b = _disk_mask((160, 160), 80, 90, 50)  # different center + radius

    contour_a = trace_outer_contour(mask_a, tolerance=0.5, max_vertices=200)
    contour_b = trace_outer_contour(mask_b, tolerance=0.5, max_vertices=200)

    da = efd_descriptor(contour_a.points, n_harmonics=10)
    db = efd_descriptor(contour_b.points, n_harmonics=10)
    assert efd_distance(da, db) < 0.05

    # and a clearly different shape (elongated) should be much farther
    rod_pts = _rect_ring(60, 60, 90, 12, n=120)
    d_rod = efd_descriptor(rod_pts, n_harmonics=10)
    assert efd_distance(da, d_rod) > 0.2
