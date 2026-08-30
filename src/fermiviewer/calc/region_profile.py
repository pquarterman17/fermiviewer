"""Collapsing a canonical region to a 1-D depth profile.

`cross_section_profile` reduces a rectangle to a depth profile by
averaging whole rows (or columns) of it. Every depth in a rectangle is
backed by the same number of pixels, which is what makes the profile a
picture of the specimen rather than of the box.

An irregular region breaks that, and the consequences are not uniform
across the `reduce` modes — so this module keeps the two that survive and
refuses the one that does not, rather than returning a number for all
three.

**mean and median survive.** Both are per-depth AVERAGES, so a depth
backed by 40 selected pixels and a depth backed by 12 are still directly
comparable. The support changes; the quantity does not.

**sum does not.** A sum over a varying number of pixels tracks the
region's WIDTH at each depth as faithfully as it tracks intensity. Run
over a circle, a flat specimen produces a domed profile with two steep
flanks, and `detect_interfaces` reports the flanks as interfaces — a
layer structure read off the shape the user drew. That is a wrong answer
rather than a degraded one, so `reduce="sum"` with a non-rectangular mask
raises and names `"mean"`.

**A depth with no selected pixel** raises for the same reason. There is
no average to report, and any filler — 0, NaN, an interpolation — becomes
a feature in a profile whose whole purpose is edge detection.

`box_integrate` is golden-tested and is not touched: the rectangular path
still runs through `cross_section_profile` unchanged, and this module is
reached only once a mask exists.
"""

from __future__ import annotations

import numpy as np

__all__ = ["REDUCE_NEEDS_UNIFORM_SUPPORT", "masked_depth_profile"]

#: `reduce` modes whose value depends on HOW MANY pixels contributed, and
#: which therefore cannot be read over a region of varying width.
REDUCE_NEEDS_UNIFORM_SUPPORT = ("sum",)


def masked_depth_profile(
    block: np.ndarray, window: np.ndarray, axis: str = "y", reduce: str = "mean"
) -> tuple[np.ndarray, np.ndarray]:
    """`(depth_pos, profile)` over the selected pixels of `block`.

    `block` is the region's bounding-box crop and `window` the mask over
    that same crop, both 2-D and the same shape. `axis="y"` reduces over
    columns (one value per row); `axis="x"` reduces over rows. Positions
    stay 0-based pixels from the box edge, matching
    `layers.cross_section_profile`.
    """
    if block.shape != window.shape:
        raise ValueError(
            f"mask window {window.shape} does not match the region {block.shape}"
        )
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'y' or 'x'")
    if reduce in REDUCE_NEEDS_UNIFORM_SUPPORT:
        raise ValueError(
            f"reduce={reduce!r} needs every depth backed by the same number "
            "of pixels, which an irregular region does not give: the profile "
            "would follow the region's width and report its flanks as "
            "interfaces. Use reduce='mean' (or a rectangular region)"
        )
    if reduce not in ("mean", "median"):
        raise ValueError("reduce must be 'mean' or 'median'")

    arr = np.asarray(block, dtype=np.float64)
    # a pixel is usable when it is BOTH selected and finite — the NaN
    # policy `cross_section_profile` documents, applied per depth
    usable = np.asarray(window, dtype=bool) & np.isfinite(arr)
    reduce_axis = 1 if axis == "y" else 0
    support = usable.sum(axis=reduce_axis)
    if not support.all():
        empty = int(np.flatnonzero(support == 0)[0])
        raise ValueError(
            f"the region leaves depth {empty} with no usable pixel, so it has "
            "no profile value; any filler would read as an edge"
        )

    if reduce == "mean":
        profile = np.sum(arr, axis=reduce_axis, where=usable, dtype=np.float64)
        profile /= support
    else:
        # nanmedian over the selection: masked-out pixels become NaN in a
        # working copy so the median sees only what the region selected
        masked = np.where(usable, arr, np.nan)
        profile = np.nanmedian(masked, axis=reduce_axis)
    return np.arange(profile.size, dtype=np.float64), np.asarray(profile)
