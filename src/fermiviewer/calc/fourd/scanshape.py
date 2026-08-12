"""Scan-shape candidates for a headerless 4D acquisition (PLAN_4DSTEM #14).

A Merlin ``.mib`` records frames back to back and nothing about the raster
that produced them, so a file of N frames is consistent with every (rows,
cols) whose product is N. The parser therefore defaults to a single-row
line-scan and the viewer shows a 10-px strip — correct, and useless, for the
128x128 raster the user actually acquired.

This module answers "which shapes are even possible, and which are worth
offering first". Pure arithmetic, no I/O: the route serves it, the workshop
lists it, and the parser's own ``rows * cols == n_frames`` check remains the
authority on whether a chosen shape is legal.
"""

from __future__ import annotations

import math

__all__ = ["scan_shape_candidates"]


def scan_shape_candidates(n_frames: int, limit: int = 12) -> list[tuple[int, int]]:
    """Plausible ``(rows, cols)`` factorisations of ``n_frames``, best first.

    Ordered by how close the raster is to square, because STEM scans
    overwhelmingly are — a 128x128 acquisition should be the first thing
    offered for 16384 frames, not 1x16384. Both orientations of a non-square
    pair are offered (128x64 and 64x128 are different acquisitions and
    nothing in the file distinguishes them), with the taller one first, and
    the degenerate 1xN line-scan is always included last: it is the parser's
    own default and a genuine acquisition mode, so it must stay reachable
    even when `limit` would otherwise crowd it out.

    Returns an empty list for a non-positive frame count.
    """
    if n_frames <= 0:
        return []
    if n_frames == 1:
        return [(1, 1)]

    pairs: list[tuple[int, int]] = []
    for rows in range(1, math.isqrt(n_frames) + 1):
        if n_frames % rows:
            continue
        cols = n_frames // rows
        pairs.append((cols, rows))  # taller orientation first
        if rows != cols:
            pairs.append((rows, cols))

    line_scan = (1, n_frames)
    # Squareness: |log(rows/cols)| is symmetric in the two orientations, so
    # ties between them are broken by the insertion order above rather than
    # by an arbitrary preference for one of the two.
    ranked = sorted(pairs, key=lambda rc: abs(math.log(rc[0] / rc[1])))
    if limit > 0 and len(ranked) > limit:
        ranked = ranked[:limit]
        if line_scan not in ranked:
            ranked[-1] = line_scan
    return ranked
