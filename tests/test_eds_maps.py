"""EDS hypercube map tests — synthetic oracles + real BCF self-consistency."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eds_maps import element_map, extract_element_maps, pixel_spectrum
from fermiviewer.io.bcf import load_bcf

pytestmark = pytest.mark.eds


@pytest.fixture()
def synthetic_cube() -> tuple[np.ndarray, np.ndarray]:
    energy = np.arange(1024) * 0.01                      # 0–10.23 keV
    cube = np.full((4, 5, 1024), 2.0)                    # flat background
    # Fe Kα peak at 6.404 keV, amplitude varies by pixel
    peak = np.exp(-((energy - 6.404) ** 2) / (2 * 0.03**2))
    weights = (np.arange(20, dtype=np.float64).reshape(4, 5) + 1)[..., None]
    cube = cube + weights * peak * 50
    return cube, energy


@pytest.fixture()
def kramers_cube() -> tuple[np.ndarray, np.ndarray, float]:
    """Cube = per-pixel-scaled Kramers continuum + identical Fe-Kα peak.

    The continuum amplitude ramps across pixels; the peak is the same at
    every pixel. A correct bremsstrahlung subtraction removes the ramp and
    leaves the same net peak area at every pixel.
    """
    energy = np.linspace(0.1, 12.0, 1200)         # ~10 eV/channel
    e0 = 15.0
    cont = (e0 - energy) / energy                 # unit pure-Kramers shape
    amps = (np.arange(12, dtype=np.float64).reshape(3, 4) + 1.0)  # 1..12
    peak = np.exp(-0.5 * ((energy - 6.404) / 0.04) ** 2)
    cube = amps[..., None] * cont[None, None, :] + 500.0 * peak[None, None, :]
    return cube, energy, e0


def test_element_map_window_sum(synthetic_cube) -> None:
    cube, energy = synthetic_cube
    m = element_map(cube, energy, 6.3, 6.5)
    manual = cube[:, :, (energy >= 6.3) & (energy <= 6.5)].sum(axis=2)
    np.testing.assert_array_equal(m, manual)
    # swapped bounds normalise
    np.testing.assert_array_equal(element_map(cube, energy, 6.5, 6.3), m)


def test_element_map_linear_bg_removes_flat_background(synthetic_cube) -> None:
    cube, energy = synthetic_cube
    no_bg = element_map(cube, energy, 6.3, 6.5, bg="linear", bg_gap=0.1)
    # flat background of 2 counts/channel cancels exactly → pure peak counts
    peak_only = cube[:, :, (energy >= 6.3) & (energy <= 6.5)].sum(axis=2) \
        - 2.0 * ((energy >= 6.3) & (energy <= 6.5)).sum()
    np.testing.assert_allclose(no_bg, peak_only, atol=1e-6)


def test_element_map_bremsstrahlung_removes_continuum_ramp(kramers_cube) -> None:
    cube, energy, e0 = kramers_cube
    net = element_map(cube, energy, 6.254, 6.554, bg="bremsstrahlung",
                      bg_gap=0.05, e0_kev=e0)
    # the per-pixel continuum ramp is removed → identical net at every pixel,
    # equal to the (continuum-free) Gaussian window sum
    peak = (energy >= 6.254) & (energy <= 6.554)
    expected = 500.0 * np.exp(-0.5 * ((energy[peak] - 6.404) / 0.04) ** 2).sum()
    np.testing.assert_allclose(net, expected, rtol=2e-3)
    assert net.max() - net.min() < expected * 2e-3   # flat across the ramp


def test_element_map_bremsstrahlung_zero_on_pure_continuum() -> None:
    # a pure (peak-free) Kramers continuum: the fixed Kramers shape matches
    # it exactly, so a peak-free window nets to ~0 (the continuum is removed
    # by its own shape, where a linear chord would over-subtract a convex
    # continuum and clip to 0). Steep low-energy region exercises curvature.
    energy = np.linspace(0.1, 12.0, 1200)
    e0 = 15.0
    cube = (5.0 * (e0 - energy) / energy)[None, None, :].repeat(2, 0).repeat(2, 1)
    net = element_map(cube, energy, 1.0, 1.4, bg="bremsstrahlung", bg_gap=0.1, e0_kev=e0)
    assert np.abs(net).max() < 1e-6


def test_element_map_bremsstrahlung_requires_e0(kramers_cube) -> None:
    cube, energy, _e0 = kramers_cube
    with pytest.raises(ValueError, match="e0_kev"):
        element_map(cube, energy, 6.3, 6.5, bg="bremsstrahlung")


def test_element_map_bremsstrahlung_e0_must_exceed_window(kramers_cube) -> None:
    cube, energy, _e0 = kramers_cube
    with pytest.raises(ValueError, match="must exceed"):
        element_map(cube, energy, 6.3, 6.5, bg="bremsstrahlung", e0_kev=6.0)


def test_extract_element_maps_bremsstrahlung_passthrough(kramers_cube) -> None:
    cube, energy, e0 = kramers_cube
    entries = extract_element_maps(cube, energy, ["Fe"], half_window=0.15,
                                   bg="bremsstrahlung", beam_kv=200.0, e0_kev=e0)
    assert len(entries) == 1 and entries[0].total > 0


def test_pixel_spectrum_mask_oracle(synthetic_cube) -> None:
    cube, energy = synthetic_cube
    all_mask = np.ones(cube.shape[:2], dtype=bool)
    np.testing.assert_allclose(
        pixel_spectrum(cube, all_mask),
        np.asarray(cube, dtype=np.float64).sum(axis=(0, 1)),
        rtol=1e-12,
    )
    one = pixel_spectrum(cube, np.array([2]), np.array([3]))     # 1-based
    np.testing.assert_array_equal(one, cube[1, 2])
    # out-of-bounds pixels are dropped
    assert pixel_spectrum(cube, np.array([99]), np.array([99])).sum() == 0


def test_extract_element_maps_line_snap(synthetic_cube) -> None:
    cube, energy = synthetic_cube
    with pytest.warns(UserWarning, match="no known line for 'Xx'"):
        entries = extract_element_maps(cube, energy, ["Fe", "Xx"], half_window=0.1)
    assert len(entries) == 1                                     # Xx warned+skipped
    e = entries[0]
    assert e.symbol == "Fe" and e.line == "K"
    assert e.energy_kev == pytest.approx(6.404)
    assert e.total > 0
    # the Fe map ranks pixels by the injected weights
    assert e.map.argmax() == 19


@pytest.mark.golden
def test_real_bcf_cube_self_consistency(ml_datasets) -> None:
    ds = load_bcf(ml_datasets / "BCF" / "esprit_v2_50x50.bcf")
    cube = ds.data
    spec = pixel_spectrum(cube, np.ones(cube.shape[:2], dtype=bool))
    np.testing.assert_allclose(spec, ds.sum_spectrum(), rtol=1e-12)
    # element maps: use recorded elements when present, else a known
    # in-range line (this vector records no element list)
    elements = ds.metadata["elements"] or ["Si"]
    entries = extract_element_maps(cube, ds.energy_axis, elements)
    assert entries
    assert all(e.map.shape == cube.shape[:2] for e in entries)
