"""Item 15 (atoms + grains) vs MATLAB goldens.

The atom-lattice synthetic is RNG-free; the k-means-backed pieces
(sublattice, grain segmentation) use deliberately separable synthetics
so the converged partition is unique across RNG implementations —
labels are compared after the deterministic brightness/area orderings.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.calc.atoms import (
    assign_sublattice,
    detect_columns,
    find_lattice_vectors,
    fit_gaussian_2d,
    peak_pair_strain,
)
from fermiviewer.calc.grains import (
    extract_grain_features,
    grain_stats,
    segment_auto,
)

pytestmark = [pytest.mark.imaging, pytest.mark.golden]

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "imaging.json").read_text()
)
REL = 1e-9


@pytest.fixture(scope="module")
def atom_img() -> np.ndarray:
    xx, yy = np.meshgrid(
        np.arange(1, 121, dtype=np.float64),
        np.arange(1, 101, dtype=np.float64),
    )
    img = 0.05 + 0.001 * xx
    for gi in range(10):
        for gj in range(12):
            cx = 8 + gj * 9.6
            cy = 7 + gi * 9.2 + 0.15 * gj
            amp = 1 + 0.3 * ((gi + gj) % 2)
            img = img + amp * np.exp(
                -((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * 1.8**2)
            )
    return img


@pytest.fixture(scope="module")
def fitted(atom_img):
    det = detect_columns(
        atom_img, sigma=2, threshold=0.15, min_separation=5
    )
    fit = fit_gaussian_2d(atom_img, det.positions, win_radius=4)
    return det, fit


def test_synthetic_and_detect(atom_img, fitted) -> None:
    g = GOLDEN["atoms"]
    assert atom_img.sum() == pytest.approx(g["imgSum"], rel=REL)
    det, _ = fitted
    assert det.positions.shape[0] == g["detectN"]
    assert det.positions.sum() == pytest.approx(g["detectPosSum"], rel=REL)
    assert det.intensities.sum() == pytest.approx(
        g["detectIntSum"], rel=REL
    )


def test_fit_gaussian_2d(fitted) -> None:
    g = GOLDEN["atoms"]
    _, fit = fitted
    assert int(fit.converged.sum()) == g["fitConverged"]
    # verbatim LM, but \ vs solve round-off can wiggle late iterations
    assert fit.positions.sum() == pytest.approx(g["fitPosSum"], rel=1e-7)
    assert fit.amplitude.sum() == pytest.approx(g["fitAmpSum"], rel=1e-6)
    assert fit.sigma.sum() == pytest.approx(g["fitSigmaSum"], rel=1e-6)
    assert fit.rsquared.min() == pytest.approx(g["fitR2Min"], rel=1e-6)


def test_find_lattice_vectors(fitted) -> None:
    g = GOLDEN["atoms"]
    _, fit = fitted
    lv = find_lattice_vectors(fit.positions)
    assert lv.valid == bool(g["lvValid"])
    np.testing.assert_allclose(lv.a1, g["a1"], rtol=1e-6)
    np.testing.assert_allclose(lv.a2, g["a2"], rtol=1e-6)
    assert lv.spacing == pytest.approx(g["spacing"], rel=1e-6)
    np.testing.assert_allclose(lv.origin, g["origin"], rtol=1e-6)


def test_peak_pair_strain(fitted) -> None:
    g = GOLDEN["atoms"]
    _, fit = fitted
    st = peak_pair_strain(fit.positions)
    assert st.valid == bool(g["strainValid"])
    assert np.nanmean(st.exx) == pytest.approx(g["exxMean"], abs=1e-8)
    assert np.nanmean(st.eyy) == pytest.approx(g["eyyMean"], abs=1e-8)
    assert np.nanmean(st.exy) == pytest.approx(g["exyMean"], abs=1e-8)
    assert np.abs(st.displacement).sum() == pytest.approx(
        g["dispSum"], rel=1e-5
    )


def test_assign_sublattice(fitted) -> None:
    g = GOLDEN["atoms"]
    _, fit = fitted
    sub = assign_sublattice(fit.amplitude, 2)
    counts = [int((sub == 1).sum()), int((sub == 2).sum())]
    assert counts == list(g["subCounts"])
    # label 1 = brightest sublattice (deterministic remap)
    assert sub[int(np.argmax(fit.amplitude))] == g["subBrightLabel"]


@pytest.fixture(scope="module")
def grain_img() -> np.ndarray:
    r = np.arange(1, 65, dtype=np.float64)[:, None]
    c = np.arange(1, 97, dtype=np.float64)[None, :]
    base = np.sin(r / 7) * np.cos(c / 11) + 0.001 * (r * c) / (64 * 96)
    noisy = base + 0.05 * np.sin(13 * r + 7 * c)
    return np.hstack([base[:, :48], noisy[:, 48:] + 1.5])


def test_grain_features(grain_img) -> None:
    g = GOLDEN["grains"]
    feats = extract_grain_features(grain_img)
    assert list(feats.shape) == g["featSize"]
    assert feats.sum() == pytest.approx(g["featSum"], rel=REL)


def test_segment_auto_and_stats(grain_img) -> None:
    # k-means partitions are RNG-dependent at the texture-transition
    # zone (MATLAB twister vs numpy PCG converge to centres differing
    # within Tol=1e-4, flipping ~1% of boundary pixels) — so goldens
    # compare at PARTITION level: counts exact, areas/inertia tolerant.
    g = GOLDEN["grains"]
    seg = segment_auto(grain_img, k=2, min_area=25, seed=0, replicates=3)
    assert seg.n_grains == g["numGrains"]
    areas = np.sort(np.bincount(seg.labels.ravel())[1:])
    areas = areas[areas > 0]
    np.testing.assert_allclose(areas, g["areasSorted"], rtol=0.05, atol=10)
    assert seg.inertia == pytest.approx(g["inertia"], rel=1e-2)

    gs = grain_stats(seg.labels, grain_img, pixel_size=0.4)
    assert gs.boundary_length_px == pytest.approx(
        g["boundaryLengthPx"], rel=0.1
    )
    assert gs.n_boundary_segments == g["numBoundarySegments"]
    assert gs.area_px.sum() == pytest.approx(g["areaPxSum"], rel=1e-2)
    assert gs.boundary_length_calibrated == pytest.approx(
        gs.boundary_length_px * 0.4, rel=REL
    )
