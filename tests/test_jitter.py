"""Scan-line jitter and frame-drift correction (calc/jitter.py), checked
against synthetic images with a known, injected distortion.

The images are smooth atomic-column lattices (the case the correction is
built for) plus a little detector noise. Tolerances are the accuracy the
method reaches here, with margin — a regression that loses sub-pixel
accuracy or flips a sign fails them.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import ndimage

from fermiviewer.calc.jitter import (
    apply_frame_drift,
    correct_line_jitter,
    estimate_frame_drift,
    estimate_line_jitter,
)

PAD = 32


def _lattice(h: int, w: int, period: float = 16.0, sigma: float = 2.6) -> np.ndarray:
    """Gaussian atom columns on a square lattice, padded by PAD all round
    so distorted crops never sample outside the field."""
    yy, xx = np.mgrid[0 : h + 2 * PAD, 0 : w + 2 * PAD].astype(float)
    img = np.exp(
        -(((xx % period) - period / 2) ** 2 + ((yy % period) - period / 2) ** 2)
        / (2 * sigma**2)
    )
    return (img - img.mean()) / img.std()


def _jittered(base: np.ndarray, offsets: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Displace row r of the central crop by offsets[r] px (content moves right)."""
    h = offsets.size
    w = base.shape[1] - 2 * PAD
    x = np.arange(base.shape[1], dtype=float)
    rows = [np.interp(x - offsets[r], x, base[PAD + r]) for r in range(h)]
    return np.array(rows)[:, PAD : PAD + w] + rng.normal(0, 0.1, (h, w))


def _centred(v: np.ndarray) -> np.ndarray:
    return v - np.median(v)


# ── line jitter ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kind",
    ["white", "mains"],
)
def test_line_jitter_recovers_injected_offsets(kind: str) -> None:
    rng = np.random.default_rng(7)
    h, w = 384, 384
    base = _lattice(h, w)
    if kind == "white":
        truth = rng.normal(0, 0.8, h)
    else:  # mains-like: a periodic wobble repeating every ~40 lines
        truth = 0.9 * np.sin(2 * np.pi * np.arange(h) / 41.0) + rng.normal(0, 0.15, h)
    img = _jittered(base, truth, rng)

    res = estimate_line_jitter(img)

    # accuracy is judged on rows that contain structure: a blank row midway
    # between atomic rows has nothing to measure, and nothing to move
    clean = base[PAD : PAD + h, PAD : PAD + w]
    lit = clean.std(axis=1) >= np.median(clean.std(axis=1))
    err = (res.offsets - _centred(truth))[lit]
    assert np.sqrt(np.mean(err**2)) < 0.4
    assert np.corrcoef(res.offsets[lit], truth[lit])[0, 1] > 0.9
    assert res.rms == pytest.approx(np.sqrt(np.mean(res.offsets**2)))
    # correcting with the estimate brings the image back toward the truth
    fixed = correct_line_jitter(img, res.offsets)
    inner = (slice(None), slice(16, -16))
    assert np.abs(fixed - clean)[inner].mean() < 0.6 * np.abs(img - clean)[inner].mean()


def test_line_jitter_leaves_a_clean_lattice_nearly_alone() -> None:
    """No jitter in, (almost) none out — the correction must not invent
    distortion, including on the near-blank rows between atomic rows."""
    rng = np.random.default_rng(3)
    clean = _lattice(256, 256)[PAD:-PAD, PAD:-PAD] + rng.normal(0, 0.1, (256, 256))
    res = estimate_line_jitter(clean)
    assert res.rms < 0.25


def test_line_jitter_keeps_a_genuine_shear() -> None:
    """A lattice sheared steadily across the image is real structure, not
    jitter: the offsets must not follow the shear. (Single near-blank rows
    midway between atomic rows can still read a noisy offset; with nothing
    in them, that moves no visible structure, so the test bounds the RMS
    and the correlation with the shear rather than the worst row.)"""
    rng = np.random.default_rng(5)
    h = 256
    base = _lattice(h, 256)
    shear = np.linspace(-3.0, 3.0, h)
    res = estimate_line_jitter(_jittered(base, shear, rng))
    assert res.rms < 0.3
    assert abs(np.corrcoef(res.offsets, shear)[0, 1]) < 0.2


def test_line_jitter_sign_convention() -> None:
    """A single row displaced to the right gets a positive offset."""
    rng = np.random.default_rng(11)
    truth = np.zeros(128)
    truth[64] = 2.0
    res = estimate_line_jitter(_jittered(_lattice(128, 256, period=20.0), truth, rng))
    assert res.offsets[64] == pytest.approx(2.0, abs=0.4)
    assert abs(float(np.median(res.offsets))) < 1e-9


