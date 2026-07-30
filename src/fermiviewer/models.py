"""Pydantic API models — the wire types (handoff §8).

Kept separate from the internal DataStruct on purpose: wire schemas
evolve with the frontend; the internal contract evolves with analysis.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel

from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.io.metadata import get_stage_tilt

__all__ = ["ImageMeta", "OpenRequest"]


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
    meta: dict[str, Any] = {}

    @classmethod
    def from_datastruct(cls, img_id: str, name: str, ds: DataStruct) -> ImageMeta:
        spectral = ds.kind is not DataKind.IMAGE
        px = None
        unit = ""
        if ds.kind is not DataKind.SPECTRUM and ds.pixel_cal.calibrated:
            px, unit = ds.pixel_cal.scale, ds.pixel_cal.units
        ax = ds.energy_axis if spectral else None
        tilt_deg, _ = get_stage_tilt(ds.metadata)
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
            energy_first=float(ax[0]) if ax is not None else None,
            energy_last=float(ax[-1]) if ax is not None else None,
            energy_units=ds.energy_cal.units if spectral else "",
            stage_tilt_deg=None if math.isnan(tilt_deg) else tilt_deg,
            meta=_public_meta(ds.metadata),
        )
