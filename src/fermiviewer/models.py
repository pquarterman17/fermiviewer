"""Pydantic API models — the wire types (handoff §8).

Kept separate from the internal DataStruct on purpose: wire schemas
evolve with the frontend; the internal contract evolves with analysis.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from fermiviewer.calc.fourd.scanshape import scan_shape_candidates
from fermiviewer.datastruct import SPECTRAL_KINDS, AxisCal, DataKind, DataStruct
from fermiviewer.io.metadata import databar_content_rows, get_stage_tilt

if TYPE_CHECKING:
    from fermiviewer.calc.fourd.dataset import FourDDataset

__all__ = ["AxisCalOut", "FourDMeta", "ImageMeta", "OpenRequest"]


# Short lists of scalars are metadata a client can use (`elements`,
# `element_z`); long ones are data dumps that would bloat every image record.
_MAX_META_LIST = 256


def _public_meta(metadata: dict[str, Any]) -> dict[str, Any]:
    """Client-visible slice of a DataStruct's metadata.

    Scalars pass through, plus short homogeneous lists of scalars. The list
    case is not cosmetic: the EDS element picker highlights the species an
    acquisition declares via ``meta['elements']``, and while this filter
    allowed scalars only, that list was dropped for every parser that
    supplied it — the picker has never had acquisition elements to show.
    """
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if key == "image_tags":
            continue
        if isinstance(value, (int, float, str, bool)):
            out[key] = value
        elif (
            isinstance(value, list)
            and 0 < len(value) <= _MAX_META_LIST
            and all(isinstance(v, (int, float, str, bool)) for v in value)
        ):
            out[key] = value
    return out


class OpenRequest(BaseModel):
    paths: list[str]


class ImageMeta(BaseModel):
    id: str
    name: str
    kind: DataKind
    shape: list[int]
    dtype: str
    pixel_size: float | None = None
    pixel_unit: str = ""
    value_unit: str = ""  # physical unit of the pixel values (e.g. AFM height "nm")
    n_channels: int | None = None
    energy_first: float | None = None
    energy_last: float | None = None
    energy_units: str = ""
    stage_tilt_deg: float | None = None  # from io.metadata.get_stage_tilt
    # Rows of real image above a vendor-baked databar (FEI/Thermo Fisher
    # SEM/FIB TIFFs), else None. One normalized number so the client never
    # re-derives the image_rows/databar_height precedence rule — the scale
    # bar keeps its default off the bar, and Strip Vendor Databar knows
    # where to cut. See io.metadata.databar_content_rows.
    content_rows: int | None = None
    meta: dict[str, Any] = {}

    @classmethod
    def from_datastruct(cls, img_id: str, name: str, ds: DataStruct) -> ImageMeta:
        spectral = ds.kind in SPECTRAL_KINDS
        px = None
        unit = ""
        if ds.kind is not DataKind.SPECTRUM and ds.pixel_cal.calibrated:
            px, unit = ds.pixel_cal.scale, ds.pixel_cal.units
        ax = ds.energy_axis if spectral else None
        tilt_deg, _ = get_stage_tilt(ds.metadata)

        def _finite_or_none(value: float | None) -> float | None:
            # AxisCal.calibrated only requires a finite, non-zero `scale` —
            # a NaN `origin` (finite scale notwithstanding, e.g. a recipe
            # step that derives an axis from a bad fit) still produces a
            # NaN-filled axis. Left unguarded, that NaN survives into the
            # JSON response as a literal `NaN` token (Python's json.dumps
            # allows it, JS's JSON.parse does not), breaking the *entire*
            # response for the client — same class of bug as
            # stage_tilt_deg below, applied to the energy bounds too.
            return None if value is not None and math.isnan(value) else value

        return cls(
            id=img_id,
            name=name,
            kind=ds.kind,
            shape=list(ds.data.shape),
            dtype=str(ds.data.dtype),
            pixel_size=px,
            pixel_unit=unit,
            value_unit=str(ds.metadata.get("value_unit", "")),
            n_channels=ds.n_channels if spectral else None,
            energy_first=_finite_or_none(float(ax[0]) if ax is not None else None),
            energy_last=_finite_or_none(float(ax[-1]) if ax is not None else None),
            energy_units=ds.energy_cal.units if spectral else "",
            stage_tilt_deg=None if math.isnan(tilt_deg) else tilt_deg,
            content_rows=(
                # DataKind.IMAGE is validated 2-D, so shape[0] is the row count
                databar_content_rows(ds.metadata, int(ds.data.shape[0]))
                if ds.kind is DataKind.IMAGE
                else None
            ),
            meta=_public_meta(ds.metadata),
        )


class AxisCalOut(BaseModel):
    """Wire form of `fermiviewer.datastruct.AxisCal` (never expose the
    dataclass itself — same separation-of-concerns rationale as the module
    docstring)."""

    scale: float
    origin: float
    units: str

    @classmethod
    def from_axis_cal(cls, a: AxisCal) -> AxisCalOut:
        return cls(scale=a.scale, origin=a.origin, units=a.units)


class FourDMeta(BaseModel):
    """4D-STEM dataset metadata (PLAN_4DSTEM). Deliberately NOT an ImageMeta
    variant — a FourDDataset is not a DataStruct (see
    docs/adr/0001-fourd-data-model.md) — but mirrors its shape so a client
    can tell the two apart by the `is_fourd` discriminator without choking
    on an unexpected `kind` value: this is never a normal image and must
    never be treated as one (see routes/images.py's `/session/open`)."""

    id: str
    name: str
    is_fourd: Literal[True] = True
    source: str | None = None
    scan_shape: list[int]
    det_shape: list[int]
    dtype: str
    scan_axes: list[AxisCalOut]
    det_axes: list[AxisCalOut]
    nav_available: bool = True
    #: Probe positions in the file — the product of `scan_shape`, and the
    #: quantity any re-rastering has to preserve.
    n_frames: int = 0
    #: False when the format records no raster (Merlin `.mib`), meaning the
    #: current `scan_shape` is a guess the user may correct via
    #: `POST /fourd/{id}/reshape`. True when the file states it.
    scan_shape_from_file: bool = True
    #: Plausible `(rows, cols)` re-rasterings, best first. Empty when the
    #: shape came from the file — offering alternatives there would invite
    #: the user to contradict the acquisition.
    scan_shape_options: list[list[int]] = []

    @classmethod
    def from_dataset(cls, fourd_id: str, name: str, ds: FourDDataset) -> FourDMeta:
        source = ds.metadata.get("source")
        rows, cols = ds.scan_shape
        from_file = bool(ds.metadata.get("scan_shape_from_file", True))
        return cls(
            id=fourd_id,
            name=name,
            source=str(source) if source else None,
            scan_shape=list(ds.scan_shape),
            det_shape=list(ds.det_shape),
            dtype=str(ds.dtype),
            scan_axes=[AxisCalOut.from_axis_cal(a) for a in ds.scan_axes],
            det_axes=[AxisCalOut.from_axis_cal(a) for a in ds.det_axes],
            n_frames=rows * cols,
            scan_shape_from_file=from_file,
            scan_shape_options=(
                []
                if from_file
                else [list(p) for p in scan_shape_candidates(rows * cols)]
            ),
        )