def test_correct_line_jitter_resamples_rows() -> None:
    img = np.tile(np.arange(10, dtype=float), (3, 1))
    out = correct_line_jitter(img, np.array([0.0, 1.0, -0.5]))
    np.testing.assert_allclose(out[0], img[0])
    # sampling at x + 1: each value moves one place left, the edge repeats
    np.testing.assert_allclose(out[1], [1, 2, 3, 4, 5, 6, 7, 8, 9, 9])
    np.testing.assert_allclose(out[2][1:], np.arange(9) + 0.5)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"max_shift": 0.5}, "max_shift"),
        ({"trend_rows": -1}, "trend_rows"),
        ({"max_lag": 0}, "max_lag"),
        ({"min_corr": 1.0}, "min_corr"),
        ({"iterations": 0}, "iterations"),
    ],
)
def test_line_jitter_rejects_bad_parameters(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        estimate_line_jitter(np.zeros((16, 16)), **kwargs)


def test_line_jitter_rejects_non_images() -> None:
    with pytest.raises(ValueError, match="2-D"):
        estimate_line_jitter(np.zeros(32))
    with pytest.raises(ValueError, match="too small"):
        estimate_line_jitter(np.zeros((2, 32)))


def test_line_jitter_tolerates_non_finite_pixels() -> None:
    rng = np.random.default_rng(2)
    img = _lattice(64, 64)[PAD:-PAD, PAD:-PAD] + rng.normal(0, 0.1, (64, 64))
    img[10, 5] = np.nan
    img[20, 7] = np.inf
    assert np.isfinite(estimate_line_jitter(img).offsets).all()


# ── frame drift ─────────────────────────────────────────────────────────

SHIFTS = np.array([[0.0, 0.0], [1.3, -2.6], [3.7, 0.4], [-2.2, 4.9], [5.5, -1.1]])


def _drifted_frames(rng: np.random.Generator, noise: float = 0.3) -> tuple[list, np.ndarray]:
    yy, xx = np.mgrid[0:320, 0:320].astype(float)
    texture = ndimage.gaussian_filter(rng.normal(size=(320, 320)), 3)
    base = texture / texture.std() + 0.5 * np.sin(xx / 5) * np.cos(yy / 7)
    frames = [
        ndimage.shift(base, (dy, dx), order=3, mode="nearest")[PAD:-PAD, PAD:-PAD]
        + rng.normal(0, noise, (256, 256))
        for dy, dx in SHIFTS
    ]
    return frames, base[PAD:-PAD, PAD:-PAD]


@pytest.mark.parametrize("reference", ["first", "mean"])
def test_frame_drift_recovers_subpixel_shifts(reference: str) -> None:
    frames, _ = _drifted_frames(np.random.default_rng(0))
    res = estimate_frame_drift(frames, reference=reference)
    np.testing.assert_allclose(res.shifts, SHIFTS, atol=0.25)
    assert res.shifts[0].tolist() == [0.0, 0.0]
    assert res.max_abs == pytest.approx(float(np.max(np.abs(res.shifts))))


def test_frame_drift_average_is_sharper_and_cropped() -> None:
    frames, truth = _drifted_frames(np.random.default_rng(1))
    res = estimate_frame_drift(frames)
    aligned, (top, bottom, left, right) = apply_frame_drift(frames, res.shifts)
    # the crop excludes every row/column some frame had to pad
    assert top >= 2 and left >= 2 and bottom <= 256 - 5 and right <= 256 - 4
    assert all(a.shape == (bottom - top, right - left) for a in aligned)
    window = (slice(top, bottom), slice(left, right))
    naive = np.mean(frames, axis=0)[window]
    corrected = np.mean(aligned, axis=0)
    err_naive = np.abs(naive - truth[window]).mean()
    err_corrected = np.abs(corrected - truth[window]).mean()
    assert err_corrected < 0.5 * err_naive


def test_frame_drift_without_crop_keeps_frame_size() -> None:
    frames, _ = _drifted_frames(np.random.default_rng(4))
    aligned, box = apply_frame_drift(frames, np.zeros((len(frames), 2)), crop=False)
    assert box == (0, 256, 0, 256)
    np.testing.assert_allclose(aligned[2], frames[2])


def test_frame_drift_rejects_bad_input() -> None:
    a = np.zeros((32, 32))
    with pytest.raises(ValueError, match="at least 2"):
        estimate_frame_drift([a])
    with pytest.raises(ValueError, match="same size"):
        estimate_frame_drift([a, np.zeros((32, 40))])
    with pytest.raises(ValueError, match="reference"):
        estimate_frame_drift([a, a], reference="median")
    with pytest.raises(ValueError, match="one \\(dy, dx\\)"):
        apply_frame_drift([a, a], np.zeros((3, 2)))
    with pytest.raises(ValueError, match="no common region"):
        apply_frame_drift([a, a], np.array([[0.0, 0.0], [31.0, 0.0]]))
