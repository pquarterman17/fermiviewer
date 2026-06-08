"""Scale-bar auto-detection (port of +fermiViewer/+calibration/
detectScaleBar.m, verbatim): longest clean white-or-black run in the
bottom 15 % strip, with a bar-height sanity check. Pure library."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["ScaleBarDetect", "detect_scale_bar"]


@dataclass(frozen=True)
class ScaleBarDetect:
    found: bool
    bar_len: int
    bar_x1: int   # 1-based, inclusive (MATLAB convention)
    bar_x2: int
    bar_y: int
    msg: str


def detect_scale_bar(pixels: np.ndarray) -> ScaleBarDetect:
    px = np.asarray(pixels, dtype=np.float64)
    h, w = px.shape

    if h < 10 or w < 20:
        return ScaleBarDetect(False, 0, 0, 0, 0,
                              "Image too small for scale-bar detection.")

    strip_h = min(h, max(10, round(h * 0.15)))
    strip = px[h - strip_h:, :]

    smin, smax = strip.min(), strip.max()
    if smax - smin < 1:
        return ScaleBarDetect(
            False, 0, 0, 0, 0,
            "Could not detect a scale bar (bottom strip is uniform).",
        )
    norm = (strip - smin) / (smax - smin)

    best_len, best_row, best_x1, best_x2 = 0, 0, 0, 0

    for try_white in (True, False):
        bw = norm > 0.85 if try_white else norm < 0.15
        for ri in range(bw.shape[0]):
            row = bw[ri]
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            starts = np.flatnonzero(d == 1)        # 0-based
            ends = np.flatnonzero(d == -1) - 1
            for s0, e0 in zip(starts, ends, strict=True):
                run_len = int(e0 - s0 + 1)
                if not (run_len > best_len and run_len >= 20
                        and run_len >= w * 0.03 and run_len <= w * 0.60):
                    continue
                # bar height: rows below must stay mostly set across
                # the run's interior columns (MATLAB sampCols)
                bar_height = 1
                for rr in range(ri + 1, bw.shape[0]):
                    c0 = max(0, s0 + 2)
                    c1 = min(w, e0 - 1)            # MATLAB ends-2 incl.
                    if c1 - c0 < 3:
                        break
                    if bw[rr, c0:c1].mean() > 0.7:
                        bar_height += 1
                    else:
                        break
                if 1 <= bar_height <= 15:
                    best_len = run_len
                    best_row = ri + 1              # 1-based
                    best_x1 = int(s0) + 1
                    best_x2 = int(e0) + 1

    if best_len == 0:
        return ScaleBarDetect(
            False, 0, 0, 0, 0,
            "Could not detect a scale bar in the bottom 15% of the "
            'image. Use "Draw on Bar" instead.',
        )
    return ScaleBarDetect(
        True, best_len, best_x1, best_x2,
        h - strip_h + best_row, f"{best_len:.0f} px detected",
    )
