"""Tests for model-based multi-edge EELS fitting (PLAN_SPECTRAL_QUANT #2).

Validation is by (a) parity of the differential edge shape with the
existing window-integration cross-section, and (b) recovery of known at%
from synthetic model spectra. No MATLAB goldens (the predecessor has no
model-fit path).
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eels_model import (
    edge_shape_fn,
    fit_edges,
    fit_edges_map,
)
from fermiviewer.calc.eels_quant import ElementEdge, cross_section

pytestmark = pytest.mark.eels


def _edge(element: str, shell: str, z: int, onset: float) -> ElementEdge:
    return ElementEdge(
        element=element, shell=shell, z=z, onset_ev=onset,
        signal_window=(onset, onset + 100.0),
        bg_window=(onset - 80.0, onset - 10.0),
    )


def test_edge_shape_integral_matches_cross_section() -> None:
    # the per-channel shape, integrated over a window, reproduces the
    # window-integration cross_section() (same Egerton integrand, same
    # 5 keV normalisation floor for Δ ≤ 100 eV)
    z, shell, onset, e0, beta, delta = 8, "K", 532.0, 200.0, 10.0, 80.0
    fn = edge_shape_fn(z, shell, e0, beta, onset)
    e = np.linspace(onset, onset + delta, 400)
    got = float(np.trapezoid(fn(e), e))
    expected = cross_section(z, shell, e0, beta, delta, onset)
    assert got == pytest.approx(expected, rel=1e-9)


def test_edge_shape_zero_below_onset() -> None:
    fn = edge_shape_fn(8, "K", 200.0, 10.0, 532.0)  # z, shell, e0, beta, onset
    e = np.linspace(400.0, 700.0, 300)
    shape = fn(e)
    assert np.all(shape[e < 532.0] == 0.0)
    assert np.any(shape[e >= 532.0] > 0.0)


def _synth(energy, edges, areal, bg_amp=5.0e5, r=3.0):
    """power-law bg + Σ areal_X · dσ_X/dE — the model's own generator."""
    spec = bg_amp * np.power(np.maximum(energy, 1e-12), -r)
    for el, n in zip(edges, areal, strict=True):
        fn = edge_shape_fn(el.z, el.shell, 200.0, 10.0, el.onset_ev)
        spec = spec + n * fn(energy)
    return spec


def test_recovers_at_percent_two_edges() -> None:
    energy = np.linspace(250.0, 950.0, 700)
    edges = [_edge("O", "K", 8, 532.0), _edge("Fe", "L", 26, 708.0)]
    # areal densities 2 : 1 → at% 66.7 / 33.3
    spec = _synth(energy, edges, areal=[2.0e27, 1.0e27])
    r = fit_edges(energy, spec, edges, e0_kv=200.0, beta_mrad=10.0)
    assert r.success
    assert r.elements == ["O", "Fe"]
    assert r.atomic_percent[0] == pytest.approx(66.667, abs=0.5)
    assert r.atomic_percent[1] == pytest.approx(33.333, abs=0.5)
    assert r.amplitude_errors.shape == (2,)
    # per-edge curves + bg sum to the model
    np.testing.assert_allclose(
        r.model, r.background + r.edge_curves.sum(axis=0), rtol=1e-9
    )


def test_resolves_overlapping_edges() -> None:
    # Mn-L (640) and Fe-L (708): signal windows overlap (708–740), which
    # window-integration mis-assigns; the joint model separates them
    energy = np.linspace(400.0, 950.0, 800)
    edges = [_edge("Mn", "L", 25, 640.0), _edge("Fe", "L", 26, 708.0)]
    spec = _synth(energy, edges, areal=[3.0e27, 1.0e27])  # 75 / 25
    r = fit_edges(energy, spec, edges, e0_kv=200.0, beta_mrad=10.0)
    assert r.success
    assert r.atomic_percent[0] == pytest.approx(75.0, abs=1.0)
    assert r.atomic_percent[1] == pytest.approx(25.0, abs=1.0)


def test_fit_edges_map_uniform_matches_scalar() -> None:
    energy = np.linspace(250.0, 950.0, 500)
    edges = [_edge("O", "K", 8, 532.0), _edge("Fe", "L", 26, 708.0)]
    spec = _synth(energy, edges, areal=[2.0e27, 1.0e27])
    scalar = fit_edges(energy, spec, edges, e0_kv=200.0, beta_mrad=10.0)
    cube = np.broadcast_to(spec, (4, 5, energy.size)).copy()
    mp = fit_edges_map(cube, energy, edges, e0_kv=200.0, beta_mrad=10.0)
    assert mp.atomic_percent.shape == (4, 5, 2)
    # every pixel ≈ the scalar at% (linear fixed-r solve vs nonlinear fit)
    assert mp.atomic_percent[..., 0] == pytest.approx(
        scalar.atomic_percent[0], abs=1.0
    )
    assert np.ptp(mp.atomic_percent[..., 0]) < 1e-6   # uniform across pixels


def test_fit_edges_map_two_regions() -> None:
    energy = np.linspace(250.0, 950.0, 500)
    edges = [_edge("O", "K", 8, 532.0), _edge("Fe", "L", 26, 708.0)]
    left = _synth(energy, edges, areal=[3.0e27, 1.0e27])   # O-rich
    right = _synth(energy, edges, areal=[1.0e27, 3.0e27])  # Fe-rich
    cube = np.empty((2, 2, energy.size))
    cube[:, 0, :] = left
    cube[:, 1, :] = right
    mp = fit_edges_map(cube, energy, edges, e0_kv=200.0, beta_mrad=10.0)
    o_left = mp.atomic_percent[0, 0, 0]
    o_right = mp.atomic_percent[0, 1, 0]
    assert o_left > 60.0 > o_right          # O dominant left, minor right
    assert o_left == pytest.approx(75.0, abs=3.0)
    assert o_right == pytest.approx(25.0, abs=3.0)


def test_validation_errors() -> None:
    energy = np.linspace(250.0, 950.0, 100)
    with pytest.raises(ValueError):
        fit_edges(energy, energy[:-1], [_edge("O", "K", 8, 532.0)],
                  e0_kv=200.0, beta_mrad=10.0)
    with pytest.raises(ValueError):
        fit_edges(energy, energy, [], e0_kv=200.0, beta_mrad=10.0)
    with pytest.raises(ValueError):
        fit_edges_map(energy, energy, [_edge("O", "K", 8, 532.0)],
                      e0_kv=200.0, beta_mrad=10.0)  # not a cube
