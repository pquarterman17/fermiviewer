"""EELS advanced analysis: ZLP alignment, Fourier-log deconvolution,
Kramers-Kronig dielectric analysis, SVD/MSA decomposition.

Port of fermi-viewer's +imaging/+eels/ (advanced half). Pure library.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "KKResult", "SVDResult", "align_zlp", "fourier_log", "fourier_ratio",
    "kramers_kronig", "richardson_lucy", "svd",
]

_EPS = np.finfo(np.float64).eps


def _parabolic_offset(xc: np.ndarray, peak: np.ndarray) -> np.ndarray:
    """Sub-sample peak offset in [-0.5, 0.5] from a 3-point parabolic fit
    around each column's argmax (circular neighbours)."""
    nfft = xc.shape[0]
    cols = np.arange(xc.shape[1])
    y0 = xc[(peak - 1) % nfft, cols]
    y1 = xc[peak, cols]
    y2 = xc[(peak + 1) % nfft, cols]
    denom = y0 - 2.0 * y1 + y2
    frac = np.zeros_like(y1)
    nz = np.abs(denom) > _EPS
    frac[nz] = 0.5 * (y0[nz] - y2[nz]) / denom[nz]
    return np.asarray(np.clip(frac, -0.5, 0.5), dtype=np.float64)


def _fractional_shift(cube_d: np.ndarray, shift: np.ndarray) -> np.ndarray:
    """Shift each pixel's spectrum by a fractional channel count via an FFT
    phase ramp. Sign matches ``np.roll`` (positive → toward higher channel),
    so integer shifts reproduce the integer-alignment path exactly."""
    ny, nx, ne = cube_d.shape
    flat = cube_d.reshape(ny * nx, ne)
    s = shift.reshape(-1)
    k = np.fft.fftfreq(ne)
    spec = np.fft.fft(flat, axis=1)
    phase = np.exp(-2j * np.pi * k[None, :] * s[:, None])
    shifted = np.fft.ifft(spec * phase, axis=1).real
    return shifted.reshape(ny, nx, ne)


