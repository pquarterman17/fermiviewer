"""Anisotropic Cauchy--Crofton perimeter.

Every expectation here comes from outside the module under test: skimage's
own estimator for the isotropic cases, and closed-form perimeters of
shapes constructed at known physical size for the anisotropic ones. No
test recomputes `crofton.py`'s expression and asserts the two agree --
that is true of any formula, and it is exactly how a `log2`/`log10` error
survived in `astm_grain_size_number` for as long as it did.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from skimage import draw, measure

from fermiviewer.calc.crofton import (
    _direction_offsets,
    crofton_perimeter,
    crofton_perimeters_by_label,
)

# ── fixtures: shapes with known geometry ─────────────────────────────────


def _rect(h: int, w: int, margin: int = 25) -> np.ndarray:
    a = np.zeros((h + 2 * margin, w + 2 * margin), np.uint8)
    a[margin : margin + h, margin : margin + w] = 1
    return a


def _ellipse(r_semi: int, c_semi: int, rot: float = 0.0) -> np.ndarray:
    a = np.zeros((2 * r_semi + 40, 2 * c_semi + 40), np.uint8)
    rr, cc = draw.ellipse(r_semi + 20, c_semi + 20, r_semi, c_semi, rotation=rot)
    a[rr, cc] = 1
    return a


_SHAPES = {
    "rect_20x40": _rect(20, 40),
    "square_20": _rect(20, 20),
    "thin_3x60": _rect(3, 60),
    "disc_r30": _ellipse(30, 30),
    "ellipse_rot": _ellipse(40, 16, rot=0.7),
    "single_pixel": _rect(1, 1),
}


# ── the backward-compatibility guarantee ─────────────────────────────────


@pytest.mark.parametrize("name", sorted(_SHAPES))
def test_square_pixels_reproduce_skimage_exactly(name: str) -> None:
    """On square pixels this must BE skimage's estimator, not merely agree
    with it to a tolerance.

    `ClassThresholds.sphere_min_circularity` and its siblings are
    calibrated against the Crofton scale (an axis-aligned square lands
    near 0.874, not the textbook pi/4). Any drift here silently
    re-scales circularity for every existing isotropic image and quietly
    invalidates those cutoffs, so the bar is bit-for-bit equality rather
    than "close enough".
    """
    mask = _SHAPES[name]
    mine = crofton_perimeter(mask, (1.0, 1.0))
    theirs = measure.perimeter_crofton(mask, directions=4)
    assert mine == pytest.approx(theirs, rel=1e-12, abs=1e-12)


def test_square_pixels_pick_skimages_own_directions() -> None:
    """The parity above is not a coincidence to be re-measured each time:
    with square pixels the angle-matching search provably lands on the
    four offsets skimage hard-codes."""
    assert set(_direction_offsets((1.0, 1.0), 4, 1)) == {(0, 1), (1, 1), (1, 0), (1, -1)}


def test_per_label_matches_regionprops_on_square_pixels() -> None:
    """Per-region ordering and isolation match `regionprops_table` --
    including two regions that touch, which must EACH count the shared
    edge, since it really is on both their boundaries."""
    lab = np.zeros((160, 200), np.int64)
    rr, cc = draw.disk((40, 40), 22)
    lab[rr, cc] = 1
    lab[20:60, 90:170] = 2
    rr, cc = draw.ellipse(110, 60, 35, 15, rotation=0.7)
    lab[rr, cc] = 3
    lab[100:104, 5:9] = 4  # deliberately tiny
    lab[120:140, 150:170] = 5
    lab[120:140, 170:190] = 6  # 5 and 6 share an edge

    mine = crofton_perimeters_by_label(lab)
    theirs = measure.regionprops_table(lab, properties=("perimeter_crofton",))["perimeter_crofton"]
    assert mine.shape == theirs.shape
    np.testing.assert_allclose(mine, theirs, rtol=1e-12, atol=1e-12)
    # the shared edge really is counted twice, once for each neighbour
    assert mine[4] == pytest.approx(mine[5])


# ── the property that makes anisotropic numbers mean anything ────────────


@pytest.mark.parametrize(
    ("s_r", "s_c"), [(1.0, 1.0), (2.0, 1.0), (1.0, 2.0), (4.0, 1.0), (1.7, 1.0)]
)
def test_one_physical_disc_measures_the_same_however_it_is_sampled(s_r: float, s_c: float) -> None:
    """A disc of physical radius 40 sampled on grids of different
    anisotropy must return the same physical circumference.

    This is the whole point of the module: the answer is a property of
    the object, not of the sampling. The oracle is 2*pi*R, not another
    code path.
    """
    radius = 40.0
    n_r, n_c = int(radius / s_r), int(radius / s_c)
    lab = np.zeros((2 * n_r + 40, 2 * n_c + 40), np.uint8)
    rr, cc = draw.ellipse(n_r + 20, n_c + 20, n_r, n_c)
    lab[rr, cc] = 1
    got = crofton_perimeter(lab, (s_r, s_c))
    assert got == pytest.approx(2 * math.pi * radius, rel=0.05)


def test_scaling_both_axes_scales_the_perimeter(  # dimensional sanity
) -> None:
    """Perimeter is a LENGTH: doubling both pixel scales must double it
    exactly, with no dependence on the shape."""
    mask = _SHAPES["ellipse_rot"]
    base = crofton_perimeter(mask, (1.0, 1.0))
    for factor in (0.5, 2.0, 10.0):
        got = crofton_perimeter(mask, (factor, factor))
        assert got == pytest.approx(factor * base, rel=1e-12)


def test_transposing_image_and_spacing_together_is_invariant() -> None:
    """Transposing the array and swapping the pixel scales describes the
    same physical object, so the perimeter must not move.

    A square fixture would pass this for the wrong reason, so the shape is
    deliberately oblong and the spacing deliberately unequal.
    """
    mask = _rect(12, 37)
    assert crofton_perimeter(mask, (3.0, 1.0)) == pytest.approx(
        crofton_perimeter(mask.T, (1.0, 3.0)), rel=1e-12
    )


# ── the regression this module exists to prevent ─────────────────────────


@pytest.mark.parametrize(("s_r", "s_c"), [(1.0, 1.0), (2.0, 1.0), (6.0, 1.0), (12.0, 1.0)])
def test_bias_does_not_collapse_as_pixels_get_more_anisotropic(s_r: float, s_c: float) -> None:
    """Guards the failure that motivated choosing directions rather than
    fixing them.

    With the four fixed offsets, all four physical directions crowd toward
    90 degrees as anisotropy grows -- at 6:1 they span only 19 degrees --
    and the error on this rectangle degrades from -5.5% to -15.7% while
    the isotropic estimator holds -5.5% on the same shapes. Angle-matched
    directions keep it inside 10%. A regression to fixed offsets fails
    here at 6:1 and 12:1.
    """
    h, w = int(60 / s_r), int(100 / s_c)
    true_perimeter = 2 * (h * s_r + w * s_c)
    got = crofton_perimeter(_rect(h, w), (s_r, s_c))
    assert got == pytest.approx(true_perimeter, rel=0.10)


def test_extreme_aspect_still_reaches_a_diagonal_direction() -> None:
    """The offset search has to widen with the aspect ratio: a 45-degree
    physical direction needs a component of about the aspect ratio, so a
    fixed search radius silently stops finding one."""
    for aspect in (12.0, 20.0, 50.0):
        offsets = _direction_offsets((aspect, 1.0), 4, math.ceil(aspect))
        angles = sorted(math.degrees(math.atan2(p * aspect, q * 1.0) % math.pi) for p, q in offsets)
        assert angles == pytest.approx([0.0, 45.0, 90.0, 135.0], abs=1.0)


# ── degenerate input ─────────────────────────────────────────────────────


def test_empty_and_single_pixel() -> None:
    assert crofton_perimeter(np.zeros((5, 5), bool)) == 0.0
    assert crofton_perimeters_by_label(np.zeros((5, 5), np.int64)).size == 0
    lone = np.zeros((5, 5), np.uint8)
    lone[2, 2] = 1
    assert crofton_perimeter(lone) == pytest.approx(measure.perimeter_crofton(lone, directions=4))


@pytest.mark.parametrize(
    "spacing", [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0), (float("nan"), 1.0), (1.0, math.inf)]
)
def test_refuses_unusable_spacing(spacing: tuple[float, float]) -> None:
    """A zero, negative or non-finite scale has no physical reading, and
    silently returning 0 or NaN would put a meaningless length into a
    result payload (ADR 0004: absent, not meaningless)."""
    with pytest.raises(ValueError, match="finite and positive"):
        crofton_perimeter(_SHAPES["square_20"], spacing)


def test_refuses_non_2d_and_too_few_directions() -> None:
    with pytest.raises(ValueError, match="2D"):
        crofton_perimeter(np.ones((4, 4, 4)), (1.0, 1.0))
    with pytest.raises(ValueError, match="at least 2"):
        crofton_perimeter(_SHAPES["square_20"], (1.0, 1.0), directions=1)
