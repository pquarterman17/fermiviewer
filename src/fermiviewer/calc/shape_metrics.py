"""Per-particle shape descriptors — SHAPE_ANALYSIS_PLAN Wave 1 item #1/#2.

`RegionStats` (particles.py) carries no shape descriptor at all, unlike
`GrainStats` (grains.py), which already reports eccentricity/orientation/
solidity/Crofton perimeter. This module closes that gap for particles,
matching `grains.grain_stats`'s `regionprops_table` idiom exactly rather
than hand-rolling moments the library already computes under test.

Circularity = 4*pi*A / P_crofton**2, where P is the CROFTON perimeter —
never the naive polygonal pixel-boundary perimeter, which overestimates
digitized circles and yields ~0.79 for a perfect disk (the classic
trap). With Crofton, a large digitized disk approaches 1; small regions
can still slightly exceed 1 (Crofton bias). Report the raw value and
never clip it silently.

Orientation is the skimage convention, verbatim: the angle between the
ROW axis (axis 0) and the ellipse major axis, range (-pi/2, pi/2],
radians. This is AXIAL data (period pi — a rod at +80 degrees is the
same rod at -100 degrees): any histogram/rose spans exactly (-90, 90]
degrees and must never be mirrored into a full circle. It is
morphological orientation, not crystallographic orientation.

Aspect ratio = axis_major_length / axis_minor_length of the binary
moment ellipse. A degenerate minor axis (e.g. a single-pixel region)
reports NaN — never Infinity, never a silently large number. The wire
layer (routes/structure.py) maps NaN -> null, the same convention
`RegionStats.diameter_calibrated` already uses for "no calibration".

`classify_shapes` buckets each region into an advisory shape class from
a 2D PROJECTION. A rod viewed end-on projects as a disk; no 2D image can
refute that. Classes therefore describe the morphology of the
projection only, never the true 3D particle — the same advisory
philosophy as the species-overlap warning badge. Thresholds are visible
and caller-tunable, and nothing is auto-corrected or filtered by class.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from skimage import measure

__all__ = [
    "ClassThresholds",
    "ShapeDescriptors",
    "classify_shapes",
    "shape_descriptors",
]

_PROPERTIES = (
    "label",
    "area",
    "perimeter_crofton",
    "eccentricity",
    "orientation",
    "solidity",
    "axis_major_length",
    "axis_minor_length",
    "feret_diameter_max",
)


@dataclass(frozen=True)
class ShapeDescriptors:
    """One entry per region, ordered to match `particles.region_stats`'s
    compact 1..n label numbering (ascending by label, same guarantee
    `grains.grain_stats` relies on for its own `regionprops_table` call)."""

    perimeter_crofton_px: np.ndarray
    eccentricity: np.ndarray
    orientation_rad: np.ndarray
    solidity: np.ndarray
    axis_major_length_px: np.ndarray
    axis_minor_length_px: np.ndarray
    feret_max_px: np.ndarray
    circularity: np.ndarray  # 4*pi*A/P_crofton**2; may slightly exceed 1
    aspect_ratio: np.ndarray  # major/minor; NaN where minor axis is degenerate


def shape_descriptors(labels: np.ndarray) -> ShapeDescriptors:
    """Per-region shape descriptors for a compact 1..n label image.

    `labels` must already be filtered/renumbered (as returned by
    `particles.region_stats`) so labels run 1..n with no gaps — the same
    precondition `grains.grain_stats` relies on. Rows come back ordered
    by ascending label, i.e. positionally aligned with the paired
    `RegionStats` list.
    """
    lab = np.asarray(labels, dtype=np.int64)
    n = int(lab.max())
    if n == 0:
        z = np.array([], dtype=np.float64)
        return ShapeDescriptors(z, z, z, z, z, z, z, z, z)

    rpt = measure.regionprops_table(lab, properties=_PROPERTIES)
    area = np.asarray(rpt["area"], dtype=np.float64)
    perim = np.asarray(rpt["perimeter_crofton"], dtype=np.float64)
    ecc = np.asarray(rpt["eccentricity"], dtype=np.float64)
    orient = np.asarray(rpt["orientation"], dtype=np.float64)
    solidity = np.asarray(rpt["solidity"], dtype=np.float64)
    major = np.asarray(rpt["axis_major_length"], dtype=np.float64)
    minor = np.asarray(rpt["axis_minor_length"], dtype=np.float64)
    feret = np.asarray(rpt["feret_diameter_max"], dtype=np.float64)

    with np.errstate(divide="ignore", invalid="ignore"):
        circularity = 4.0 * np.pi * area / perim**2
        minor_safe = np.where(minor > 0, minor, np.nan)
        aspect_ratio = major / minor_safe

    return ShapeDescriptors(
        perimeter_crofton_px=perim,
        eccentricity=ecc,
        orientation_rad=orient,
        solidity=solidity,
        axis_major_length_px=major,
        axis_minor_length_px=minor,
        feret_max_px=feret,
        circularity=circularity,
        aspect_ratio=aspect_ratio,
    )


@dataclass(frozen=True)
class ClassThresholds:
    """Caller-tunable classification cutoffs — contract defaults.

    ``sphere_min_circularity`` is set on the CROFTON scale, where an
    axis-aligned square converges to ≈0.874 (measured; see the module
    docstring — NOT the textbook 4πA/P² = π/4, which belongs to the naive
    perimeter). A cube-projection must not classify sphere-like — cubes
    vs spheres is the canonical faceted-vs-round distinction — so the
    cutoff sits between the square's 0.874 and the large disk's ≈0.99.
    The plan's original 0.85 default predated the measurement and would
    have admitted squares.
    """

    aggregate_max_solidity: float = 0.85
    rod_min_aspect: float = 2.5
    sphere_max_aspect: float = 1.3
    sphere_min_circularity: float = 0.92


def classify_shapes(
    aspect_ratio: np.ndarray,
    circularity: np.ndarray,
    solidity: np.ndarray,
    thresholds: ClassThresholds | None = None,
) -> list[str]:
    """Advisory shape class per region, from a 2D PROJECTION.

    A rod viewed end-on projects as a disk; no 2D image can refute that,
    so these labels claim morphology of the projection only — never the
    true 3D particle shape. `aggregate` is checked FIRST and trumps the
    rest (a low-solidity rod-shaped aspect ratio is still `aggregate`,
    not `rod-like`); a null/NaN `aspect_ratio` can never be classified
    `rod-like` or `sphere-like` and falls through to `intermediate`.

    ```
    aggregate    solidity < aggregate_max_solidity      # checked first
    rod-like     aspect_ratio >= rod_min_aspect
    sphere-like  aspect_ratio < sphere_max_aspect AND
                 circularity > sphere_min_circularity
    intermediate otherwise (incl. null aspect_ratio)
    ```
    """
    th = thresholds or ClassThresholds()
    ar = np.asarray(aspect_ratio, dtype=np.float64)
    circ = np.asarray(circularity, dtype=np.float64)
    sol = np.asarray(solidity, dtype=np.float64)

    with np.errstate(invalid="ignore"):
        is_aggregate = sol < th.aggregate_max_solidity
        is_rod = ~is_aggregate & (ar >= th.rod_min_aspect)
        is_sphere = (
            ~is_aggregate
            & ~is_rod
            & (ar < th.sphere_max_aspect)
            & (circ > th.sphere_min_circularity)
        )

    classes = np.full(ar.shape, "intermediate", dtype=object)
    classes[is_aggregate] = "aggregate"
    classes[is_rod] = "rod-like"
    classes[is_sphere] = "sphere-like"
    return [str(c) for c in classes]
