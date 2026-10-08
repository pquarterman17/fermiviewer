"""Zone-axis spot indexing (`calc/diffraction_zone`) and the simulator's
real-space beam direction it is checked against."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.crystal import electron_wavelength, find_phase
from fermiviewer.calc.diffraction import index_spots, simulate
from fermiviewer.calc.diffraction_zone import reciprocal_vectors

KW = dict(pixel_size=0.05, camera_length=200, acc_voltage=200)


def _spots(name: str, zone: tuple[int, int, int]) -> np.ndarray:
    sim = simulate(name, zone_axis=zone)
    return np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])


@pytest.mark.parametrize("zone", [(1, 1, 1), (1, 1, 0), (2, 1, 0)])
def test_simulated_spots_sit_at_their_true_reciprocal_length(zone) -> None:
    """The pattern plane is perpendicular to u·a + v·b + w·c, so every spot
    lies |g| = 1/d from the beam. (Treating [uvw] as Cartesian projected
    hexagonal off-axis zones onto a tilted plane and shortened spots.)"""
    sim = simulate("Titanium (HCP)", zone_axis=zone)
    scale = float(electron_wavelength(200)) * 200 / 0.05
    beam = sim.spots[0]
    for s in sim.spots[1:]:
        r = np.hypot(s.pixel_row - beam.pixel_row, s.pixel_col - beam.pixel_col)
        assert r / scale == pytest.approx(1 / s.d_spacing, rel=1e-9)


def test_hexagonal_off_axis_zone_indexes_consistently() -> None:
    cands = index_spots(_spots("Titanium (HCP)", (1, 1, 1)), (512, 512), **KW)
    ti = cands[0]
    assert ti.phase_name == "Titanium (HCP)" and ti.method == "zone"
    assert ti.score == 1.0
    uvw = np.array(ti.zone_axis)
    assert all(np.dot(h, uvw) == 0 for h in ti.matched_hkl.tolist())
    # each signed hkl reproduces its spot's d-spacing
    _, _, direct = reciprocal_vectors(find_phase("Titanium (HCP)"), 1)
    recip = np.linalg.inv(direct).T
    d = 1 / np.linalg.norm(ti.matched_hkl @ recip, axis=1)
    np.testing.assert_allclose(d, ti.ref_d, rtol=1e-9)


def test_ring_like_spots_fall_back_to_d_spacing() -> None:
    """Spots at Silicon ring radii but random azimuths form no lattice, so
    the d-only result stands (no zone is invented)."""
    rng = np.random.default_rng(1)
    scale = float(electron_wavelength(200)) * 200 / 0.05
    d = np.repeat([3.1356, 1.9201, 1.6375], 3)          # 111, 220, 311
    phi = rng.uniform(0, 2 * np.pi, d.size)
    pos = np.column_stack([257 + scale / d * np.sin(phi), 257 + scale / d * np.cos(phi)])
    cands = index_spots(pos, (512, 512), **KW)
    assert all(c.method == "d-spacing" for c in cands)
    assert cands[0].score == 1.0
