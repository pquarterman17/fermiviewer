"""Statistics over an exact region mask — roadmap 4C-2.

The one place a region becomes mean/std/min/max, shared by
`/measure/roi`, the `image_stats` op and `profile_stats.roi_stats` so the
three cannot drift. Before this, each computed its own aggregate over its
own idea of which pixels were in scope, and the three ideas disagreed
(see `STD_MATLAB` below and `n_finite`).

**The raster is never copied.** `roi_stats` used to cast the whole image
to float64 and then, for an ellipse, fancy-index a copy of the selection
on top of that. Here the rect is a VIEW and the aggregates are `where=`
reductions.

What that costs is worth stating exactly rather than as "nothing":
`np.isfinite(view)` is a boolean array the size of the region, an
intersection with the caller's mask is done in place, and the deviation
pass runs in fixed-size blocks (`_masked_std`, which exists because
`np.std(..., where=...)` allocates a float64 copy of the whole view).
Nothing scales with the raster in float64, which is the property the
bounded-memory guard in tests/test_region_stats.py pins.

**Which pixels count, and which are averaged, are different questions.**
`n_pixels` is how many the region selects; `n_finite` is how many of those
carry a real value. Physical `area` derives from `n_pixels`, because a
dead detector pixel still occupies specimen area — but mean, std, min and
max are taken over the finite subset only, so one NaN cannot poison a
region's mean. Reporting both counts is what makes that visible rather
than silent: a caller comparing them learns how much of its region was
unusable.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = ["STD_MATLAB", "STD_POPULATION", "region_stats"]

#: Sample standard deviation, N-1. The MATLAB parity `roi_stats` has
#: always had: `+fermiViewer/+interaction/rectROI.m:29` calls `std(vals)`,
#: which is ddof=1, and MATLAB's `std()` of a scalar is 0.
STD_MATLAB = 1

#: Population standard deviation, N. What the `image_stats` op has always
#: reported (`np.ndarray.std()`'s default).
#:
#: The two coexist ON PURPOSE. 4C converges which PIXELS an analysis reads,
#: not which estimator it reports, and silently switching either consumer
#: to the other would change numbers users have already published. Picking
#: one is a separate decision with its own migration.
STD_POPULATION = 0


def region_stats(
    values: np.ndarray,
    rect: tuple[int, int, int, int] | None = None,
    mask: np.ndarray | None = None,
    *,
    pixel_size: float = float("nan"),
    ddof: int = STD_MATLAB,
) -> dict[str, float]:
    """Statistics of `values` over a region.

    `rect` is 1-based inclusive and ALREADY CLAMPED (``None`` = the whole
    image); `mask` is a FULL-IMAGE boolean array or ``None`` meaning every
    pixel of `rect` — the same pairing `region_resolve.ResolvedRegion`
    hands out and `raster.masked_sum_spectrum` consumes, so a caller
    holding a resolved region can feed both without reshaping anything.

    Returns `mean`, `std`, `min`, `max`, `n_pixels`, `n_finite` and
    `area`. With no finite pixel the four aggregates are NaN rather than
    an error: an all-NaN region is a real thing to measure and saying so
    beats raising, which would lose the `n_pixels` the caller asked for.

    Raises `ValueError` for a region that selects NO pixels, matching
    `region_mask.bounding_box` — there is nothing to describe, and
    returning zeros would read as a measurement.
    """
    values = np.asarray(values)
    if values.ndim != 2:
        raise ValueError(f"region statistics need a 2-D raster, got {values.shape}")
    view = values if rect is None else _rect_view(values, rect)

    if mask is None:
        selected: np.ndarray | None = None
        n_pixels = int(view.size)
    else:
        mask = np.asarray(mask)
        if mask.dtype != bool:
            raise ValueError(f"mask must be boolean, got dtype {mask.dtype}")
        if mask.shape != values.shape:
            raise ValueError(
                f"mask must be a full-image {values.shape} array, got {mask.shape}"
            )
        selected = mask if rect is None else _rect_view(mask, rect)
        n_pixels = int(np.count_nonzero(selected))
    if n_pixels == 0:
        raise ValueError("region selects no pixels, so it has no statistics")

    # `where=` throughout: no copy of the selection, and it composes with
    # ddof, which uses the where-count for the correction. The `&=` is in
    # place because the finite mask is already the largest thing here.
    usable = np.isfinite(view)
    if selected is not None:
        usable &= selected
    n_finite = int(np.count_nonzero(usable))
    area = float(n_pixels) * pixel_size**2 if np.isfinite(pixel_size) else float(n_pixels)

    if n_finite == 0:
        nan = float("nan")
        return {
            "mean": nan, "std": nan, "min": nan, "max": nan,
            "n_pixels": float(n_pixels), "n_finite": 0.0, "area": area,
        }
    mean = float(np.mean(view, where=usable, dtype=np.float64))
    return {
        "mean": mean,
        "std": _masked_std(view, usable, mean, n_finite, ddof),
        "min": float(np.min(view, where=usable, initial=np.inf)),
        "max": float(np.max(view, where=usable, initial=-np.inf)),
        "n_pixels": float(n_pixels),
        "n_finite": float(n_finite),
        "area": area,
    }


def _rect_view(array: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray:
    """A VIEW of `array` through a 1-based inclusive rect — never a copy."""
    r0, c0, r1, c1 = rect
    return array[r0 - 1:r1, c0 - 1:c1]


#: Elements per block in the deviation pass — 256k, i.e. 2 MB as float64.
#: Small enough that the temporary is noise beside the masks the caller
#: already holds, large enough that the Python loop costs nothing.
_STD_BLOCK_ELEMENTS = 1 << 18


def _masked_std(
    view: np.ndarray, usable: np.ndarray, mean: float, n_finite: int, ddof: int
) -> float:
    """Standard deviation over `usable`, in bounded memory.

    `np.std(view, where=usable, ddof=ddof, dtype=np.float64)` computes the
    same number and is one line, but it MATERIALIZES the deviations: on a
    2048x2048 float32 raster it allocates a 33.6 MB float64 temporary of
    the whole image (measured — it is what the bounded-memory guard in
    tests/test_region_stats.py catches). So the deviation pass is chunked.

    Two-pass rather than the one-pass `E[x^2] - E[x]^2`, which needs no
    chunking at all: an EM image with mean 30000 and std 50 subtracts two
    nearly equal large numbers and loses most of the precision. Speed here
    is not worth a wrong third digit.

    ddof would divide by zero on a single pixel; MATLAB's `std()` of a
    scalar is 0 and `roi_stats` has always matched that.
    """
    if n_finite <= ddof:
        return 0.0
    per_row = max(int(view.shape[1]), 1)
    rows = max(1, _STD_BLOCK_ELEMENTS // per_row)
    total = 0.0
    for start in range(0, view.shape[0], rows):
        stop = start + rows
        deviation = view[start:stop].astype(np.float64) - mean
        deviation *= deviation
        total += float(np.sum(deviation, where=usable[start:stop]))
    return math.sqrt(total / (n_finite - ddof))
