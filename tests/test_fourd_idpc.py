"""Pure-math tests for iDPC (calc/fourd/idpc.py, PLAN_4DSTEM #9).

Per the task brief, the core property under test is: iDPC of a KNOWN
potential reconstructs its phase up to an additive constant. A pure
sinusoidal potential is the natural fixture — its frequency is an exact
DFT bin (an integer number of cycles across the grid), so the Fourier-space
gradient-inversion this module performs is analytically EXACT for it (no
aliasing/spectral leakage), letting the reconstruction be checked to a tight
tolerance rather than a loose approximate one. Both sides of every
comparison have their mean removed first — the DC term is exactly what
`idpc_image` cannot recover (see the module docstring) — so a raw equality
assertion would be simply wrong, not just imprecise.

No corpus, no server: hand-checkable synthetic arrays only.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.fourd.idpc import DEFAULT_HIGH_PASS_CUTOFF, idpc_image

# ════════════════════════════════════════════════════════════════════
# known potential -> reconstructed up to an additive constant
# ════════════════════════════════════════════════════════════════════

_NY, _NX = 24, 32
_P, _Q = 2, 3  # integer cycle counts -> exact DFT bin, no spectral leakage
_AMPLITUDE = 5.0
_DC_OFFSET = 7.5  # baked into the "true" potential to prove it is discarded
_MRAD_PER_PX = 2.5


def _known_potential_and_field() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A pure 2D sinusoid ``psi`` (an exact DFT bin, plus an arbitrary DC
    offset) and its ANALYTIC gradient, split into a raw COM-pixel field so
    that feeding it through `idpc_image`'s ``mrad_per_px`` calibration
    round-trips back to the same physical field. Returns
    ``(psi_true, com_y_shift, com_x_shift)``."""
    y = np.arange(_NY, dtype=np.float64)[:, None]
    x = np.arange(_NX, dtype=np.float64)[None, :]
    phase = 2.0 * np.pi * (_P * y / _NY + _Q * x / _NX)
    psi_true = _AMPLITUDE * np.sin(phase) + _DC_OFFSET

    d_psi_dy = _AMPLITUDE * (2.0 * np.pi * _P / _NY) * np.cos(phase)
    d_psi_dx = _AMPLITUDE * (2.0 * np.pi * _Q / _NX) * np.cos(phase)
    # idpc_image calibrates com_*_shift by mrad_per_px internally — pass the
    # field pre-divided so the CALIBRATED field equals the analytic gradient.
    com_y_shift = d_psi_dy / _MRAD_PER_PX
    com_x_shift = d_psi_dx / _MRAD_PER_PX
    return psi_true, com_y_shift, com_x_shift


def test_idpc_reconstructs_known_sinusoidal_potential_up_to_mean_no_high_pass() -> None:
    """With the high-pass disabled (cutoff=0), a signal that is an exact
    DFT bin is reconstructed EXACTLY (to floating-point precision) — the
    strongest form of "up to an additive constant" this module can claim."""
    psi_true, com_y, com_x = _known_potential_and_field()
    reconstructed = idpc_image(com_y, com_x, _MRAD_PER_PX, high_pass_cutoff=0.0)
    np.testing.assert_allclose(
        reconstructed - reconstructed.mean(),
        psi_true - psi_true.mean(),
        atol=1e-9,
    )


def test_idpc_reconstructs_known_potential_at_default_cutoff() -> None:
    """The module's DEFAULT high-pass cutoff is far below this fixture's
    signal frequency (see the module docstring's own reasoning for the
    default), so it should barely perturb a real signal at all — checked
    with a looser, but still tight, tolerance than the cutoff=0 case."""
    psi_true, com_y, com_x = _known_potential_and_field()
    reconstructed = idpc_image(
        com_y, com_x, _MRAD_PER_PX, high_pass_cutoff=DEFAULT_HIGH_PASS_CUTOFF
    )
    np.testing.assert_allclose(
        reconstructed - reconstructed.mean(),
        psi_true - psi_true.mean(),
        atol=1e-6,
    )


