"""Panoramic image stitching — W3 tranche 3b (ported verbatim).

Pairwise FFT cross-correlation on overlap strips → integer offsets →
canvas assembly with linear-ramp alpha blending at seams.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["StitchResult", "stitch_images"]


@dataclass(frozen=True)
class StitchResult:
    mosaic: np.ndarray
    offsets: np.ndarray  # (n, 2) cumulative [dy, dx] vs image 1
    n_images: int
    layout: str


def _pad(arr: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    out = np.zeros((target_h, target_w))
    out[: arr.shape[0], : arr.shape[1]] = arr
    return out


def _pair_offset(
    a: np.ndarray, b: np.ndarray, layout: str, overlap_frac: float
) -> tuple[int, int, float]:
    """(dy, dx, peak) — placement of b relative to a, via strip xcorr."""
    ha, wa = a.shape
    hb, wb = b.shape
    if layout == "horizontal":
        strip_w = max(4, round(min(wa, wb) * overlap_frac))
        pa = _pad(a[:, wa - strip_w :], max(ha, hb), strip_w)
        pb = _pad(b[:, :strip_w], max(ha, hb), strip_w)
    else:
        strip_h = max(4, round(min(ha, hb) * overlap_frac))
        pa = _pad(a[ha - strip_h :, :], strip_h, max(wa, wb))
        pb = _pad(b[:strip_h, :], strip_h, max(wa, wb))

    pa = pa - pa.mean()
    pb = pb - pb.mean()
    cc = np.real(np.fft.ifft2(np.fft.fft2(pa) * np.conj(np.fft.fft2(pb))))

    # MATLAB max(cc(:)) takes the first max in COLUMN-major order
    flat = cc.flatten(order="F")
    idx = int(np.argmax(flat))
    cc_h, cc_w = cc.shape
    r_peak = idx % cc_h  # 0-based
    c_peak = idx // cc_h
    peak = float(flat[idx])

    # lags past half the dimension wrap to negative shifts
    r_shift = r_peak - cc_h if r_peak + 1 > cc_h / 2 else r_peak
    c_shift = c_peak - cc_w if c_peak + 1 > cc_w / 2 else c_peak

    if layout == "horizontal":
        return r_shift, (wa - strip_w) + c_shift, peak
    return (ha - strip_h) + r_shift, c_shift, peak


def _alpha(
    h: int, w: int, layout: str, blend_width: float, k: int, n: int
) -> np.ndarray:
    """Linear seam ramps: fade in on leading edge (k>0), out on trailing."""
    alpha = np.ones((h, w))
    bw = max(1, round(blend_width))
    if layout == "horizontal":
        if k > 0:
            b = min(bw, w)
            alpha[:, :b] *= np.linspace(0, 1, b)[None, :]
        if k < n - 1:
            b = min(bw, w)
            alpha[:, w - b :] *= np.linspace(1, 0, b)[None, :]
    else:
        if k > 0:
            b = min(bw, h)
            alpha[:b, :] *= np.linspace(0, 1, b)[:, None]
        if k < n - 1:
            b = min(bw, h)
            alpha[h - b :, :] *= np.linspace(1, 0, b)[:, None]
    return alpha


def stitch_images(
    images: list[np.ndarray],
    layout: str = "horizontal",
    overlap_frac: float = 0.2,
    blend_width: float = 50.0,
) -> StitchResult:
    """Stitch a sequence of equal-ish tiles; layout 'auto' picks the
    orientation whose first-pair correlation peak is stronger."""
    if len(images) < 2:
        raise ValueError("at least 2 images are required")
    if not 0 <= overlap_frac <= 0.5:
        raise ValueError("overlap_frac must be in [0, 0.5]")
    imgs = [np.asarray(im, dtype=np.float64) for im in images]
    for im in imgs:
        if im.ndim != 2:
            raise ValueError("images must be 2-D grayscale")

    if layout == "auto":
        _, _, peak_h = _pair_offset(imgs[0], imgs[1], "horizontal", overlap_frac)
        _, _, peak_v = _pair_offset(imgs[0], imgs[1], "vertical", overlap_frac)
        layout = "horizontal" if peak_h >= peak_v else "vertical"
    elif layout not in ("horizontal", "vertical"):
        raise ValueError("layout must be 'horizontal', 'vertical' or 'auto'")

    n = len(imgs)
    offsets = np.zeros((n, 2), dtype=np.int64)
    for k in range(n - 1):
        dy, dx, _ = _pair_offset(imgs[k], imgs[k + 1], layout, overlap_frac)
        offsets[k + 1] = offsets[k] + (dy, dx)

    h0, w0 = imgs[0].shape
    min_dy, max_dy = int(offsets[:, 0].min()), int(offsets[:, 0].max())
    min_dx, max_dx = int(offsets[:, 1].min()), int(offsets[:, 1].max())
    canvas = np.zeros((h0 + max_dy - min_dy, w0 + max_dx - min_dx))
    weights = np.zeros_like(canvas)

    for k, im in enumerate(imgs):
        h, w = im.shape
        r0 = int(offsets[k, 0]) - min_dy
        c0 = int(offsets[k, 1]) - min_dx
        a = _alpha(h, w, layout, blend_width, k, n)
        canvas[r0 : r0 + h, c0 : c0 + w] += im * a
        weights[r0 : r0 + h, c0 : c0 + w] += a

    valid = weights > 0
    canvas[valid] /= weights[valid]

    return StitchResult(
        mosaic=canvas, offsets=offsets, n_images=n, layout=layout
    )
