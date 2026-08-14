"""Integrated differential phase contrast (iDPC) from a calibrated COM field
(PLAN_4DSTEM #9).

`calc/fourd/dpc.py` turns a per-probe COM shift field (detector pixels) into
a calibrated beam-deflection-angle field in milliradians. iDPC goes one step
further: it treats that vector field as (proportional to) the GRADIENT of
the specimen's projected potential and inverts the gradient in Fourier
space to recover a single scan-shaped phase-contrast image, rather than a
per-probe vector. Reimplemented directly from Lazić, Bosch & Lazar, "Phase
contrast STEM for thin samples: Integrated differential phase contrast",
Ultramicroscopy 160 (2016) 265-280 — the paper that introduced the iDPC
name and method. py4DSTEM/pyxem (AGPL) were not consulted for this module.

THE INTEGRATION (a Frankot-Chellappa-style least-squares gradient
inversion — the standard way to invert a measured 2D gradient field in
Fourier space, also used for wavefront/transport-of-intensity
reconstruction): given a vector field ``(field_y, field_x)`` sampled on an
``(Ny, Nx)`` pixel grid, the discrete-Fourier derivative theorem says
``F[d psi/d row](omega_y, omega_x) = 1j * omega_y * F[psi]``, and likewise
for the column derivative, where ``omega = 2*pi*f`` and ``f`` is
``numpy.fft.fftfreq``'s cycles-per-pixel frequency. If ``(field_y,
field_x)`` were exactly ``(d psi/d row, d psi/d col)`` for some scalar
``psi``, then ``F[field_y] = 1j*omega_y*F[psi]`` and ``F[field_x] =
1j*omega_x*F[psi]``. Multiplying the first by ``omega_y``, the second by
``omega_x``, and adding gives the minimum-norm (least-squares) solution for
``F[psi]`` — exact when the field truly is a gradient, and the best
curl-free approximation otherwise (a measured COM field need not be exactly
conservative):

    F[psi](omega) = -1j * (omega_y*F[field_y] + omega_x*F[field_x])
                    / (omega_y**2 + omega_x**2)

with ``F[psi](0, 0)`` defined as exactly 0. This is not an approximation
this module makes reluctantly: the DC/mean term of ``psi`` is not, and
cannot be, recovered from a GRADIENT field at all (adding any constant to
``psi`` leaves its gradient, and therefore the measured field, unchanged) —
so the returned image is a phase-contrast map up to an UNKNOWN ADDITIVE
CONSTANT, full stop. This is why the tests compare mean-removed images
rather than asserting equality outright.

Coordinates and axis order follow this package's 0-based ``(ky, kx)`` ==
``(row, col)`` convention throughout — see `geometry.py`/`dpc.py`'s module
docstrings; NOT `calc/radial.py`'s 1-based MATLAB-port convention.

HIGH-PASS FILTER: the ``1/(omega_y**2 + omega_x**2)`` reconstruction kernel
is not only singular exactly at ``(0, 0)`` (handled above) but also LARGE at
every low-but-nonzero frequency, so any noise present there is amplified
far more than noise at higher frequencies — the literature's well-known
iDPC "bowl"/low-frequency-cloud artifact (a real consequence of inverting a
derivative, not a bug to code around). Following the paper's own
prescription of a high-pass filter, this module applies a Gaussian
high-pass in the SAME Fourier domain, before the inverse transform
(equivalent to filtering the reconstructed image afterward, by linearity,
but cheaper): ``H(f) = 1 - exp(-f**2 / (2 * high_pass_cutoff**2))``, where
``f = sqrt(f_y**2 + f_x**2)`` is `numpy.fft.fftfreq`'s own spatial
frequency in CYCLES PER SCAN PIXEL (0 at DC, 0.5 at Nyquist).
``high_pass_cutoff`` is a REQUIRED-to-have-a-value, caller-overridable
parameter — defaulted to `DEFAULT_HIGH_PASS_CUTOFF` (see its own comment
for the reasoning), never a hidden magic number a caller cannot see or
change: a scan with fine atomic-resolution detail may want a much smaller
cutoff than a coarse, noisier survey scan.

UNITS: given ``com_y_shift``/``com_x_shift`` in detector PIXELS (the same
maps `com.com_maps` returns) and the required ``mrad_per_px`` calibration
(see `dpc.py`'s module docstring for why this is never defaulted), this
module calibrates them into the milliradian field via
``dpc.calibrated_field_mrad`` (reused, not re-derived) BEFORE integrating,
so the returned image is in the SAME unit, MILLIRADIANS — the mirror image
of `dpc.divergence_map`'s own "per scan-pixel" convention run in reverse:
``divergence_map`` differentiates a mrad field with respect to the
scan-pixel INDEX (unit spacing, not a physical length) to get
mrad-per-scan-pixel; this module integrates a mrad field the same way, with
respect to the scan-pixel INDEX, so the "per scan-pixel" cancels back out
and the result is plain mrad again.

This iDPC image is PROPORTIONAL to the specimen's projected potential (its
phase image, up to the additive constant above) — it is NOT volts, and not
even an absolute phase in radians. Two further constants this module is
never given, and never invents, would be needed for that:

  1. The electron wavelength (equivalently, the accelerating voltage),
     which relates a deflection-angle field to a phase GRADIENT via the
     interaction constant ``sigma_e = 2*pi*m*e*lambda / h**2`` (``phase =
     sigma_e * V_proj``, ``beta = (lambda / 2*pi) * grad(phase)``).
  2. The physical scan-pixel pitch along BOTH scan axes — this module
     integrates with respect to the pixel INDEX, exactly as
     `dpc.divergence_map` differentiates (see its docstring) — needed to
     convert that index-space integration into a true real-space phase
     integral, and NOT assumed isotropic here: a dataset's two scan axes
     can carry different physical pitches (non-square scan step), so a
     single scalar would be wrong in general.

Neither is requested nor guessed here; multiply by the caller's own
constants (the accelerating voltage and the scan-axis calibration already
carried alongside every registered map) to go further.
"""

