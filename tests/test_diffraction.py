"""Diffraction tests: synthetic detection/round-trip + golden simulation."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.diffraction import find_spots, index_spots, simulate

pytestmark = pytest.mark.diffraction


# ── synthetic ────────────────────────────────────────────────────────

def test_find_spots_synthetic_pattern() -> None:
    img = np.zeros((128, 128))
    center = (65, 65)                                # floor(128/2)+1, 1-based
    truth = [(65, 95), (65, 35), (95, 65), (35, 65)]
    yy, xx = np.mgrid[1:129, 1:129]
    for r, c in truth + [center]:
        img += np.exp(-((yy - r) ** 2 + (xx - c) ** 2) / 4)

    spots = find_spots(img, min_radius=10, threshold=0.1)
    found = {tuple(map(int, s)) for s in spots}
    assert found == set(truth)                       # beam excluded, all 4 found


def test_simulate_si_001_geometry() -> None:
    sim = simulate("Silicon", zone_axis=(0, 0, 1))
    assert sim.phase_name == "Silicon"
    beam = sim.spots[0]
    assert (beam.pixel_row, beam.pixel_col) == (256.5, 256.5)
    assert np.isnan(beam.d_spacing)
    # all reflections lie in the [001] zone: l == 0
    assert all(s.hkl[2] == 0 for s in sim.spots[1:])
    # diamond structure: (200)-type absent (|F|² = 0), (220)-type present
    hkls = {s.hkl for s in sim.spots[1:]}
    assert (2, 2, 0) in hkls
    assert (2, 0, 0) not in hkls
    # four-fold symmetry: (220) family all present at equal intensity
    fam = [s for s in sim.spots[1:] if sorted(map(abs, s.hkl)) == [0, 2, 2]]
    assert len(fam) == 4
    assert len({round(s.intensity, 12) for s in fam}) == 1
    assert sim.image.shape == (512, 512) and sim.image.max() <= 1.0


def test_index_round_trip_matlab_parity() -> None:
    """Pin the MATLAB result (fermi-viewer@84fd9ef, 2026-06-06 run).

    NOTE: d-spacing-only indexing has no angular information, and the
    intentional simulate/index 0.5 px centre offset gives ~0.5% d errors,
    so dense-d-grid phases (SrRuO3) outrank Silicon on the mean-error
    tie-break. MATLAB behaves identically — this is parity, not a bug:
      1: SrRuO3  score=1.0 n=12 meanErr=0.00232132
      2: Silicon score=1.0 n=12 meanErr=0.00565878
      3: LaNiO3  score=1.0 n=12 meanErr=0.00581723
    """
    # Pin the legacy Z-proxy ("z") model: the MATLAB result was frozen
    # with Z-as-scattering-factor, so this parity check uses the same.
    sim = simulate("Silicon", zone_axis=(0, 0, 1), scattering_model="z")
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, acc_voltage=200)

    def mean_err(c):
        return float(np.mean(np.abs(c.matched_d - c.ref_d) / c.ref_d))

    assert [c.phase_name for c in cands[:3]] == ["SrRuO3", "Silicon", "LaNiO3"]
    assert all(c.score == 1.0 and c.n_matched == 12 for c in cands[:3])
    assert mean_err(cands[0]) == pytest.approx(0.00232132, rel=1e-4)
    assert mean_err(cands[1]) == pytest.approx(0.00565878, rel=1e-4)
    assert mean_err(cands[2]) == pytest.approx(0.00581723, rel=1e-4)
    # zone axis comes from FAMILY-REPRESENTATIVE hkls (mostly (0,k,l)
    # after the sortrows tie-break), so the recovered axis is (-1,0,0),
    # not the physical (0,0,1) — MATLAB's findZoneAxis loop is identical.
    assert cands[1].zone_axis == (-1.0, 0.0, 0.0)


def test_index_no_match_scores_zero() -> None:
    pos = np.array([[257.0, 258.0]])                 # 1 px off-centre → huge d
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, tolerance=0.01)
    assert all(c.score == 0 for c in cands)


# ── golden ───────────────────────────────────────────────────────────

@pytest.mark.golden
class TestGolden:
    def test_simulate_silicon_001_top_spots(self, golden) -> None:
        g = golden("diffraction")["simulateSilicon001"]
        # Golden frozen with the Z-proxy weighting → pin scattering_model="z"
        # so the new Doyle-Turner default does not move the golden numbers.
        sim = simulate("Silicon", zone_axis=(0, 0, 1),
                       acc_voltage=200, image_size=(512, 512),
                       scattering_model="z")
        assert sim.lam == pytest.approx(g["lambda"], rel=1e-12)
        assert len(sim.spots) == g["nSpots"]
        assert sim.image.sum() == pytest.approx(g["imageSum"], rel=1e-9)

        # MATLAB freeze: stable descending-intensity sort, top 10
        order = np.argsort([-s.intensity for s in sim.spots], kind="stable")
        top = [sim.spots[i] for i in order[:10]]
        for mine, gold in zip(top, g["topSpots"], strict=True):
            if gold.get("dSpacing"):
                assert list(mine.hkl) == gold["hkl"]
                assert mine.d_spacing == pytest.approx(gold["dSpacing"], rel=1e-12)
            else:
                assert mine.hkl == (0, 0, 0)         # direct beam
            assert mine.intensity == pytest.approx(gold["intensity"], rel=1e-12)
            assert mine.pixel_row == pytest.approx(gold["pixelRow"], rel=1e-12)
            assert mine.pixel_col == pytest.approx(gold["pixelCol"], rel=1e-12)

    def test_index_round_trip_fields(self, golden) -> None:
        g = golden("diffraction").get("indexRoundTrip")
        if not g:
            pytest.skip("no indexRoundTrip in golden")
        # the MATLAB result exposes candidates/measuredD/measuredR/center
        assert "candidates" in g["fields"]
