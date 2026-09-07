"""Spot indexing over an analysis ROI — the composition `/api/diffraction/index`
and its op both run (ADR 0005 §1).

Split from `calc/diffraction.py` only for the module-size ratchet; the ROI
arithmetic it depends on (`roi_frame`, `roi_selects_pixels`) deliberately
stays beside `apply_roi` there, so the clamp maths has exactly one home.

Pure library: numpy + stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.calibration import (
    is_reciprocal_unit,
    real_spacing_from_reciprocal,
    spacing_at_column_scale,
    usable_spacing,
)
from fermiviewer.calc.crystal import Phase
from fermiviewer.calc.diffraction import (
    IndexCandidate,
    index_spots,
    roi_selects_pixels,
)

__all__ = ["IndexedPattern", "index_spots_roi", "pattern_spacing"]


def pattern_spacing(
    shape: tuple[int, ...],
    pixel_spacing: tuple[float, float],
    pixel_unit: str,
    pixel_size: float,
    camera_length: float,
) -> tuple[float, float] | None:
    """Per-axis extents for `index_spots`, read off the pattern's own
    calibration while keeping the caller's `pixel_size` as the column
    scale (`calc/calibration.spacing_at_column_scale`).

    Camera mode: the pattern's pixels ARE the detector's, so their ratio
    applies directly. FFT mode on a reciprocally calibrated pattern -- a
    generated FFT (`calc/fourier.fft_axes`) or a loaded one in ``1/nm`` --
    inverts the frequency steps over the pattern's ``(H, W)`` to recover
    the SOURCE's real-space extents, whose ratio is the one `index_spots`
    needs; a reciprocal ratio used directly would be upside down. None
    when the pattern has no usable calibration: one scale, as before.
    """
    fft_mode = bool(np.isnan(camera_length))
    if fft_mode and is_reciprocal_unit(pixel_unit):
        sp = usable_spacing(pixel_spacing)
        if sp is None:
            return None
        return spacing_at_column_scale(pixel_size, real_spacing_from_reciprocal(shape, sp))
    return spacing_at_column_scale(pixel_size, pixel_spacing)


@dataclass(frozen=True)
class IndexedPattern:
    """`index_spots` over an optional ROI, plus the overlay geometry.

    `center` and `measured_r` are in the FULL-image frame: they drive the
    matched-ring overlay, which is drawn on the whole image (the
    `.center`/`.measuredR` fields of indexDiffraction.m). The indexing
    itself (`candidates`) ALSO runs against the full-image frame — an ROI
    only gates which request is accepted (see `index_spots_roi`), it does
    not rescale the geometry `candidates` are measured against.
    """

    center: tuple[int, int]  # 1-based (row, col), full image
    measured_r: list[float]  # px from the full-image centre, per input spot
    candidates: list[IndexCandidate]


def index_spots_roi(
    img_shape: tuple[int, ...],
    spots: np.ndarray,
    roi: dict | None = None,
    *,
    pixel_size: float = 1.0,
    camera_length: float = float("nan"),
    acc_voltage: float = 200,
    tolerance: float = 0.05,
    top_n: int = 5,
    extra_phases: list[Phase] | None = None,
    spacing: tuple[float, float] | None = None,
) -> IndexedPattern:
    """Index 1-based full-image `spots` against the phase database.

    `roi`, when given, gates the request (a degenerate or out-of-image ROI
    is a `ValueError` — see below) but otherwise plays no part in the
    indexing arithmetic: an ROI is how the caller chose WHICH spots were
    worth detecting (`find_spots_roi`, upstream of this call), not a
    smaller pattern. `spots`, the DC centre, and the reciprocal grid (FFT
    mode) or physical pixel size (camera mode) all resolve against the
    FULL `img_shape`, so a given spot's measured d-spacing comes out
    identical whether or not an ROI was in force. Re-framing spots into an
    ROI-local, smaller image size used to feed that smaller size to
    `_measured_d`'s FFT-mode reciprocal grid (``d`` scales with frame
    width) and, for any off-centre ROI, to a wrong DC centre in EITHER
    mode — both silently rescaled every measured d.

    Takes a SHAPE, not the array: nothing here reads a pixel, and passing
    the image would make `apply_roi`'s circle branch copy and mask a patch
    that is then thrown away.

    An ROI that selects no pixels is an error rather than a silent
    whole-image index — the wave-C `find_spots_roi` discipline; the route's
    zero-defaults would otherwise index the full pattern while the caller
    believed a region was in force.

    `spacing` (per-axis pixel extent, ``(row, column)``) passes straight
    through to `index_spots`.
    """
    if roi is not None and not roi_selects_pixels(img_shape, roi):
        raise ValueError("roi selects no pixels of the image")
    spots = np.asarray(spots, dtype=np.float64)
    if spots.ndim != 2 or (spots.size and spots.shape[1] != 2):
        raise ValueError("spots must be an (N, 2) array of 1-based (row, col)")

    # Indexing always runs against the FULL image frame -- see the ROI
    # paragraph above -- so `spots` pass through unshifted and `img_shape`
    # unshrunk, regardless of `roi`.
    full_shape = (int(img_shape[0]), int(img_shape[1]))
    candidates = index_spots(
        spots,
        full_shape,
        pixel_size=pixel_size,
        camera_length=camera_length,
        acc_voltage=acc_voltage,
        tolerance=tolerance,
        top_n=top_n,
        extra_phases=extra_phases,
        spacing=spacing,
    )

    full_center = (full_shape[0] // 2 + 1, full_shape[1] // 2 + 1)
    measured_r = (
        np.hypot(
            spots[:, 0] - full_center[0], spots[:, 1] - full_center[1]
        ).tolist()
        if spots.shape[0] > 0
        else []
    )
    return IndexedPattern(full_center, measured_r, candidates)