from __future__ import annotations

import numpy as np

from fermiviewer.calc.fourd.dpc import calibrated_field_mrad

__all__ = ["DEFAULT_HIGH_PASS_CUTOFF", "idpc_image"]

# Cycles per scan pixel (fftfreq-native units; Nyquist == 0.5). A Gaussian
# high-pass with this sigma has fallen to within 0.02% of full transmission
# by f = 0.1 cycles/px (a 10-scan-pixel period), so structure varying on the
# scale of a handful of scan pixels — where atomic-resolution 4D-STEM
# contrast actually lives — passes through essentially untouched, while the
# near-DC band responsible for the classic iDPC "bowl" artifact (see the
# module docstring) is suppressed. This is an engineering DEFAULT for this
# module, not a number handed down by the paper (which leaves the cutoff to
# the operator) — every caller can, and for anything but a first look
# should, retune it to their own scan's noise floor and feature size via the
# `high_pass_cutoff` parameter below.
DEFAULT_HIGH_PASS_CUTOFF = 0.02


def _validate_high_pass_cutoff(high_pass_cutoff: float) -> None:
    if not np.isfinite(high_pass_cutoff) or high_pass_cutoff < 0:
        raise ValueError(
            f"high_pass_cutoff must be a finite value >= 0, got {high_pass_cutoff}"
        )


def idpc_image(
    com_y_shift: np.ndarray,
    com_x_shift: np.ndarray,
    mrad_per_px: float,
    high_pass_cutoff: float = DEFAULT_HIGH_PASS_CUTOFF,
) -> np.ndarray:
    """Integrated DPC: Fourier-space integration of a calibrated COM field
    into a single scan-shaped phase-contrast image, with a Gaussian
    high-pass to suppress the low-frequency reconstruction artifact. See
    the module docstring for the full derivation, the units, and what an
    absolute potential in volts would additionally require.

    ``com_y_shift``/``com_x_shift`` are `calc.fourd.com.com_maps`'s output
    (detector pixels, shape ``(scan_y, scan_x)``); ``mrad_per_px`` is the
    required, explicit detector calibration (see `dpc.py`'s module
    docstring for why this is never defaulted). ``high_pass_cutoff`` is a
    spatial frequency in CYCLES PER SCAN PIXEL (``0 <= high_pass_cutoff``,
    ``0.5`` == Nyquist); ``0`` disables the low-frequency suppression
    entirely (the additive-constant/DC indeterminacy is unconditional, not
    a side effect of the filter, so the true DC term is still zeroed) —
    useful for seeing the raw artifact the filter exists to remove.

    Raises ``ValueError`` for a non-finite/non-positive ``mrad_per_px``, a
    non-finite/negative ``high_pass_cutoff``, mismatched
    ``com_y_shift``/``com_x_shift`` shapes, or a scan shape smaller than
    2x2 (a single scan row/column carries no in-plane gradient information
    along that axis to integrate).

    Returns a real-valued ``(scan_y, scan_x)`` array in MILLIRADIANS,
    proportional to the projected potential up to an unrecoverable additive
    constant (see the module docstring) — compare reconstructions with
    their mean removed, never as absolute values.
    """
    _validate_high_pass_cutoff(high_pass_cutoff)
    com_y_arr = np.asarray(com_y_shift, dtype=np.float64)
    com_x_arr = np.asarray(com_x_shift, dtype=np.float64)
    if com_y_arr.shape != com_x_arr.shape:
        raise ValueError(
            "com_y_shift/com_x_shift shape mismatch: "
            f"{com_y_arr.shape} != {com_x_arr.shape}"
        )
    if com_y_arr.ndim != 2 or com_y_arr.shape[0] < 2 or com_y_arr.shape[1] < 2:
        raise ValueError(
            "idpc_image requires a 2D field with at least 2 scan positions "
            f"along each axis, got shape {com_y_arr.shape}"
        )

    field_y, field_x = calibrated_field_mrad(com_y_arr, com_x_arr, mrad_per_px)

    ny, nx = field_y.shape
    freq_y = np.fft.fftfreq(ny)[:, None]  # cycles per scan pixel
    freq_x = np.fft.fftfreq(nx)[None, :]
    omega_y = 2.0 * np.pi * freq_y
    omega_x = 2.0 * np.pi * freq_x
    denom = omega_y**2 + omega_x**2
    # Dodge the 0/0 at exact DC: omega_y == omega_x == 0 there too, so the
    # numerator below is exactly 0 regardless of what finite placeholder
    # replaces the denominator — this is what pins F[psi](0, 0) at exactly
    # 0 (the additive constant this module cannot recover, see the module
    # docstring), not a special case bolted on afterward.
    denom_safe = np.where(denom == 0.0, 1.0, denom)

    fft_field_y = np.fft.fft2(field_y)
    fft_field_x = np.fft.fft2(field_x)
    fft_psi = -1j * (omega_y * fft_field_y + omega_x * fft_field_x) / denom_safe

    if high_pass_cutoff > 0:
        freq_sq = freq_y**2 + freq_x**2
        high_pass = 1.0 - np.exp(-freq_sq / (2.0 * high_pass_cutoff**2))
        fft_psi = fft_psi * high_pass

    return np.asarray(np.real(np.fft.ifft2(fft_psi)))
