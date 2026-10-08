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


def test_index_round_trip_finds_silicon_001() -> None:
    """A simulated Si [001] pattern indexes back to Silicon on the [001] zone.

    Spot patterns are indexed by d-spacing AND inter-spot angle
    (`diffraction_zone`): every spot gets a signed hkl on one reciprocal
    plane, so phases with similar plane spacings no longer tie. (The
    MATLAB prototype matched d only, ranked SrRuO3 first here and reported
    Silicon's zone as [-100]; exact parity is not a goal.)
    """
    sim = simulate("Silicon", zone_axis=(0, 0, 1), scattering_model="z")
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, acc_voltage=200)
    si = cands[0]
    assert si.phase_name == "Silicon" and si.method == "zone"
    assert si.score == 1.0 and si.n_matched == 12
    assert sorted(map(abs, si.zone_axis)) == [0.0, 0.0, 1.0]   # a <100> zone
    # signed hkls, all on that zone's plane (Weiss zone law h·uvw = 0)
    uvw = np.array(si.zone_axis)
    assert all(np.dot(h, uvw) == 0 for h in si.matched_hkl.tolist())
    assert {tuple(sorted(map(abs, h))) for h in si.matched_hkl.tolist()} <= {
        (0, 2, 2), (0, 0, 4), (0, 4, 4)}
    # Ge / GaAs share the lattice but their 200 spots are allowed (not
    # extinct) and absent here, so they score below Silicon
    every = index_spots(pos, (512, 512), pixel_size=0.05, camera_length=200,
                        acc_voltage=200, top_n=99)
    ge = next(c for c in every if c.phase_name == "Ge")
    assert ge.score < si.score


def test_index_no_match_scores_zero() -> None:
    pos = np.array([[257.0, 258.0]])                 # 1 px off-centre → huge d
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, tolerance=0.01)
    assert all(c.score == 0 for c in cands)


def test_index_matched_idx_maps_to_input_spots() -> None:
    """matched_idx (Diffraction #4 overlay/report) points into the input
    `positions`, and the indexed spot's d_meas = λL/r at that index."""
    sim = simulate("Silicon", zone_axis=(0, 0, 1), scattering_model="z")
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, acc_voltage=200)
    c = cands[0]
    assert c.phase_name == "Silicon"
    assert c.matched_idx.shape[0] == c.n_matched == c.matched_d.shape[0]
    # every index is a valid row of the input spot list
    assert c.matched_idx.min() >= 0 and c.matched_idx.max() < pos.shape[0]
    assert len(set(c.matched_idx.tolist())) == c.n_matched  # no spot used twice
    # the matched measured-d at each index reproduces d = λL/r from that spot's
    # radius (the relation the overlay/report rely on)
    from fermiviewer.calc.crystal import electron_wavelength
    lam = float(electron_wavelength(200))
    center = (512 // 2 + 1, 512 // 2 + 1)
    for k, i in enumerate(c.matched_idx.tolist()):
        r = float(np.hypot(pos[i, 0] - center[0], pos[i, 1] - center[1]))
        d_from_r = (lam * 200 * 1e7) / (r * 0.05 * 1e7)
        assert c.matched_d[k] == pytest.approx(d_from_r, rel=1e-6)


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


def test_index_ties_prefer_a_consistent_zone_axis() -> None:
    """Simulated Gold [001] at the simulator's own calibration: many phases
    tie at 1.0, and one whose hkls fit no zone ("[ ]") must not lead."""
    sim = simulate("Gold", zone_axis=(0, 0, 1))
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    cands = index_spots(pos, (512, 512), pixel_size=0.05,
                        camera_length=200, acc_voltage=200, top_n=10)
    assert cands[0].phase_name == "Gold"
    # a <100> zone (cubic: [001], [010] and [100] are the same pattern)
    assert cands[0].method == "zone"
    assert sorted(map(abs, cands[0].zone_axis)) == [0.0, 0.0, 1.0]
    zoned = [not np.isnan(c.zone_axis[0]) for c in cands if c.score == 1.0]
    assert zoned == sorted(zoned, reverse=True)  # every zoned tie first
