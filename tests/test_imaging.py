"""W3 tranche-1 imaging ports vs MATLAB goldens (imaging.json).

Synthetics are CLOSED-FORM (no RNG) and defined identically in
tools/matlab/freeze_reference_values.m — see docs/w3_imaging_audit.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.calc.filters import (
    apply_gaussian,
    apply_median,
    area_downsample,
    bin_image,
    butterworth_filter,
    clahe,
    plane_level,
    thumbnail,
    unsharp_mask,
)
from fermiviewer.calc.segment import (
    distance_transform,
    label_components,
    morph_op,
    multi_otsu,
)

pytestmark = [pytest.mark.imaging, pytest.mark.golden]

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "imaging.json").read_text()
)
REL = 1e-9


@pytest.fixture(scope="module")
def synth() -> dict[str, np.ndarray]:
    # 1-based r, c per the MATLAB definition
    r = np.arange(1, 65, dtype=np.float64)[:, None]
    c = np.arange(1, 97, dtype=np.float64)[None, :]
    base = np.sin(r / 7) * np.cos(c / 11) + 0.001 * (r * c) / (64 * 96)
    noisy = base + 0.05 * np.sin(13 * r + 7 * c)
    bw = base > 0.2
    return {"base": base, "noisy": noisy, "bw": bw}


def check_fp(arr: np.ndarray, fp: dict, rel: float = REL) -> None:
    assert list(arr.shape) == fp["size"]
    assert arr.sum() == pytest.approx(fp["sum"], rel=rel, abs=1e-12)
    assert np.abs(arr).sum() == pytest.approx(fp["sumAbs"], rel=rel)
    r = min(19, arr.shape[0] - 1)
    c = min(29, arr.shape[1] - 1)
    assert arr[r, c] == pytest.approx(fp["px"], rel=rel, abs=1e-12)


def test_synthetic_matches_matlab(synth) -> None:
    g = GOLDEN["synthetic"]
    assert synth["base"].sum() == pytest.approx(g["baseSum"], rel=REL)
    assert synth["noisy"].sum() == pytest.approx(g["noisySum"], rel=REL)
    assert int(synth["bw"].sum()) == g["bwCount"]


def test_gaussian(synth) -> None:
    check_fp(apply_gaussian(synth["base"], sigma=2), GOLDEN["gaussian"])


def test_median(synth) -> None:
    check_fp(apply_median(synth["noisy"], window_size=5), GOLDEN["median"])


def test_unsharp(synth) -> None:
    check_fp(
        unsharp_mask(synth["base"], sigma=2, amount=1.5), GOLDEN["unsharp"]
    )


def test_butterworth(synth) -> None:
    out = butterworth_filter(
        synth["base"], low_cutoff=0.05, high_cutoff=0.5, order=2
    )
    check_fp(out, GOLDEN["butterworth"])


def test_clahe(synth) -> None:
    out = clahe(
        synth["base"], tile_size=(8, 8), clip_limit=0.01, num_bins=256
    )
    check_fp(out, GOLDEN["clahe"])
    assert out.min() >= 0 and out.max() <= 1


def test_bin_image(synth) -> None:
    check_fp(bin_image(synth["base"], 4, "average"), GOLDEN["binAvg"])
    check_fp(bin_image(synth["base"], 4, "sum"), GOLDEN["binSum"])


def test_area_downsample(synth) -> None:
    check_fp(area_downsample(synth["base"], 16, 24), GOLDEN["downsample"])


def test_thumbnail(synth) -> None:
    check_fp(thumbnail(synth["base"], max_size=32), GOLDEN["thumbnail"])


def test_plane_level(synth) -> None:
    res = plane_level(synth["noisy"], order=2)
    np.testing.assert_allclose(
        res.coeffs, GOLDEN["planeLevel"]["coeffs"], rtol=1e-6, atol=1e-12
    )
    assert np.abs(res.leveled).sum() == pytest.approx(
        GOLDEN["planeLevel"]["leveledSum"], rel=1e-9
    )
    # surface + leveled reconstructs the input
    np.testing.assert_allclose(
        res.surface + res.leveled, synth["noisy"], rtol=0, atol=1e-9
    )


def test_percentiles(synth) -> None:
    got = np.percentile(synth["base"].ravel(), [1, 50, 99])
    np.testing.assert_allclose(got, GOLDEN["percentiles"], rtol=REL)


def test_multi_otsu(synth) -> None:
    res = multi_otsu(synth["base"], n_classes=3, n_bins=256)
    np.testing.assert_allclose(
        res.thresholds, GOLDEN["multiOtsu"]["thresholds"], rtol=REL
    )
    assert res.class_fractions.sum() == pytest.approx(1.0)
    assert res.label_map.min() >= 1 and res.label_map.max() <= 3


def test_morphology(synth) -> None:
    for op, expect in GOLDEN["morph"].items():
        got = int(morph_op(synth["bw"], op, radius=2, shape="disk").sum())
        assert got == expect, f"morph {op}: {got} != {expect}"


def test_label_components(synth) -> None:
    labels8, n8 = label_components(synth["bw"], connectivity=8)
    _, n4 = label_components(synth["bw"], connectivity=4)
    assert n8 == GOLDEN["label"]["n8"]
    assert n4 == GOLDEN["label"]["n4"]
    areas = np.sort(np.bincount(labels8.ravel())[1:])
    np.testing.assert_array_equal(areas, GOLDEN["label"]["areas8Sorted"])


def test_distance_transform(synth) -> None:
    d34 = distance_transform(synth["bw"], metric="chamfer34")
    assert d34.sum() == GOLDEN["distance"]["chamferSum"]
    assert d34.max() == GOLDEN["distance"]["chamferMax"]
    dcb = distance_transform(synth["bw"], metric="cityblock")
    assert dcb[np.isfinite(dcb)].sum() == GOLDEN["distance"]["cityblockSum"]


def test_edge_cases() -> None:
    flat = np.full((10, 12), 3.0)
    assert clahe(flat).sum() == 0  # constant image → zeros
    res = multi_otsu(flat, n_classes=2)
    assert res.thresholds[0] == 3.0
    empty = distance_transform(np.zeros((5, 5), dtype=bool))
    assert empty.sum() == 0
    with pytest.raises(ValueError):
        apply_median(flat, window_size=4)
    with pytest.raises(ValueError):
        bin_image(flat, 100)
    with pytest.raises(ValueError):
        morph_op(flat > 0, "explode")
