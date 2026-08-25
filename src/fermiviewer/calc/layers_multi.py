"""Cross-map layer comparison — one reference detection re-measured on every
map, the numerics behind POST /analyze/layers/multi lifted out of
`routes/layers.py` (ADR 0005 §1) so the route and any future `layers_multi`
op run the SAME sequence instead of each re-wiring it.

The point of the endpoint (EELS/EDS element maps): detect the interfaces
ONCE on a reference map, then re-measure those same depths on every other
map → per-element σ_erf (chemical interface sharpness) and σ_w (geometric
waviness) at a shared set of interfaces. That comparison is only meaningful
if the imposed geometry is identical everywhere, which is why the reference
map's detected `axis` — not each map's own auto-detection — governs every
`recompute_layers` call here, and why the whole detect→impose→measure
sequence lives in one function rather than being re-assembled per caller.

Lives in its own module because `calc/layers.py` sits at the 500-line
ceiling. Pure: numpy + sibling calc only, arrays/sequences/primitives in,
a frozen dataclass of JSON-shaped data out. Maps are keyed by INDEX into
the input sequences (input order == output order); attaching identity
(image ids, display names) is the caller's job.

Conventions shared with `calc/layers.py`:

* ``roi`` is 1-based inclusive ``(r1, c1, r2, c2)``.
* ``Interface.position`` is a sub-pixel float in *profile pixels* — a
  0-based index into the laterally-collapsed depth profile of the ROI
  sub-image along ``axis``. ``axis="y"`` means depth runs over ROWS.
* ``sigma_erf`` / ``sigma_w`` / ``thickness`` / ``thickness_std`` come back
  in calibrated units (pixel size × pixel), positions stay in pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.layers import analyze_layers, recompute_layers
from fermiviewer.calc.layers_report import interface_layer_blocks

__all__ = [
    "MapCalibrationError",
    "MapMeasureError",
    "MultiLayerComparison",
    "compare_layers_across_maps",
    "uniform_pixel_cal",
]


class MapCalibrationError(ValueError):
    """One input map's spatial calibration is incompatible with the reference.

    ``index`` is that map's position in the input sequences, so a caller can
    name the offender ("<map name> has incompatible spatial calibration")
    without the pure layer knowing anything about image ids or names.
    """

    def __init__(self, message: str, index: int) -> None:
        super().__init__(message)
        self.index = index


class MapMeasureError(ValueError):
    """Measuring one input map failed (e.g. non-finite pixels in its ROI).

    Same contract as :class:`MapCalibrationError`: ``index`` identifies which
    input map raised, so the failure is reported per map instead of as an
    anonymous error for the whole batch.
    """

    def __init__(self, message: str, index: int) -> None:
        super().__init__(message)
        self.index = index


def _clamp_reference(reference: int, n: int) -> int:
    """Clamp a caller-supplied reference index into ``range(n)``.

    Deliberately forgiving rather than raising: the reference is a UI choice
    ("compare against this map"), and a stale index should still produce a
    comparison instead of a hard error.
    """
    return max(0, min(reference, n - 1))


def uniform_pixel_cal(
    pixel_sizes: Sequence[float],
    pixel_units: Sequence[str],
    *,
    reference: int = 0,
    rtol: float = 1e-6,
) -> tuple[float, str, bool]:
    """The reference map's pixel calibration, checked to hold for ALL maps.

    Returns ``(pixel_size, unit, calibrated)`` for the reference map, using
    the layers-route idiom: a non-finite or non-positive pixel size falls
    back to ``1.0``, an empty unit to ``"px"``, and ``calibrated`` is True
    only when the reference really carries both (finite, > 0, non-empty unit).

    WHY the check: σ_erf and σ_w come back in calibrated units, so comparing
    interface roughness across maps is only meaningful if one calibrated
    pixel means the same physical length on every map. Therefore every map
    must be calibrated **iff** the reference is, and a calibrated map must
    carry the SAME unit string and a pixel size equal within ``rtol``
    (``atol=0`` — a relative tolerance only; two sizes differing by a real
    factor are never "close enough", however small they both are).

    Raises :class:`MapCalibrationError` (carrying the offending map's index)
    on the first incompatible map, and plain ``ValueError`` if the two
    sequences disagree in length or are empty.
    """
    if len(pixel_sizes) != len(pixel_units):
        raise ValueError("pixel_sizes and pixel_units must have the same length")
    if not pixel_sizes:
        raise ValueError("give at least one map")

    ref_idx = _clamp_reference(reference, len(pixel_sizes))
    ref_px, ref_unit = float(pixel_sizes[ref_idx]), pixel_units[ref_idx]
    ref_calibrated = bool(np.isfinite(ref_px) and ref_px > 0 and ref_unit)
    px = ref_px if np.isfinite(ref_px) and ref_px > 0 else 1.0
    unit = ref_unit if ref_unit else "px"

    for k, (size, map_unit) in enumerate(zip(pixel_sizes, pixel_units, strict=True)):
        size = float(size)
        calibrated = bool(np.isfinite(size) and size > 0 and map_unit)
        if calibrated != ref_calibrated:
            raise MapCalibrationError("incompatible spatial calibration", k)
        if calibrated and (
            map_unit != ref_unit or not np.isclose(size, ref_px, rtol=rtol, atol=0)
        ):
            raise MapCalibrationError("incompatible spatial calibration", k)
    return px, unit, ref_calibrated


@dataclass(frozen=True)
class MultiLayerComparison:
    axis: str                          # "y" | "x", the REFERENCE map's axis
    unit: str                          # reference calibration, shared by all maps
    pixel_size: float
    reference_index: int               # clamped into range(len(images))
    reference_positions: list[float]   # profile pixels, reference frame
    maps: list[dict]                   # per input map, interface_layer_blocks()


def compare_layers_across_maps(
    images: Sequence[np.ndarray],
    pixel_sizes: Sequence[float],
    pixel_units: Sequence[str],
    *,
    reference: int = 0,
    roi: tuple[int, int, int, int] | None = None,
    axis: str = "auto",
    sensitivity: float = 0.3,
    n_layers: int = 0,
    modality: str = "haadf",
    waviness: bool = True,
) -> MultiLayerComparison:
    """Per-map interface sharpness at ONE shared set of interfaces.

    Detects interfaces on ``images[reference]`` (:func:`analyze_layers`), then
    re-measures those depths on every map (:func:`recompute_layers`) with the
    reference's axis and positions imposed — including on the reference map
    itself, so all rows go through the same measurement path. ``waviness``
    defaults to True here (unlike the single-map entry points) because σ_w is
    the point of a per-element comparison.

    Callers must have already checked that the maps share a shape; this only
    checks what it needs to impose one geometry on all of them. Calibration
    compatibility is re-checked here via :func:`uniform_pixel_cal` so a direct
    caller cannot skip it — the HTTP route calls it first only to turn the
    error's ``index`` into a map name.

    Output order equals input order. Raises :class:`MapCalibrationError` /
    :class:`MapMeasureError`, both carrying the offending map's index.
    """
    if not (len(images) == len(pixel_sizes) == len(pixel_units)):
        raise ValueError("images, pixel_sizes and pixel_units must have the same length")
    if not images:
        raise ValueError("give at least one map")

    ref_idx = _clamp_reference(reference, len(images))
    px, unit, _calibrated = uniform_pixel_cal(
        pixel_sizes, pixel_units, reference=ref_idx
    )

    try:
        ref_res = analyze_layers(
            images[ref_idx], axis=axis, sensitivity=sensitivity, n_layers=n_layers,
            modality=modality, waviness=waviness, pixel_size=px, unit=unit, roi=roi,
        )
    except ValueError as e:
        raise MapMeasureError(str(e), ref_idx) from None
    positions = [i.position for i in ref_res.interfaces]
    # The reference's RESOLVED axis (not the caller's possibly-"auto" request)
    # is imposed on every map: two maps of the same region can auto-detect
    # opposite growth axes when one of them has weak layer contrast, and the
    # comparison would then be between unrelated profiles.
    use_axis = ref_res.axis

    maps: list[dict] = []
    for k, (img, size, map_unit) in enumerate(
        zip(images, pixel_sizes, pixel_units, strict=True)
    ):
        # Dead but load-bearing after the uniform_pixel_cal check above (every
        # map now matches the reference): kept so this stays correct if the
        # compatibility rule is ever relaxed to per-map calibration.
        m_px = float(size) if np.isfinite(size) and size > 0 else px
        m_unit = map_unit if map_unit else unit
        try:
            res = recompute_layers(
                img, positions, axis=use_axis, roi=roi,
                pixel_size=m_px, unit=m_unit, waviness=waviness,
            )
        except ValueError as e:      # e.g. non-finite pixels in a comparison map
            raise MapMeasureError(str(e), k) from None
        maps.append(interface_layer_blocks(res))

    return MultiLayerComparison(
        axis=use_axis,
        unit=unit,
        pixel_size=px,
        reference_index=ref_idx,
        reference_positions=positions,
        maps=maps,
    )
