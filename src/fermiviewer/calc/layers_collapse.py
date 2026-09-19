"""Turning a cross-section ROI into the depth profile the detectors run on,
and the pixel extents that profile is measured in.

Split from `calc/layers.py` when the tilt-aware scaling pushed that module
past the 500-line guard, along a seam that was already there: everything
here answers "what curve am I detecting interfaces in, and what is one step
of it worth", and nothing here finds an interface.

Shared by `analyze_layers` and `recompute_layers` on purpose. An edited run
has to be collapsed EXACTLY as the detected one was — the positions a user
drags are depths in that profile — and a second spelling of this would let a
re-measure land them in a slightly different frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.calibration import growth_axis_scales, line_axis_scales
from fermiviewer.calc.layers_profile import cross_section_profile, roi_subimage
from fermiviewer.calc.tilted_profile import tilted_depth_profile

__all__ = ["Collapsed", "collapse", "tilted_scales"]


@dataclass(frozen=True)
class Collapsed:
    """What both entry points need out of "turn the ROI into a profile"."""

    depth_pos: np.ndarray
    profile: np.ndarray
    #: block a waviness trace runs over, already in `trace_axis` orientation
    sub: np.ndarray | None
    trace_axis: str
    applied_tilt_deg: float | None
    sampled_fraction: float


def tilted_scales(
    axis: str,
    tilt_deg: float | None,
    pixel_size: float,
    spacing: tuple[float, float] | None,
) -> tuple[float, float]:
    """``(depth, lateral)`` pixel extents for the axis actually collapsed along.

    `growth_axis_scales` answers for a stack aligned to the image axes. Once
    a tilt is applied the depth axis is rotated, so on anisotropic pixels its
    step is a MIX of the row and column extents: on 4 nm rows and 1 nm
    columns a 45-degree corrected axis steps 2.92 nm, not 4. Leaving the
    untilted answer in place miscalibrated every thickness, sigma_erf,
    sigma_w and thickness_std by that ratio — 1.37x in that example — while
    the numbers still looked ordinary.

    No tilt returns `growth_axis_scales` unchanged, so every existing result
    is untouched.
    """
    if tilt_deg is None or tilt_deg == 0.0:
        return growth_axis_scales(axis, pixel_size, spacing)
    theta = np.radians(tilt_deg)
    # the rotated depth direction in (row, col); axis="x" is the transpose,
    # the same way `growth_axis_scales` swaps its pair
    d_row, d_col = float(np.cos(theta)), float(np.sin(theta))
    if axis == "x":
        d_row, d_col = d_col, d_row
    return line_axis_scales(d_row, d_col, pixel_size, spacing)


def collapse(
    work: np.ndarray,
    roi: tuple[int, int, int, int] | None,
    axis: str,
    reduce: str,
    mask: np.ndarray | None,
    tilt_deg: float | None,
    waviness: bool,
) -> Collapsed:
    """The ROI as a depth profile, tilt-corrected when asked.

    Shared by :func:`analyze_layers` and :func:`recompute_layers` because an
    edited run has to be collapsed EXACTLY as the detected one was: two
    spellings of this would let a re-measure land its interfaces in a
    slightly different frame from the one the user dragged them in.

    The block a waviness trace runs over must come from the same collapse,
    or every trace sits at a depth the profile never had. After a tilt
    correction that is the resampled box, whose depth already runs down the
    rows -- hence a trace axis of "y" whatever `axis` was.
    """
    if tilt_deg is not None and tilt_deg != 0.0:
        if mask is not None:
            raise ValueError(
                "a tilt correction and an irregular region cannot be combined: "
                "the rotated box is rectangular by construction"
            )
        tilted = tilted_depth_profile(
            work, roi, axis=axis, tilt_deg=tilt_deg, reduce=reduce
        )
        return Collapsed(
            depth_pos=tilted.depth_pos,
            profile=tilted.profile,
            sub=tilted.block if waviness else None,
            trace_axis="y",
            applied_tilt_deg=tilted.tilt_deg,
            sampled_fraction=tilted.sampled_fraction,
        )
    depth_pos, profile = cross_section_profile(work, roi, axis, reduce, mask)
    return Collapsed(
        depth_pos=depth_pos,
        profile=profile,
        # the ROI sub-image, clamped like box_integrate
        sub=roi_subimage(work, roi) if waviness else None,
        trace_axis=axis,
        applied_tilt_deg=None,
        sampled_fraction=1.0,
    )

