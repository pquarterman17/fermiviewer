"""Integrating a cross-section along a rotated axis (feature request #1).

The claim this module has to earn: a stack mounted a few degrees off-square
reports blurred interfaces when integrated along the image rows, and
integrating along the stack's own axis recovers the sharpness. Every test
here is built on a synthetic stack with a KNOWN tilt and a KNOWN interface
width, so "sharper" is measured against the width that was planted rather
than against the untilted answer alone.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import erf

from fermiviewer.calc.layers_profile import cross_section_profile
from fermiviewer.calc.tilted_profile import tilted_depth_profile

pytestmark = pytest.mark.imaging

H = W = 201
SIGMA = 2.0          # planted interface width, pixels
TILT = 12.0          # planted stack tilt, degrees


def _tilted_stack(tilt_deg: float, sigma: float = SIGMA) -> np.ndarray:
    """One erf interface through the centre, rotated by `tilt_deg`.

    Built analytically from the rotated coordinate rather than by rotating
    a raster, so the image has no interpolation blur of its own — any width
    the profile reports beyond `sigma` came from the integration.
    """
    r, c = np.mgrid[0:H, 0:W].astype(np.float64)
    theta = np.radians(tilt_deg)
    # distance from the tilted interface line through the image centre
    depth = (r - (H - 1) / 2) * np.cos(theta) + (c - (W - 1) / 2) * np.sin(theta)
    return 0.5 * (1 + erf(depth / (sigma * np.sqrt(2))))


def _edge_width(depth: np.ndarray, profile: np.ndarray) -> float:
    """10-90% rise distance — the width a reader would quote off the plot."""
    lo, hi = profile.min(), profile.max()
    p10, p90 = lo + 0.1 * (hi - lo), lo + 0.9 * (hi - lo)
    x10 = float(np.interp(p10, profile, depth))
    x90 = float(np.interp(p90, profile, depth))
    return abs(x90 - x10)


def test_an_untilted_stack_is_unchanged_by_a_zero_tilt() -> None:
    """The no-op must be exact, or every existing result shifts under a
    feature nobody switched on."""
    img = _tilted_stack(0.0)
    depth, straight = cross_section_profile(img, axis="y", reduce="mean")
    out = tilted_depth_profile(img, None, axis="y", tilt_deg=0.0)
    assert out.sampled_fraction == pytest.approx(1.0)
    assert out.lateral_samples == W
    np.testing.assert_allclose(out.profile, straight, atol=1e-9)
    np.testing.assert_allclose(out.depth_pos, depth)


def test_integrating_square_across_a_tilted_stack_blurs_the_interface() -> None:
    """The negative control, and the reason the feature exists.

    Averaging a tilted interface along image rows convolves it with a box
    as wide as the interface's lateral run, ``W·tan θ``. The 10-90% width
    of a box is 0.8 of its width, so the reported edge should come out at
    ``0.8·W·tan(12°) ≈ 34 px`` — against the ~5 px it actually has.
    Pinning the predicted value rather than "bigger than X" means this
    fails if the blur ever has some other cause.
    """
    img = _tilted_stack(TILT)
    depth, profile = cross_section_profile(img, axis="y", reduce="mean")
    blurred = _edge_width(depth, profile)
    predicted = 0.8 * W * np.tan(np.radians(TILT))
    assert blurred == pytest.approx(predicted, rel=0.05)
    assert blurred > 5 * (2.563 * SIGMA)


def test_integrating_along_the_stack_axis_recovers_the_planted_width() -> None:
    img = _tilted_stack(TILT)
    out = tilted_depth_profile(img, None, axis="y", tilt_deg=TILT, reduce="mean")
    recovered = _edge_width(out.depth_pos, out.profile)
    # 10-90% of an erf is 2.563·σ
    assert recovered == pytest.approx(2.563 * SIGMA, rel=0.15)


def test_the_wrong_sign_of_tilt_makes_it_worse_not_better() -> None:
    """Guards against a correction that is really just a smoothing: if the
    sign were ignored, -12° would work as well as +12°."""
    img = _tilted_stack(TILT)
    right = tilted_depth_profile(img, None, axis="y", tilt_deg=TILT)
    wrong = tilted_depth_profile(img, None, axis="y", tilt_deg=-TILT)
    assert _edge_width(wrong.depth_pos, wrong.profile) > 5 * _edge_width(
        right.depth_pos, right.profile
    )


def test_every_depth_row_averages_the_same_lateral_width() -> None:
    """A NaN-padded rotated box would vignette — fewer contributing pixels
    near the ends — and that gradient would read as specimen structure. The
    inscribed box exists to make this constant."""
    out = tilted_depth_profile(_tilted_stack(TILT), None, axis="y", tilt_deg=TILT)
    assert out.sampled_fraction < 1.0        # it really did shrink
    flat = tilted_depth_profile(
        np.ones((H, W)), None, axis="y", tilt_deg=TILT, reduce="mean"
    )
    # a uniform image must come back uniform: any edge falloff is vignetting
    assert flat.profile.std() == pytest.approx(0.0, abs=1e-12)
    assert flat.profile.min() == pytest.approx(1.0)


def test_axis_x_is_the_same_measurement_on_a_transposed_stack() -> None:
    img = _tilted_stack(TILT)
    by_y = tilted_depth_profile(img, None, axis="y", tilt_deg=TILT)
    by_x = tilted_depth_profile(img.T, None, axis="x", tilt_deg=TILT)
    np.testing.assert_allclose(by_x.profile, by_y.profile, atol=1e-9)


def test_a_tilt_that_leaves_no_box_is_refused_not_silently_narrowed() -> None:
    thin = _tilted_stack(0.0)[:, :6]
    with pytest.raises(ValueError, match="lateral pixels"):
        tilted_depth_profile(thin, None, axis="y", tilt_deg=60.0)


def test_sum_is_refused_because_the_box_changes_size_with_the_angle() -> None:
    with pytest.raises(ValueError, match="'mean' or 'median'"):
        tilted_depth_profile(
            _tilted_stack(0.0), None, axis="y", tilt_deg=5.0, reduce="sum"
        )


# ── wired into the layers analysis ───────────────────────────────────


def test_a_tilt_correction_sharpens_the_interface_the_analysis_reports() -> None:
    """End to end: the σ_erf a user reads must improve, not just the raw
    profile. A correction that fixed the curve but never reached the fit
    would leave the reported number wrong."""
    from fermiviewer.calc.layers import analyze_layers

    img = _tilted_stack(TILT)
    square = analyze_layers(img, axis="y")
    levelled = analyze_layers(img, axis="y", tilt_deg=TILT)
    assert square.applied_tilt_deg is None
    assert levelled.applied_tilt_deg == pytest.approx(TILT)
    assert levelled.sampled_fraction < 1.0
    (flat,) = levelled.interfaces
    (smeared,) = square.interfaces
    assert flat.sigma_erf == pytest.approx(SIGMA, rel=0.25)
    # Uncorrected, the edge is wider than the fit window, so the erf fit is
    # rejected outright and there is no width to report. A rejected fit must
    # also report no quality — r² of 0, not the 1.0 of the fit that was just
    # thrown away, which `assessLayerQuality` would read as a fine interface.
    assert not np.isfinite(smeared.sigma_erf)
    assert smeared.r_squared == 0.0
    assert np.isfinite(flat.sigma_erf) and flat.r_squared > 0.9


def test_re_measuring_an_edit_uses_the_same_frame_it_was_dragged_in() -> None:
    """The positions a user drags are depths in the COLLAPSED profile. Feed
    them back with a different tilt and they mean something else, so every
    interface moves. Both calls here pass the same tilt, and the refit must
    land essentially where the detector did."""
    from fermiviewer.calc.layers import analyze_layers, recompute_layers

    img = _tilted_stack(TILT)
    detected = analyze_layers(img, axis="y", tilt_deg=TILT)
    positions = [i.position for i in detected.interfaces]
    same = recompute_layers(img, positions, axis="y", tilt_deg=TILT)
    assert same.applied_tilt_deg == pytest.approx(TILT)
    assert [i.position for i in same.interfaces] == pytest.approx(positions, abs=1.0)

    # and the trap: the SAME positions read against the uncorrected frame
    # describe a different profile, so the answer is not the same measurement
    other = recompute_layers(img, positions, axis="y", tilt_deg=None)
    assert other.applied_tilt_deg is None
    assert other.depth_profile.size != same.depth_profile.size


def test_a_waviness_trace_runs_in_the_corrected_frame() -> None:
    """A trace taken from the un-rotated block while the profile came from
    the rotated one would sit at depths the profile never had — so the
    trace's mean would not match its own interface position."""
    from fermiviewer.calc.layers import analyze_layers

    res = analyze_layers(_tilted_stack(TILT), axis="y", tilt_deg=TILT, waviness=True)
    (iface,) = res.interfaces
    assert iface.trace is not None
    assert iface.trace.size == res.depth_profile.size or iface.trace.size > 1
    # the levelled interface is flat, so its trace sits on its own centre
    assert float(np.nanmean(iface.trace)) == pytest.approx(iface.position, abs=2.0)
