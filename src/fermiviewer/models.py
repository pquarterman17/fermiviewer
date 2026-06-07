"""Pydantic API models — the wire types (handoff §8).

Kept separate from the internal DataStruct on purpose: wire schemas
evolve with the frontend; the internal contract evolves with analysis.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from fermiviewer.datastruct import DataKind, DataStruct

__all__ = ["ImageMeta", "OpenRequest"]


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
    n_channels: int | None = None
    energy_first: float | None = None
    energy_last: float | None = None
    energy_units: str = ""
    meta: dict[str, Any] = {}

    @classmethod
    def from_datastruct(cls, img_id: str, name: str, ds: DataStruct) -> ImageMeta:
        spectral = ds.kind is not DataKind.IMAGE
        px = None
        unit = ""
        if ds.kind is not DataKind.SPECTRUM and ds.pixel_cal.calibrated:
            px, unit = ds.pixel_cal.scale, ds.pixel_cal.units
        ax = ds.energy_axis if spectral else None
        return cls(
            id=img_id,
            name=name,
            kind=ds.kind,
            shape=list(ds.data.shape),
            dtype=str(ds.data.dtype),
            pixel_size=px,
            pixel_unit=unit,
            n_channels=ds.n_channels if spectral else None,
            energy_first=float(ax[0]) if ax is not None else None,
            energy_last=float(ax[-1]) if ax is not None else None,
            energy_units=ds.energy_cal.units if spectral else "",
            meta={
                k: v
                for k, v in ds.metadata.items()
                if isinstance(v, (int, float, str, bool)) and k != "image_tags"
            },
        )
