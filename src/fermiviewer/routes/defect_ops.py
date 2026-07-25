"""Defect-line analysis route with inspectable diagnostic outputs."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.defects import count_defect_lines
from fermiviewer.calc.roi import embed_rect_roi
from fermiviewer.routes.imaging_ops import _raster, _register
from fermiviewer.session import store

router = APIRouter(prefix="/api")


class DefectsRequest(BaseModel):
    image_id: str
    direction: float | None = None
    kernel_length: int = Field(15, ge=1)
    grid_spacing: int = Field(50, ge=1)
    roi: tuple[int, int, int, int] | None = None
    foil_thickness: float | None = Field(default=None, gt=0)


@router.post("/analyze/defects")
def analyze_defects(req: DefectsRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else 1.0
    try:
        res = count_defect_lines(
            raster,
            roi=req.roi,
            direction=req.direction,
            kernel_length=req.kernel_length,
            grid_spacing=req.grid_spacing,
            foil_thickness=(
                req.foil_thickness
                if req.foil_thickness is not None
                else float("nan")
            ),
            pixel_size=px,
            pixel_unit=ds.pixel_unit or "px",
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None

    name = store.name(req.image_id)
    enhanced = embed_rect_roi(res.enhanced, raster.shape, req.roi)
    binary_mask = embed_rect_roi(
        res.binary_mask.astype(np.uint8), raster.shape, req.roi,
    )
    provenance: dict[str, object] = {
        "analysis": "defects",
        "direction": "sweep" if req.direction is None else req.direction,
        "kernel_length": req.kernel_length,
        "grid_spacing": req.grid_spacing,
        "foil_thickness": req.foil_thickness,
        "roi": req.roi,
    }
    return {
        "intersections": res.intersection_count,
        "test_lines": res.num_test_lines,
        "total_line_length": res.total_line_length,
        "density": res.density,
        "density_unit": res.density_unit,
        "pixel_unit": ds.pixel_unit or "px",
        "roi": req.roi,
        "h_rows": res.h_rows.tolist(),
        "v_cols": res.v_cols.tolist(),
        "enhanced": _register(
            enhanced,
            f"defects({name})",
            ds,
            req.image_id,
            {**provenance, "diagnostic": "enhanced_response"},
        ),
        "mask": _register(
            binary_mask,
            f"defect mask({name})",
            ds,
            req.image_id,
            {**provenance, "diagnostic": "binary_mask"},
        ),
    }
