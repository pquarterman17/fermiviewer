"""Collapsing a box to a 1-D profile along a ROTATED axis.

A cross-section is rarely mounted square to the detector. Integrate a
tilted stack along the image rows and every interface is averaged over a
lateral run that crosses it, so a sharp interface reports a wide σ_erf —
the profile is blurred by the mounting, and nothing downstream can tell
that apart from a genuinely graded interface. Integrating along the
stack's own axis is the fix, and it is the same operation a rotatable
box-profile tool needs, so it lives here once rather than twice.

**One angle for the whole stack, not one per interface.** Layers in a
film stack are parallel by construction; letting each interface carry its
own angle would allow two of them to cross, and would leave "depth" with
no single meaning to measure a thickness along. A tilt is a property of
how the specimen sits, so it belongs to the box.

**The sampled box shrinks rather than padding.** A rotated box poking
outside its ROI could be sampled with NaN fill and a NaN-aware reduce,
but then the number of contributing pixels varies with depth and the
profile carries a vignette that looks like a gradient in the specimen.
Instead the largest similarly-shaped rotated box that still fits is used,
so every depth row averages the SAME lateral width and the profile's
shape is the specimen's. `sampled_fraction` reports how much extent that
cost, because a large tilt on a thin ROI can shrink it a lot.

At ``tilt_deg == 0`` this module is not involved at all: the caller keeps
using the existing axis-aligned collapse, so the untilted path stays
byte-identical to the golden-tested `box_integrate`.

Pure library (numpy + scipy.ndimage).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import map_coordinates

from fermiviewer.calc.roi import roi_slices

__all__ = ["TiltedProfile", "tilted_depth_profile"]


@dataclass(frozen=True)
class TiltedProfile:
    #: 0-based depth in pixels ALONG THE TILTED AXIS, from the box edge
    depth_pos: np.ndarray
    profile: np.ndarray
    #: the resampled box itself, depth down the rows. Returned because a
    #: waviness trace must run in the SAME frame the profile was collapsed
    #: in -- tracing the un-rotated block while profiling the rotated one
    #: would put every trace at a depth the profile never had.
    block: np.ndarray
    #: the angle actually used, degrees, signed
    tilt_deg: float
    #: lateral pixels averaged at every depth -- constant by construction
    lateral_samples: int
    #: linear extent kept after shrinking the box to fit, 0-1. 1.0 means the
    #: tilt cost nothing; a small number means the answer rests on a narrow
    #: strip and the caller should say so.
    sampled_fraction: float


def _inscribed_scale(height: float, width: float, tilt_deg: float) -> float:
    """Largest uniform scale whose rotated `height x width` box still fits.

    Both constraints must hold for a box rotated by θ inside the original::

        h·|cos θ| + w·|sin θ| <= height
        h·|sin θ| + w·|cos θ| <= width

    Scaling both sides by one factor keeps the box's shape, which is what
    makes the untilted and tilted profiles comparable: a caller does not
    silently get a different aspect ratio along with the rotation.
    """
    c = abs(np.cos(np.radians(tilt_deg)))
    s = abs(np.sin(np.radians(tilt_deg)))
    span_h = height * c + width * s
    span_w = height * s + width * c
    return float(min(height / span_h, width / span_w))


def tilted_depth_profile(
    img: np.ndarray,
    roi: tuple[int, int, int, int] | None,
    *,
    axis: str = "y",
    tilt_deg: float = 0.0,
    reduce: str = "mean",
    min_lateral: int = 3,
) -> TiltedProfile:
    """Collapse the ROI along an axis rotated by `tilt_deg`.

    `axis` names which way depth runs BEFORE the rotation -- ``"y"`` for
    horizontal layers (depth down the rows), ``"x"`` for vertical ones --
    so a caller that already decided the growth axis keeps that answer and
    only adds the off-axis correction.

    Sampling is bilinear (`map_coordinates`, order 1), the same
    interpolation `calc.profiles.line_profile` uses for an arbitrary-angle
    line, so a tilted box profile and a line profile drawn along the same
    direction agree rather than differing by the interpolator.
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError("a depth profile needs a 2-D image")
    if axis not in ("x", "y"):
        raise ValueError("axis must be 'y' or 'x'")
    if reduce not in ("mean", "median"):
        # No "sum" here: the box shrinks with tilt, so a sum would change
        # with the angle for reasons that are geometry, not specimen. A
        # caller wanting a total should scale a mean by a width it states.
        raise ValueError("tilted reduce must be 'mean' or 'median'")
    if not np.isfinite(tilt_deg):
        raise ValueError("tilt_deg must be finite")

    rows, cols = roi_slices(arr.shape, roi)
    sub = arr[rows, cols]
    n_rows, n_cols = sub.shape
    # depth runs down `sub`'s rows for axis="y"; transpose once for "x" so
    # the geometry below is written in one orientation only
    block = sub if axis == "y" else sub.T
    height, width = block.shape

    scale = _inscribed_scale(float(height), float(width), tilt_deg)
    n_depth = max(int(round(height * scale)), 2)
    n_lat = max(int(round(width * scale)), 1)
    if n_lat < min_lateral:
        raise ValueError(
            f"a tilt of {tilt_deg:g}° leaves only {n_lat} lateral pixels in this "
            "box; widen the region or reduce the tilt"
        )

    theta = np.radians(tilt_deg)
    cos_t, sin_t = float(np.cos(theta)), float(np.sin(theta))
    d = np.arange(n_depth, dtype=np.float64) - (n_depth - 1) / 2.0
    lat = np.arange(n_lat, dtype=np.float64) - (n_lat - 1) / 2.0
    dd, ll = np.meshgrid(d, lat, indexing="ij")
    r_centre = (height - 1) / 2.0
    c_centre = (width - 1) / 2.0
    rr = r_centre + dd * cos_t - ll * sin_t
    cc = c_centre + dd * sin_t + ll * cos_t

    # "nearest" rather than a NaN fill: the inscribed box already keeps every
    # sample inside, so this only guards float round-off at the very edge,
    # where clamping to the boundary pixel is right and a NaN would not be.
    samples = map_coordinates(block, [rr, cc], order=1, mode="nearest")
    profile = (
        np.nanmedian(samples, axis=1) if reduce == "median"
        else np.mean(samples, axis=1)
    )
    return TiltedProfile(
        depth_pos=np.arange(n_depth, dtype=np.float64),
        profile=np.asarray(profile, dtype=np.float64),
        block=np.asarray(samples, dtype=np.float64),
        tilt_deg=float(tilt_deg),
        lateral_samples=int(n_lat),
        sampled_fraction=float(scale),
    )
