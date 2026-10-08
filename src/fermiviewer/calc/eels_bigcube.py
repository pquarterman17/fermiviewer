"""Memory-bounded variants of the whole-cube EELS/EDS operations.

The reference implementations in ``eels_advanced`` promote the WHOLE
spectrum-image cube to float64 (and, for ZLP alignment, to complex128 FFT
buffers). On a real 240x320x4096 or 512x512x4096 SI that is several GiB per
temporary and the backend dies with MemoryError — or, without a memory cap,
the OS kills the process and the user loses the session.

These variants walk the cube in blocks of pixels so peak extra memory is a
fixed budget plus the output, never a multiple of the cube. They are only
used above ``BIG_CUBE_BYTES`` (see ``is_big``) so small cubes — and every
golden test — keep the exact reference arithmetic.
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np

__all__ = ["BIG_CUBE_BYTES", "align_zlp_chunked", "is_big", "svd_chunked"]

# float64-equivalent size above which the chunked path is used
BIG_CUBE_BYTES = 512 * 1024**2
# working-set budget per block of pixels
_BLOCK_BYTES = 128 * 1024**2


def is_big(cube: np.ndarray) -> bool:
    return int(np.asarray(cube).size) * 8 > BIG_CUBE_BYTES


def _blocks(n_px: int, bytes_per_px: int) -> Iterator[slice]:
    step = max(1, _BLOCK_BYTES // max(1, bytes_per_px))
    for start in range(0, n_px, step):
        yield slice(start, min(n_px, start + step))


def align_zlp_chunked(
    cube: np.ndarray,
    win_mask: np.ndarray,
    ref_custom: np.ndarray | None,
    reference: str,
    subpixel: bool,
    parabolic_offset,  # eels_advanced._parabolic_offset (no import cycle)
) -> tuple[np.ndarray, np.ndarray]:
    """Blockwise ``align_zlp``: same cross-correlation, same shift rules,
    output in the input dtype (as the reference path returns it)."""
    ny, nx, ne = cube.shape
    n_px = ny * nx
    flat = cube.reshape(n_px, ne)
    n_win = int(win_mask.sum())
    nfft = 2 * n_win - 1

    if ref_custom is not None:
        ref = ref_custom
    elif reference == "mean":
        acc = np.zeros(n_win)
        for sl in _blocks(n_px, n_win * 8):
            acc += flat[sl][:, win_mask].sum(axis=0, dtype=np.float64)
        ref = acc / n_px
    elif reference == "max":
        best, best_px = -np.inf, 0
        for sl in _blocks(n_px, n_win * 8):
            tot = flat[sl][:, win_mask].sum(axis=1, dtype=np.float64)
            j = int(tot.argmax())
            if tot[j] > best:
                best, best_px = float(tot[j]), sl.start + j
        ref = flat[best_px, win_mask].astype(np.float64)
    else:
        raise ValueError("reference must be 'mean', 'max', or a vector")

    ref_f = np.conj(np.fft.fft(ref, nfft))
    out = np.empty_like(flat)
    shifts = np.empty(n_px, dtype=np.float64 if subpixel else np.int32)
    k = np.fft.fftfreq(ne)
    # complex FFT buffers dominate: ~3 complex128 arrays of max(nfft, ne)
    per_px = 3 * 16 * max(nfft, ne)
    for sl in _blocks(n_px, per_px):
        zlp = flat[sl][:, win_mask].astype(np.float64).T          # [nWin, B]
        xc = np.fft.ifft(np.fft.fft(zlp, nfft, axis=0) * ref_f[:, None], axis=0).real
        peak = xc.argmax(axis=0)
        lag = np.where(peak > n_win - 1, peak - nfft, peak)
        block = flat[sl]
        if subpixel:
            s = -(lag.astype(np.float64) + parabolic_offset(xc, peak))
            spec = np.fft.fft(block.astype(np.float64), axis=1)
            phase = np.exp(-2j * np.pi * k[None, :] * s[:, None])
            out[sl] = np.fft.ifft(spec * phase, axis=1).real.astype(cube.dtype)
        else:
            s = (-lag).astype(np.int32)
            res = block.copy()
            for v in np.unique(s):
                if v != 0:
                    sel = s == v
                    res[sel] = np.roll(block[sel], int(v), axis=-1)
            out[sl] = res
        shifts[sl] = s
    return out.reshape(ny, nx, ne), shifts.reshape(ny, nx)


def svd_chunked(
    cube: np.ndarray, n_components: int, denoise: bool, center: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float, np.ndarray, np.ndarray | None]:
    """SVD via eigendecomposition of the nE x nE covariance, accumulated in
    pixel blocks. Gives the same leading components as the thin SVD of the
    centred [Np, nE] matrix without ever holding it in float64.

    Returns ``(v_k, scores_k, sv_k, total_var, mean_spec, denoised)`` where
    ``scores_k = U_k * S_k`` ([Np, k]) and ``denoised`` is float32."""
    ny, nx, ne = cube.shape
    n_px = ny * nx
    flat = cube.reshape(n_px, ne)
    per_px = 2 * 8 * ne

    mean_spec = np.zeros(ne)
    if center:
        for sl in _blocks(n_px, per_px):
            mean_spec += flat[sl].sum(axis=0, dtype=np.float64)
        mean_spec /= n_px

    cov = np.zeros((ne, ne))
    for sl in _blocks(n_px, per_px):
        b = flat[sl].astype(np.float64) - mean_spec
        cov += b.T @ b
    w, vecs = np.linalg.eigh(cov)
    order = np.argsort(w)[::-1]
    w = np.clip(w[order], 0.0, None)
    vecs = vecs[:, order]

    k_max = min(n_px, ne)
    k = min(n_components, k_max) if n_components > 0 else min(20, k_max)
    total_var = float(w.sum())
    sv_k = np.sqrt(w[:k])
    v_k = np.ascontiguousarray(vecs[:, :k])

    scores = np.empty((n_px, k))
    for sl in _blocks(n_px, per_px):
        scores[sl] = (flat[sl].astype(np.float64) - mean_spec) @ v_k

    # deterministic sign: largest |component| of each eigenspectrum positive
    for j in range(k):
        if v_k[np.abs(v_k[:, j]).argmax(), j] < 0:
            v_k[:, j] = -v_k[:, j]
            scores[:, j] = -scores[:, j]

    denoised = None
    if denoise:
        denoised = np.empty((n_px, ne), dtype=np.float32)
        for sl in _blocks(n_px, per_px):
            denoised[sl] = scores[sl] @ v_k.T + mean_spec
        denoised = denoised.reshape(ny, nx, ne)
    return v_k, scores, sv_k, total_var, mean_spec, denoised
