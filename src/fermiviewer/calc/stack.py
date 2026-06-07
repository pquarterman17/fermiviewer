"""Multi-image operations: image math, FFT drift alignment, maximum
intensity projection (port of +fermiViewer/+processing/
executeImageMath.m, executeAlignStack.m, stackOps doMip). Pure library.
"""

from __future__ import annotations

import numpy as np

__all__ = ["align_stack", "image_math", "mip"]

_OPS = ("subtract", "divide", "ratio", "add")


def image_math(a: np.ndarray, b: np.ndarray, op: str) -> np.ndarray:
    """Arithmetic between two images (executeImageMath.m, verbatim):
    both are cropped to the common top-left region; divide and ratio
    clamp their denominators at 1 (count-data convention)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mh = min(a.shape[0], b.shape[0])
    mw = min(a.shape[1], b.shape[1])
    a = a[:mh, :mw]
    b = b[:mh, :mw]
    out: np.ndarray
    if op == "subtract":
        out = a - b
    elif op == "divide":
        out = a / np.maximum(b, 1.0)
    elif op == "ratio":
        out = a / np.maximum(a + b, 1.0)
    elif op == "add":
        out = a + b
    else:
        raise ValueError(f"op must be one of {_OPS}")
    return out


def align_stack(
    rasters: list[np.ndarray],
) -> tuple[list[np.ndarray], np.ndarray]:
    """FFT cross-correlation drift correction (executeAlignStack.m,
    verbatim): first image is the reference; each mover is zero-padded
    to the common size, integer-shifted by circshift. Ties in the
    correlation peak resolve in MATLAB's column-major order.

    Returns (aligned rasters, shifts[N, 2] as (dy, dx))."""
    if len(rasters) < 2:
        raise ValueError("need at least 2 images to align")
    ref = np.asarray(rasters[0], dtype=np.float64)
    out: list[np.ndarray] = [ref]
    shifts = np.zeros((len(rasters), 2), dtype=np.int64)

    for k in range(1, len(rasters)):
        mov = np.asarray(rasters[k], dtype=np.float64)
        pad_h = max(ref.shape[0], mov.shape[0])
        pad_w = max(ref.shape[1], mov.shape[1])
        ref_pad = np.zeros((pad_h, pad_w))
        ref_pad[: ref.shape[0], : ref.shape[1]] = ref
        mov_pad = np.zeros((pad_h, pad_w))
        mov_pad[: mov.shape[0], : mov.shape[1]] = mov

        cc = np.real(np.fft.ifft2(
            np.fft.fft2(ref_pad) * np.conj(np.fft.fft2(mov_pad))
        ))
        # MATLAB max(cc(:)) — first maximum in column-major order
        flat_idx = int(np.argmax(cc.ravel(order="F")))
        peak_r, peak_c = np.unravel_index(flat_idx, cc.shape, order="F")
        dy = int(peak_r)
        dx = int(peak_c)
        if dy > pad_h / 2:
            dy -= pad_h
        if dx > pad_w / 2:
            dx -= pad_w
        shifts[k] = (dy, dx)
        out.append(np.roll(mov, (dy, dx), axis=(0, 1)))
    return out, shifts


def mip(rasters: list[np.ndarray]) -> np.ndarray:
    """Maximum intensity projection across images (stackOps doMip,
    verbatim): frames zero-pad into the FIRST frame's canvas."""
    if not rasters:
        raise ValueError("need at least 1 image")
    h, w = np.asarray(rasters[0]).shape
    stack = np.zeros((h, w, len(rasters)))
    for i, fr in enumerate(rasters):
        fr = np.asarray(fr, dtype=np.float64)
        mh = min(h, fr.shape[0])
        mw = min(w, fr.shape[1])
        stack[:mh, :mw, i] = fr[:mh, :mw]
    out: np.ndarray = stack.max(axis=2)
    return out
