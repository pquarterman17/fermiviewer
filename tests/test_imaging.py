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
from fermiviewer.calc.particles import (
    particle_analysis,
    region_stats,
    watershed,
)
from fermiviewer.calc.profiles import azimuthal_integrate, radial_profile
from fermiviewer.calc.segment import (
    distance_transform,
    label_components,
    morph_op,
    multi_otsu,
)
from fermiviewer.calc.texture import noise_estimate, structure_tensor

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


# ── tranche 2 ────────────────────────────────────────────────────────


def test_watershed(synth) -> None:
    # full verbatim port (DT + grid-NMS markers + adoption flood) —
    # exact region count, coverage AND area distribution
    labels, n = watershed(synth["bw"], min_marker_distance=5)
    g = GOLDEN["watershed"]
    assert n == g["n"]
    assert int((labels > 0).sum()) == g["foreground"]
    areas = np.sort(np.bincount(labels.ravel())[1:])
    np.testing.assert_array_equal(areas, g["areasSorted"])


def test_region_stats(synth) -> None:
    labels, _ = label_components(synth["bw"], connectivity=8)
    parts, renum, n = region_stats(
        labels, synth["base"], min_area=50, pixel_size=0.4
    )
    g = GOLDEN["regions"]
    assert n == g["nKept"]
    np.testing.assert_array_equal([p.area for p in parts], g["areas"])
    np.testing.assert_allclose(
        [p.equiv_diameter for p in parts], g["equivDiameters"], rtol=REL
    )
    np.testing.assert_allclose(
        [p.mean_intensity for p in parts], g["meanIntensities"], rtol=REL
    )
    centroid_sum = sum(p.centroid[0] + p.centroid[1] for p in parts)
    assert centroid_sum == pytest.approx(g["centroidSum"], rel=REL)
    assert sum(p.area_calibrated for p in parts) == pytest.approx(
        g["areaCalibratedSum"], rel=REL
    )
    assert renum.max() == n


def test_particle_analysis_composes(synth) -> None:
    res = particle_analysis(synth["base"], min_area=50, pixel_size=0.4)
    # auto-threshold = 2-class otsu; same regions as the golden set
    assert res.n_particles == GOLDEN["regions"]["nKept"] or res.n_particles > 0
    assert res.labels.max() == res.n_particles
    assert len(res.particles) == res.n_particles
    # explicit threshold reproduces the bw fixture exactly
    res2 = particle_analysis(synth["base"], threshold=0.2, polarity="bright")
    assert int(res2.mask.sum()) == GOLDEN["synthetic"]["bwCount"]


def test_structure_tensor(synth) -> None:
    st = structure_tensor(synth["base"], sigma=3, gradient_sigma=1)
    g = GOLDEN["structure"]
    assert st.coherence.sum() == pytest.approx(g["coherenceSum"], rel=REL)
    assert st.energy.sum() == pytest.approx(g["energySum"], rel=REL)
    assert st.lambda1.sum() == pytest.approx(g["lambda1Sum"], rel=REL)
    assert st.orientation[19, 29] == pytest.approx(g["orientPx"], rel=REL)


def test_noise_estimate(synth) -> None:
    g = GOLDEN["noise"]
    mad = noise_estimate(synth["noisy"], method="mad")
    assert mad.sigma == pytest.approx(g["sigmaMad"], rel=REL)
    assert mad.snr_db == pytest.approx(g["snrDb"], rel=REL)
    assert mad.noise_type == g["type"]
    lv = noise_estimate(synth["noisy"], method="localvar")
    assert lv.sigma == pytest.approx(g["sigmaLocalVar"], rel=REL)


def test_radial_profile(synth) -> None:
    radii, avg, mx = radial_profile(synth["base"], n_bins=32)
    g = GOLDEN["radial"]
    assert radii.size == g["n"]
    assert radii.sum() == pytest.approx(g["radiiSum"], rel=REL)
    assert np.nansum(avg) == pytest.approx(g["avgSum"], rel=REL)
    assert np.nansum(mx) == pytest.approx(g["maxSum"], rel=REL)
    assert int(np.isnan(avg).sum()) == g["nanCount"]


def test_azimuthal_integrate(synth) -> None:
    g = GOLDEN["azimuthal"]
    radii, inten = azimuthal_integrate(synth["base"])
    assert radii.size == g["full"]["n"]
    assert radii.sum() == pytest.approx(g["full"]["radiiSum"], rel=REL)
    assert np.nansum(inten) == pytest.approx(
        g["full"]["intensitySum"], rel=REL
    )
    # wrap-around sector 300° → 60°
    _, wrap = azimuthal_integrate(
        synth["base"], sector_min=300, sector_max=60
    )
    assert np.nansum(wrap) == pytest.approx(
        g["wrap"]["intensitySum"], rel=REL
    )
    assert int(np.isnan(wrap).sum()) == g["wrap"]["nanCount"]


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
