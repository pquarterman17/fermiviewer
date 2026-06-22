"""EELS advanced deconvolution tests: sub-pixel ZLP align, Fourier-ratio,
Richardson-Lucy — synthetic oracles (no external data)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eels_advanced import (
    align_zlp,
    fourier_ratio,
    richardson_lucy,
)

pytestmark = pytest.mark.eels


def _gauss(x: np.ndarray, center: float, sigma: float, amp: float = 1.0) -> np.ndarray:
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def _half_max_width(y: np.ndarray) -> int:
    return int((y >= 0.5 * y.max()).sum())


# ── sub-pixel ZLP alignment ──────────────────────────────────────────

def test_align_zlp_subpixel_recovers_fractional_shift() -> None:
    ne = 64
    energy = np.arange(ne, dtype=np.float64) - 32.0   # E=0 at channel 32
    ref_zlp = _gauss(energy, 0.0, 3.0)                # clean reference ZLP
    cube = np.zeros((2, 2, ne))
    cube[:] = ref_zlp
    # pixel (0,1) shifted by +2.3 channels (fractional)
    cube[0, 1] = _gauss(energy, 2.3, 3.0)

    aligned, shifts = align_zlp(
        cube, energy, window=(-20, 20), reference=ref_zlp, subpixel=True,
    )
    assert shifts.dtype.kind == "f"                   # float shifts in subpixel mode
    # the shifted pixel is brought back by ≈ -2.3 channels, to < 0.1 channel
    assert shifts[0, 1] == pytest.approx(-2.3, abs=0.1)
    # unshifted pixels barely move
    assert abs(shifts[0, 0]) < 0.1


def test_align_zlp_integer_path_unchanged() -> None:
    ne = 64
    energy = np.arange(ne, dtype=np.float64) - 32.0
    ref_zlp = _gauss(energy, 0.0, 3.0)
    cube = np.zeros((2, 2, ne))
    cube[:] = ref_zlp
    cube[0, 1] = _gauss(energy, 2.3, 3.0)
    _aligned, shifts = align_zlp(cube, energy, reference=ref_zlp)  # integer default
    assert shifts.dtype == np.int32
    assert shifts[0, 1] == -2                          # 2.3 rounds to the integer peak


# ── Fourier-ratio deconvolution ──────────────────────────────────────

def test_fourier_ratio_suppresses_plural_scattering() -> None:
    ne = 256
    energy = np.arange(ne, dtype=np.float64)           # E=0 at channel 0
    zlp = _gauss(energy, 0.0, 2.0)
    plasmon = _gauss(energy, 20.0, 3.0, amp=0.4)       # single plasmon replica
    low = zlp + plasmon
    single = _gauss(energy, 100.0, 3.0)                # the true core-loss edge
    low_norm = low / low.sum()

    n2 = 1 << int(np.ceil(np.log2(2 * ne)))
    core = np.fft.ifft(np.fft.fft(single, n2) * np.fft.fft(low_norm, n2)).real[:ne]

    ssd = fourier_ratio(energy, core, low, zlp_window=(-3, 3))

    # the plasmon replica at edge+20 is strongly suppressed relative to the edge
    ratio_core = core[120] / core[100]
    ratio_ssd = ssd[120] / ssd[100]
    assert ratio_ssd < 0.3 * ratio_core
    # the single-scattering peak sits at the edge channel
    assert abs(int(np.argmax(ssd)) - 100) <= 2


def test_fourier_ratio_length_mismatch_raises() -> None:
    e = np.arange(10.0)
    with pytest.raises(ValueError, match="equal length"):
        fourier_ratio(e, np.arange(10.0), np.arange(9.0))


def test_fourier_ratio_tiny_zlp_window_raises() -> None:
    e = np.arange(10.0) + 50.0     # no channels in (-5,5)
    with pytest.raises(ValueError, match="ZLP window"):
        fourier_ratio(e, np.ones(10), np.ones(10))


# ── Richardson-Lucy deconvolution ────────────────────────────────────

def test_richardson_lucy_sharpens_a_broadened_peak() -> None:
    ne = 128
    x = np.arange(ne, dtype=np.float64)
    true = _gauss(x, 64.0, 1.5)                        # sharp feature
    psf = _gauss(x, 64.0, 4.0)                         # centred broadening kernel
    observed = np.convolve(true, psf / psf.sum(), mode="same")

    rl = richardson_lucy(observed, psf, iterations=40)

    assert abs(int(np.argmax(rl)) - 64) <= 1           # peak preserved
    assert rl.max() > observed.max()                   # RL concentrates the peak
    assert _half_max_width(rl) < _half_max_width(observed)  # sharper than observed


def test_richardson_lucy_psf_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="psf must match"):
        richardson_lucy(np.ones(10), np.ones(9))


def test_richardson_lucy_zero_psf_raises() -> None:
    with pytest.raises(ValueError, match="positive sum"):
        richardson_lucy(np.ones(8), np.zeros(8))


def test_richardson_lucy_nonnegative() -> None:
    rng = np.random.default_rng(0)
    ne = 64
    x = np.arange(ne, dtype=np.float64)
    psf = _gauss(x, 32.0, 3.0)
    observed = np.convolve(_gauss(x, 32.0, 1.0), psf / psf.sum(), mode="same")
    observed = observed + rng.normal(0, 1e-3, ne)
    rl = richardson_lucy(observed, psf, iterations=10)
    assert np.all(rl >= 0.0)
