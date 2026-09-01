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

from fermiviewer.calc.crofton import crofton_perimeters_by_label, usable_spacing

__all__ = [
    "ClassThresholds",
    "ShapeDescriptors",
    "classify_shapes",
    "shape_descriptors",
]

_PROPERTIES = (
    "label",
    "area",
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
    #: Angle of the major axis, measured from the ROW axis (downward, the
    #: first index) toward the column axis, in [-pi/2, pi/2] — skimage's
    #: convention, kept rather than converted so the number a reader looks
    #: up matches the number this reports.
    #:
    #: Stated because it is 90 degrees from the one most people assume. A
    #: horizontal feature (constant row, varying column) reports pi/2, not
    #: 0; a consumer plotting it as "from horizontal" draws every particle
    #: across its own short axis. Verified against synthetic ellipses at
    #: known angles: reported == 90 deg - (angle from the column axis).
    orientation_rad: np.ndarray
    solidity: np.ndarray
    axis_major_length_px: np.ndarray
    axis_minor_length_px: np.ndarray
    feret_max_px: np.ndarray
    #: Physical lengths, in the unit of the `spacing` passed to
    #: `shape_descriptors`; all-NaN when it was not given. Separate fields
    #: rather than a scaled view of the `_px` ones because under
    #: anisotropic pixels they are NOT proportional: stretching one axis
    #: reshapes the moment ellipse, so the physical major axis is not the
    #: pixel major axis times any single number.
    perimeter_calibrated: np.ndarray
    axis_major_length_calibrated: np.ndarray
    axis_minor_length_calibrated: np.ndarray
    feret_max_calibrated: np.ndarray
    #: The dimensionless descriptors below are measured in PHYSICAL space
    #: when `spacing` is given, and in pixel space otherwise.
    #:
    #: Dimensionless is not the same as scale-invariant. These are all
    #: invariant under scaling both axes together, which is why a single
    #: `pixel_size` never mattered to them -- but none of them survives
    #: scaling one axis alone. A circular particle on 2:1 pixels is an
    #: ellipse in the array, and pixel-space eccentricity, circularity,
    #: aspect ratio and orientation all describe that distortion rather
    #: than the particle. On anisotropic data the calibrated values are
    #: the physical answer and the pixel-space ones are an artefact of
    #: the sampling.
    circularity: np.ndarray  # 4*pi*A/P_crofton**2; may slightly exceed 1
    aspect_ratio: np.ndarray  # major/minor; NaN where minor axis is degenerate


def _measure(lab: np.ndarray, spacing: tuple[float, float]) -> dict[str, np.ndarray]:
    """One regionprops pass at `spacing`, plus the Crofton perimeter.

    The perimeter comes from `calc.crofton` rather than regionprops
    because skimage refuses `perimeter_crofton` outright on anisotropic
    spacing; on square pixels the two agree bit for bit.
    """
    rpt = measure.regionprops_table(lab, properties=_PROPERTIES, spacing=spacing)
    out = {k: np.asarray(rpt[k], dtype=np.float64) for k in rpt}
    out["perimeter_crofton"] = crofton_perimeters_by_label(lab, spacing)
    return out


def shape_descriptors(
    labels: np.ndarray,
    spacing: tuple[float, float] | None = None,
) -> ShapeDescriptors:
    """Per-region shape descriptors for a compact 1..n label image.

    `labels` must already be filtered/renumbered (as returned by
    `particles.region_stats`) so labels run 1..n with no gaps — the same
    precondition `grains.grain_stats` relies on. Rows come back ordered
    by ascending label, i.e. positionally aligned with the paired
    `RegionStats` list.

    `spacing` is the physical extent of one pixel as ``(row, column)`` —
    `DataStruct.pixel_spacing`. Given it, the `_calibrated` lengths are
    filled in and the dimensionless descriptors are measured in physical
    space; omitted (or unusable: non-finite, zero, negative), the
    `_calibrated` fields are NaN and everything else is pixel-space, which
    is exactly what this returned before spacing existed.

    Two passes rather than one scaled pass, because anisotropic pixels
    make the two genuinely different measurements and neither is
    recoverable from the other: the pixel-space moment ellipse of a
    circle on 2:1 pixels is an ellipse, and no single factor turns its
    axes into the circle's.
    """
    lab = np.asarray(labels, dtype=np.int64)
    n = int(lab.max()) if lab.size else 0
    if n == 0:
        z = np.array([], dtype=np.float64)
        return ShapeDescriptors(z, z, z, z, z, z, z, z, z, z, z, z, z)

    px = _measure(lab, (1.0, 1.0))
    usable = usable_spacing(spacing)
    phys = _measure(lab, usable) if usable is not None else None
    # Dimensionless descriptors describe the PHYSICAL particle when we can
    # reach it; none of them survives scaling one axis alone.
    shape = phys if phys is not None else px

    with np.errstate(divide="ignore", invalid="ignore"):
        circularity = 4.0 * np.pi * shape["area"] / shape["perimeter_crofton"] ** 2
        minor = shape["axis_minor_length"]
        aspect_ratio = shape["axis_major_length"] / np.where(minor > 0, minor, np.nan)

    def _cal(key: str) -> np.ndarray:
        return phys[key] if phys is not None else np.full(n, np.nan)

    return ShapeDescriptors(
        perimeter_crofton_px=px["perimeter_crofton"],
        eccentricity=shape["eccentricity"],
        orientation_rad=shape["orientation"],
        solidity=shape["solidity"],
        axis_major_length_px=px["axis_major_length"],
        axis_minor_length_px=px["axis_minor_length"],
        feret_max_px=px["feret_diameter_max"],
        perimeter_calibrated=_cal("perimeter_crofton"),
        axis_major_length_calibrated=_cal("axis_major_length"),
        axis_minor_length_calibrated=_cal("axis_minor_length"),
        feret_max_calibrated=_cal("feret_diameter_max"),
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