# ════════════════════════════════════════════════════════════════════
def align_zlp(
    cube: np.ndarray,
    energy: np.ndarray,
    window: tuple[float, float] = (-20.0, 20.0),
    reference: str | np.ndarray = "mean",
    subpixel: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """ZLP alignment via FFT cross-correlation (port of eelsAlignZLP.m).

    Returns ``(aligned_cube, shifts[Ny,Nx])``. With ``subpixel`` the
    cross-correlation peak is refined by parabolic interpolation and the
    fractional shift applied via an FFT phase ramp; ``shifts`` is then a
    float array. The default integer path is byte-identical to the port
    (goldens unchanged)."""
    cube_in = np.asarray(cube)
    cube_d = cube_in.astype(np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    ny, nx, ne = cube_d.shape
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")

    win_mask = (energy >= window[0]) & (energy <= window[1])
    n_win = int(win_mask.sum())
    if n_win < 3:
        raise ValueError("alignment window spans fewer than 3 channels")

    flat = cube_d.reshape(ny * nx, ne).T          # [nE, Np]
    zlp = flat[win_mask]                          # [nWin, Np]

    if isinstance(reference, str):
        if reference == "mean":
            ref = zlp.mean(axis=1)
        elif reference == "max":
            ref = zlp[:, int(zlp.sum(axis=0).argmax())]
        else:
            raise ValueError("reference must be 'mean', 'max', or a vector")
    else:
        ref_full = np.asarray(reference, dtype=np.float64).ravel()
        if ref_full.size != ne:
            raise ValueError("custom reference must match channel count")
        ref = ref_full[win_mask]

    nfft = 2 * n_win - 1
    ref_f = np.conj(np.fft.fft(ref, nfft))
    xc = np.fft.ifft(np.fft.fft(zlp, nfft, axis=0) * ref_f[:, None], axis=0).real
    peak = xc.argmax(axis=0)                       # [Np], 0-based circular
    lag = np.where(peak > n_win - 1, peak - nfft, peak)

    if subpixel:
        frac = _parabolic_offset(xc, peak)
        shifts_f = (-(lag.astype(np.float64) + frac)).reshape(ny, nx)
        aligned = _fractional_shift(cube_d, shifts_f)
        if cube_in.dtype != np.float64:
            aligned = aligned.astype(cube_in.dtype)
        return aligned, shifts_f

    shifts = (-lag).astype(np.int32).reshape(ny, nx)
    aligned = cube_d.copy()
    for s in np.unique(shifts):
        if s == 0:
            continue
        sel = shifts == s
        aligned[sel] = np.roll(cube_d[sel], int(s), axis=-1)

    if cube_in.dtype != np.float64:
        aligned = aligned.astype(cube_in.dtype)
    return aligned, shifts


# ════════════════════════════════════════════════════════════════════
def fourier_log(
    energy: np.ndarray,
    spectrum: np.ndarray,
    zlp_window: tuple[float, float] = (-5.0, 5.0),
    zlp_ref: np.ndarray | None = None,
    regularize: float = 1e-6,
) -> tuple[np.ndarray, float]:
    """Fourier-log plural-scattering removal (port of eelsFourierLog.m).
    Returns (single_scattering_distribution, t_over_lambda)."""
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    n = energy.size
    if spectrum.size != n:
        raise ValueError("energy and spectrum must have equal length")

    if zlp_ref is None:
        mask = (energy >= zlp_window[0]) & (energy <= zlp_window[1])
        if mask.sum() < 2:
            raise ValueError("ZLP window has fewer than 2 channels")
        zlp = np.zeros(n)
        zlp[mask] = spectrum[mask]
    else:
        zlp = np.asarray(zlp_ref, dtype=np.float64).ravel()
        if zlp.size != n:
            raise ValueError("zlp_ref must match spectrum length")

    spec_g = np.maximum(spectrum, _EPS)
    zlp_g = np.maximum(zlp, _EPS)
    t_over_lambda = float(np.log(spec_g.sum() / zlp_g.sum()))

    n2 = 1 << int(np.ceil(np.log2(2 * n)))
    s = np.fft.fft(spec_g, n2)
    z = np.fft.fft(zlp_g, n2)

    z_thresh = regularize * np.abs(z).max()
    small = np.abs(z) < z_thresh
    z[small] = z_thresh * np.exp(1j * np.angle(z[small]))

    ratio = s / z
    r_thresh = regularize * np.abs(ratio).max()
    small_r = np.abs(ratio) < r_thresh
    ratio[small_r] = r_thresh * np.exp(1j * np.angle(ratio[small_r]))

    ssd = np.fft.ifft(z * np.log(ratio)).real[:n]
    return np.maximum(ssd, 0.0), t_over_lambda


# ════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class KKResult:
    energy: np.ndarray
    eps1: np.ndarray
    eps2: np.ndarray
    elf: np.ndarray
    optical_conductivity: np.ndarray
    refractive_index: np.ndarray
    thickness: float
    t_over_lambda: float


def kramers_kronig(
    energy: np.ndarray,
    spectrum: np.ndarray,
    zlp_window: tuple[float, float] = (-5.0, 5.0),
    refractive_index: float = float("nan"),
    collection_angle: float = 10.0,
    acc_voltage: float = 200.0,
    thickness: float = float("nan"),
) -> KKResult:
    """Dielectric function via Kramers-Kronig (port of eelsKramersKronig.m,
    Egerton Ch. 4). FFT-based Hilbert transform of the normalised
    energy-loss function."""
    e_charge, hbar, eps0 = 1.602e-19, 1.055e-34, 8.854e-12

    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    if spectrum.size != energy.size:
        raise ValueError("energy and spectrum must have equal length")

    zlp_mask = (energy >= zlp_window[0]) & (energy <= zlp_window[1])
    if not zlp_mask.any():
        raise ValueError("ZLP window contains no channels")
    i0 = spectrum[zlp_mask].sum()
    i_total = np.maximum(spectrum, 0).sum()
    t_lambda = float(np.log(max(i_total / i0, 1 + _EPS))) if i0 > 0 else 0.0

    spec = np.maximum(spectrum, 0.0)
    spec[zlp_mask] = 0.0
    pos = energy > 0
    if pos.sum() < 4:
        raise ValueError("fewer than 4 channels with E > 0")
    e = energy[pos]
    s = spec[pos]
    m = e.size

    de = np.empty(m)
    de[0] = e[1] - e[0]
    de[-1] = e[-1] - e[-2]
    de[1:-1] = (e[2:] - e[:-2]) / 2

    raw_integral = float((s * de / np.maximum(e, _EPS)).sum())
    if not np.isfinite(refractive_index) or refractive_index <= 0:
        sum_target = 0.0
    else:
        sum_target = 1 - 1 / refractive_index**2
    if raw_integral > _EPS and sum_target > 0:
        k = sum_target * np.pi / (2 * raw_integral)
    else:
        peak = s.max()
        k = 1 / max(peak, _EPS) if peak > 0 else 1.0

    elf = k * s

    n2 = 1 << int(np.ceil(np.log2(max(m, 2))))
    freq = np.arange(n2) / n2
    freq[freq > 0.5] -= 1
    elf_pad = np.concatenate([elf, np.zeros(n2 - m)])
    h_elf = np.fft.ifft(-1j * np.sign(freq) * np.fft.fft(elf_pad)).real[:m]

    inv_eps = (1 - h_elf) - 1j * elf
    denom = np.maximum(inv_eps.real**2 + inv_eps.imag**2, _EPS**2)
    eps_c = np.conj(inv_eps) / denom

    omega = e * e_charge / hbar
    eps_abs = np.abs(eps_c)
    if not np.isfinite(thickness):
        thickness = t_lambda * 100 * np.sqrt(acc_voltage / 200)

    return KKResult(
        energy=e,
        eps1=eps_c.real,
        eps2=eps_c.imag,
        elf=elf,
        optical_conductivity=eps_c.imag * omega * eps0,
        refractive_index=np.sqrt(np.maximum((eps_abs + eps_c.real) / 2, 0)),
        thickness=float(thickness),
        t_over_lambda=t_lambda,
    )


# ════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class SVDResult:
    eigenspectra: np.ndarray       # [nE, k]
    score_maps: np.ndarray         # [Ny, Nx, k]
    singular_values: np.ndarray    # [k]
    explained: np.ndarray          # [k] percent
    cumulative: np.ndarray         # [k]
    mean_spectrum: np.ndarray      # [nE]
    denoised_cube: np.ndarray | None = field(default=None)


def svd(
    cube: np.ndarray,
    energy: np.ndarray,
    n_components: int = 0,
    denoise: bool = False,
    center: bool = True,
) -> SVDResult:
    """Multivariate decomposition of an SI cube (port of eelsSVD.m)."""
    cube = np.asarray(cube, dtype=np.float64)
    energy = np.asarray(energy, dtype=np.float64).ravel()
    ny, nx, ne = cube.shape
    n_px = ny * nx
    if energy.size != ne:
        raise ValueError("energy length must match cube channels")
    if n_px < 2:
        raise ValueError("need at least 2 spatial pixels")

    a = cube.reshape(n_px, ne)
    mean_spec = a.mean(axis=0) if center else np.zeros(ne)
    u, sv, vt = np.linalg.svd(a - mean_spec, full_matrices=False)
    v = vt.T

    k_max = min(n_px, ne)
    k = min(n_components, k_max) if n_components > 0 else min(20, k_max)
    total_var = float((sv**2).sum())
    sv_k, u_k, v_k = sv[:k], u[:, :k], v[:, :k]

    # deterministic sign: largest |component| of each eigenspectrum positive
    for j in range(k):
        if v_k[np.abs(v_k[:, j]).argmax(), j] < 0:
            v_k[:, j] = -v_k[:, j]
            u_k[:, j] = -u_k[:, j]

    explained = 100 * sv_k**2 / total_var
    denoised = None
    if denoise:
        denoised = ((u_k * sv_k) @ v_k.T + mean_spec).reshape(ny, nx, ne)

    return SVDResult(
        eigenspectra=v_k,
        score_maps=(u_k * sv_k).reshape(ny, nx, k),
        singular_values=sv_k,
        explained=explained,
        cumulative=np.cumsum(explained),
        mean_spectrum=mean_spec,
        denoised_cube=denoised,
    )


# ════════════════════════════════════════════════════════════════════
def fourier_ratio(
    energy: np.ndarray,
    core_loss: np.ndarray,
    low_loss: np.ndarray,
    zlp_window: tuple[float, float] = (-5.0, 5.0),
    zlp_ref: np.ndarray | None = None,
    regularize: float = 1e-6,
) -> np.ndarray:
    """Fourier-ratio deconvolution of plural scattering (Egerton §4.3).

    Removes plural scattering from a core-loss edge using the low-loss
    spectrum as the point-spread function, reconvolved with the ZLP to
    restore the energy resolution (and suppress high-frequency noise)::

        SSD = ℱ⁻¹{ ℱ[core] / ℱ[low] · ℱ[ZLP] }

    ``core_loss`` and ``low_loss`` share ``energy`` (low-loss ZLP at E≈0).
    Returns the single-scattering core-loss distribution (≥0).
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    core = np.asarray(core_loss, dtype=np.float64).ravel()
    low = np.asarray(low_loss, dtype=np.float64).ravel()
    n = energy.size
    if core.size != n or low.size != n:
        raise ValueError("energy, core_loss and low_loss must have equal length")

    if zlp_ref is None:
        mask = (energy >= zlp_window[0]) & (energy <= zlp_window[1])
        if mask.sum() < 2:
            raise ValueError("ZLP window has fewer than 2 channels")
        zlp = np.zeros(n)
        zlp[mask] = low[mask]
    else:
        zlp = np.asarray(zlp_ref, dtype=np.float64).ravel()
        if zlp.size != n:
            raise ValueError("zlp_ref must match spectrum length")

    low_g = np.maximum(low, _EPS)
    zlp_g = np.maximum(zlp, _EPS)

    n2 = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.fft(core, n2)
    low_f = np.fft.fft(low_g, n2)
    z = np.fft.fft(zlp_g, n2)

    # regularise the denominator (low-loss) against division by near-zero
    l_thresh = regularize * np.abs(low_f).max()
    small = np.abs(low_f) < l_thresh
    low_f[small] = l_thresh * np.exp(1j * np.angle(low_f[small]))

    ssd = np.fft.ifft(c / low_f * z).real[:n]
    return np.maximum(ssd, 0.0)


# ════════════════════════════════════════════════════════════════════
def richardson_lucy(
    spectrum: np.ndarray,
    psf: np.ndarray,
    iterations: int = 15,
) -> np.ndarray:
    """Richardson–Lucy iterative deconvolution of a 1-D spectrum.

    Recovers resolution lost to a known point-spread function (e.g. the
    ZLP) by the multiplicative RL update. ``psf`` must be the same length
    as ``spectrum`` and **centred** (peak at the array midpoint) so the
    deconvolved spectrum is not shifted; the route extracts and centres the
    ZLP before calling. Non-negative throughout (Poisson MLE).
    """
    d = np.maximum(np.asarray(spectrum, dtype=np.float64).ravel(), 0.0)
    p = np.asarray(psf, dtype=np.float64).ravel()
    if p.size != d.size:
        raise ValueError("psf must match spectrum length")
    ps = float(p.sum())
    if ps <= 0:
        raise ValueError("psf must have positive sum")
    p = p / ps
    p_flip = p[::-1]

    u = d.copy()
    for _ in range(max(1, int(iterations))):
        conv = np.convolve(u, p, mode="same")
        relative = d / np.maximum(conv, _EPS)
        u = u * np.convolve(relative, p_flip, mode="same")
    return np.maximum(u, 0.0)