def test_idpc_reconstruction_mean_is_always_zero() -> None:
    """`idpc_image` cannot recover the DC term (see the module docstring) —
    it does not merely happen to match a zero-mean fixture, it ALWAYS
    zeroes the k=(0,0) Fourier bin, so the reconstructed image's own mean
    is (up to float noise) exactly zero regardless of the input field."""
    _, com_y, com_x = _known_potential_and_field()
    reconstructed = idpc_image(com_y, com_x, _MRAD_PER_PX)
    assert reconstructed.mean() == pytest.approx(0.0, abs=1e-9)


def test_idpc_scales_with_mrad_per_px_calibration() -> None:
    """Doubling the calibration must exactly double the reconstructed
    field (and therefore the image) — the whole pipeline is linear."""
    _, com_y, com_x = _known_potential_and_field()
    low = idpc_image(com_y, com_x, mrad_per_px=1.0, high_pass_cutoff=0.0)
    high = idpc_image(com_y, com_x, mrad_per_px=2.0, high_pass_cutoff=0.0)
    np.testing.assert_allclose(high, 2.0 * low, atol=1e-9)


# ════════════════════════════════════════════════════════════════════
# high-pass filter actually suppresses the low-frequency artifact
# ════════════════════════════════════════════════════════════════════


def test_default_high_pass_cutoff_suppresses_a_low_frequency_signal() -> None:
    """A pure sinusoidal potential whose frequency sits WELL INSIDE the
    default cutoff (1 cycle across a 200-pixel scan -> f = 1/200 = 0.005,
    a quarter of DEFAULT_HIGH_PASS_CUTOFF = 0.02 — deliberately chosen for
    this test, not a byproduct of grid size) is barely visible after the
    high-pass, while the SAME field with the filter disabled (cutoff=0)
    reconstructs it at essentially its full analytic amplitude — proof the
    amplitude drop is the filter actually suppressing a low frequency, not
    a defect in the underlying integration (which the cutoff=0 half of
    this comparison independently confirms is fine)."""
    ny, nx = 200, 200
    p = 1
    amplitude = 3.0
    y = np.arange(ny, dtype=np.float64)[:, None]
    phase = 2.0 * np.pi * p * y / ny
    d_psi_dy = amplitude * (2.0 * np.pi * p / ny) * np.cos(phase)
    field_y = np.broadcast_to(d_psi_dy, (ny, nx)).copy()
    field_x = np.zeros((ny, nx))

    unfiltered = idpc_image(field_y, field_x, mrad_per_px=1.0, high_pass_cutoff=0.0)
    filtered = idpc_image(
        field_y, field_x, mrad_per_px=1.0, high_pass_cutoff=DEFAULT_HIGH_PASS_CUTOFF
    )
    # cutoff=0 recovers the known peak-to-peak amplitude (2 * amplitude)...
    assert np.ptp(unfiltered) == pytest.approx(2.0 * amplitude, rel=0.02)
    # ...while the default cutoff crushes the SAME signal to a small
    # fraction of it (analytically H(f=0.005) ~= 0.031 at cutoff=0.02)
    assert np.ptp(filtered) < 0.1 * np.ptp(unfiltered)


def test_high_pass_cutoff_zero_disables_filtering_but_still_zeroes_dc() -> None:
    """cutoff=0 is documented as "no suppression, DC still removed" — not
    "no-op equal to some other cutoff". Confirm the DC term is zero even
    with filtering fully disabled."""
    rng = np.random.default_rng(1)
    field_y = rng.normal(size=(10, 10))
    field_x = rng.normal(size=(10, 10))
    reconstructed = idpc_image(field_y, field_x, mrad_per_px=1.0, high_pass_cutoff=0.0)
    assert reconstructed.mean() == pytest.approx(0.0, abs=1e-9)


