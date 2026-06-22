"""Advanced EELS deconvolution endpoints (PLAN_SPECTRAL_QUANT #10).

Thin adapters over calc/eels_advanced for the deconvolution additions —
sub-pixel ZLP alignment and Richardson–Lucy resolution recovery. Its own
module because routes/analysis.py (which holds the original EELS-advanced
quintet) is at the 500-line ceiling. Fourier-ratio is a calc primitive
(needs a separate low-loss spectrum); its endpoint is a follow-up.
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eels_advanced import align_zlp, richardson_lucy
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _get(img_id: str) -> DataStruct:
    try:
        return store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None


def _cube(img_id: str) -> DataStruct:
    ds = _get(img_id)
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise HTTPException(400, "requires a spectrum-image cube")
    return ds


def _spectral(img_id: str) -> DataStruct:
    ds = _get(img_id)
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "image has no spectral axis")
    return ds


def _register_cube(arr: np.ndarray, name: str, parent: DataStruct,
                   parent_id: str) -> ImageMeta:
    derived = DataStruct(
        data=np.ascontiguousarray(arr), kind=DataKind.SPECTRUM_IMAGE,
        axes=parent.axes, metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived)


class EelsSubpixelAlignRequest(BaseModel):
    image_id: str
    window: tuple[float, float] = (-20.0, 20.0)
    reference: str = "mean"               # | "max"


@router.post("/eels/subpixel-align")
def eels_subpixel_align(req: EelsSubpixelAlignRequest) -> dict:
    """Sub-pixel ZLP alignment (parabolic peak refine + fractional FFT
    shift). Registers the aligned cube as a derived spectrum-image."""
    ds = _cube(req.image_id)
    try:
        aligned, shifts = align_zlp(
            ds.data, ds.energy_axis, req.window, req.reference, subpixel=True,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    meta = _register_cube(aligned, "ZLP aligned (sub-pixel)", ds, req.image_id)
    return {
        "aligned": meta.model_dump(),
        "max_shift": float(np.abs(shifts).max()),
        "shifted_fraction": float((np.abs(shifts) > 0.01).mean()),
    }


class EelsRichardsonLucyRequest(BaseModel):
    image_id: str
    zlp_window: tuple[float, float] = (-5.0, 5.0)
    iterations: int = 15


@router.post("/eels/richardson-lucy")
def eels_richardson_lucy(req: EelsRichardsonLucyRequest) -> dict:
    """Richardson–Lucy deconvolution of the summed spectrum using its own
    ZLP (from ``zlp_window``) as the point-spread function — recovers
    resolution lost to the ZLP. Returns the spectrum + deconvolved curve."""
    ds = _spectral(req.image_id)
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    ne = spectrum.size

    mask = (energy >= req.zlp_window[0]) & (energy <= req.zlp_window[1])
    if int(mask.sum()) < 2:
        raise HTTPException(422, "ZLP window has fewer than 2 channels")
    psf = np.zeros(ne)
    psf[mask] = np.maximum(spectrum[mask], 0.0)
    if psf.sum() <= 0:
        raise HTTPException(422, "no ZLP intensity in the window")
    # centre the ZLP peak at the array midpoint so RL does not shift the result
    psf = np.roll(psf, ne // 2 - int(np.argmax(psf)))

    try:
        deconv = richardson_lucy(spectrum, psf, iterations=req.iterations)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    return {
        "energy": energy.tolist(),
        "spectrum": spectrum.tolist(),
        "deconvolved": deconv.tolist(),
        "iterations": req.iterations,
    }