# ════════════════════════════════════════════════════════════════════
# validation
# ════════════════════════════════════════════════════════════════════


def test_idpc_rejects_shape_mismatch() -> None:
    com_y = np.zeros((5, 5))
    com_x = np.zeros((5, 6))
    with pytest.raises(ValueError, match="shape mismatch"):
        idpc_image(com_y, com_x, mrad_per_px=1.0)


@pytest.mark.parametrize("shape", [(1, 5), (5, 1), (1, 1)])
def test_idpc_rejects_scan_shape_too_small(shape: tuple[int, int]) -> None:
    com_y = np.zeros(shape)
    com_x = np.zeros(shape)
    with pytest.raises(ValueError, match="at least 2 scan positions"):
        idpc_image(com_y, com_x, mrad_per_px=1.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_idpc_propagates_invalid_mrad_per_px(bad: float) -> None:
    com_y = np.zeros((3, 3))
    com_x = np.zeros((3, 3))
    with pytest.raises(ValueError, match="mrad_per_px"):
        idpc_image(com_y, com_x, mrad_per_px=bad)


@pytest.mark.parametrize("bad", [-1.0, -0.001, float("nan"), float("inf")])
def test_idpc_rejects_invalid_high_pass_cutoff(bad: float) -> None:
    com_y = np.zeros((3, 3))
    com_x = np.zeros((3, 3))
    with pytest.raises(ValueError, match="high_pass_cutoff"):
        idpc_image(com_y, com_x, mrad_per_px=1.0, high_pass_cutoff=bad)


# ════════════════════════════════════════════════════════════════════
# units: the output carries a scan pixel, so it scales with scan sampling
# ════════════════════════════════════════════════════════════════════


def test_output_scales_with_scan_sampling_because_the_unit_carries_a_pixel() -> None:
    """The integration is with respect to the scan-pixel INDEX, so the
    result is mrad * SCAN PIXEL, not plain mrad — and that unit is not
    cosmetic: it predicts that sampling the SAME underlying continuous
    field twice as finely doubles every value.

    Two scans image one continuous sinusoid of fixed physical period.
    The coarse scan samples it over `ny` points, the fine scan over
    `2*ny` — same specimen, same field, half the scan step. The mrad
    field sampled at each probe is IDENTICAL in value at matching
    positions (a deflection angle is a physical quantity; it does not
    care how finely you sample it), but the reconstructed potential
    differs by exactly the step ratio, because each output value is an
    integral accumulated per scan pixel.

    A reconstruction genuinely in plain mrad would be invariant here.
    This asserts it is NOT — pinning the documented unit against a
    regression that would silently relabel a sampling-dependent number
    as a physical one.
    """
    cycles = 2
    amp_mrad = 1.0

    def field_for(n: int) -> tuple[np.ndarray, np.ndarray]:
        """One continuous sinusoidal deflection field, sampled at n points
        across the same physical extent."""
        y = np.arange(n, dtype=np.float64)[:, None]
        field_y = amp_mrad * np.cos(2.0 * np.pi * cycles * y / n)
        return np.broadcast_to(field_y, (n, n)).copy(), np.zeros((n, n))

    coarse_y, coarse_x = field_for(64)
    fine_y, fine_x = field_for(128)
    # the sampled field itself is unchanged at matching probe positions
    np.testing.assert_allclose(coarse_y[:, 0], fine_y[::2, 0], atol=1e-12)

    coarse = idpc_image(coarse_y, coarse_x, mrad_per_px=1.0, high_pass_cutoff=0.0)
    fine = idpc_image(fine_y, fine_x, mrad_per_px=1.0, high_pass_cutoff=0.0)

    # halving the scan step doubles the reconstruction: one scan pixel of
    # unit carried through the integration
    assert np.ptp(fine) == pytest.approx(2.0 * np.ptp(coarse), rel=1e-9)
