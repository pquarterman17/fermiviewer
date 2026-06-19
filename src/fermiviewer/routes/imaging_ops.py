"""Imaging-analysis endpoints: GPA, VDF, radial/azimuthal profiles,
roughness, interface width, lattice measure, CTF, montage (plan item 28 +
Tier-2 #7 — thin adapters over W3/W4 calc; derived maps register in the
session)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.ctf import estimate_ctf
from fermiviewer.calc.eds_maps import virtual_dark_field
from fermiviewer.calc.fourier import fft_mask_inverse
from fermiviewer.calc.gpa import geometric_phase_analysis
from fermiviewer.calc.lattice import lattice_measure
from fermiviewer.calc.montage import montage as calc_montage
from fermiviewer.calc.profiles import fit_interface_width
from fermiviewer.calc.radial import azimuthal_integrate, radial_profile
from fermiviewer.calc.roughness import surface_roughness
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is DataKind.IMAGE:
        return ds, np.asarray(ds.data, dtype=np.float64)
    if ds.kind is DataKind.SPECTRUM_IMAGE:
        summed: np.ndarray = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        return ds, summed
    raise HTTPException(400, "1D spectra have no raster")


def _register(
    arr: np.ndarray, name: str, parent: DataStruct, parent_id: str
) -> dict:
    derived = DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"source": name, "parser": "derived"},
    )
    new_id = store.add_derived(derived, name, parent_id)
    return ImageMeta.from_datastruct(new_id, name, derived).model_dump()


# ── GPA ───────────────────────────────────────────────────────────────


class GpaRequest(BaseModel):
    image_id: str
    g1: tuple[float, float]  # (gx, gy) FFT-pixel offsets from centre
    g2: tuple[float, float]
    mask_radius: float = 0.0
    mask_order: float = 2.0
    pixel_size: float = 1.0


@router.post("/analyze/gpa")
def analyze_gpa(req: GpaRequest) -> dict:
    ds, raster = _raster(req.image_id)
    try:
        res = geometric_phase_analysis(
            raster, req.g1, req.g2,
            mask_radius=req.mask_radius,
            mask_order=req.mask_order,
            pixel_size=req.pixel_size,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = store.name(req.image_id)
    maps = {
        "exx": res.exx, "eyy": res.eyy,
        "exy": res.exy, "rotation": res.rotation,
    }
    return {
        "maps": [
            _register(m, f"{key}({name})", ds, req.image_id)
            for key, m in maps.items()
        ],
        "mean": {k: float(np.nanmean(m)) for k, m in maps.items()},
    }


# ── VDF ───────────────────────────────────────────────────────────────


class VdfRequest(BaseModel):
    image_id: str
    center: tuple[float, float]  # (row, col), 1-based, fftshifted
    radius: float = 10.0
    shape: str = "circle"
    inner_radius: float = 0.0


@router.post("/analyze/vdf")
def analyze_vdf(req: VdfRequest) -> dict:
    ds, raster = _raster(req.image_id)
    try:
        out = virtual_dark_field(
            raster, req.center, mask_radius=req.radius,
            mask_shape=req.shape, inner_radius=req.inner_radius,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = store.name(req.image_id)
    return {"image": _register(out, f"VDF({name})", ds, req.image_id)}


# ── FFT mask + inverse (mask editor backend) ─────────────────────────


class FftMaskRequest(BaseModel):
    image_id: str
    masks: list[tuple[float, float, float]]  # (row, col, radius), 1-based
    mode: str = "pass"


@router.post("/analyze/fft-mask")
def analyze_fft_mask(req: FftMaskRequest) -> dict:
    ds, raster = _raster(req.image_id)
    try:
        out = fft_mask_inverse(raster, req.masks, mode=req.mode)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = store.name(req.image_id)
    label = "FFTpass" if req.mode == "pass" else "FFTreject"
    return {"image": _register(out, f"{label}({name})", ds, req.image_id)}


# ── radial / azimuthal profiles ──────────────────────────────────────


class RadialRequest(BaseModel):
    image_id: str
    center: tuple[float, float] | None = None  # (x, y) 1-based
    n_bins: int = 0
    sector_min: float = 0.0
    sector_max: float = 360.0
    azimuthal: bool = False


@router.post("/analyze/radial")
def analyze_radial(req: RadialRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    if req.azimuthal:
        radii, intensity = azimuthal_integrate(
            raster, center=req.center, n_bins=req.n_bins,
            sector_min=req.sector_min, sector_max=req.sector_max,
            pixel_size=px,
        )
        avg = intensity
        mx = intensity
    else:
        radii_px, avg, mx = radial_profile(
            raster, center=req.center, n_bins=req.n_bins
        )
        radii = radii_px * px
    unit = ds.pixel_unit or "px"
    nan_to_none = [None if not np.isfinite(v) else float(v) for v in avg]
    return {
        "radii": radii.tolist(),
        "intensity": nan_to_none,
        "max_intensity": [
            None if not np.isfinite(v) else float(v) for v in mx
        ],
        "unit": unit,
    }


# ── roughness ─────────────────────────────────────────────────────────


class RoughnessRequest(BaseModel):
    image_id: str
    level: str = "plane"


@router.post("/analyze/roughness")
def analyze_roughness(req: RoughnessRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    try:
        r = surface_roughness(raster, pixel_size=px, level=req.level)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "Ra": r.ra, "Rq": r.rq, "Rz": r.rz, "Rsk": r.rsk, "Rku": r.rku,
        "Rp": r.rp, "Rv": r.rv, "SAR": r.sar,
        "unit": ds.pixel_unit or "px",
        "n_pixels": r.n_pixels,
    }


# ── interface width (fits the current profile) ───────────────────────


class InterfaceRequest(BaseModel):
    x: list[float]
    y: list[float]
    model: str = "erf"


@router.post("/analyze/interface-width")
def analyze_interface(req: InterfaceRequest) -> dict:
    try:
        fit = fit_interface_width(
            np.asarray(req.x), np.asarray(req.y), model=req.model
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "center": fit.center,
        "sigma": fit.sigma,
        "width_10_90": fit.width_10_90,
        "amplitude": fit.amplitude,
        "offset": fit.offset,
        "r_squared": fit.r_squared,
        "x_fit": fit.x_fit.tolist(),
        "y_fit": fit.y_fit.tolist(),
        "model": fit.model,
    }


# ── lattice measure (two FFT spot picks) ─────────────────────────────


class LatticeRequest(BaseModel):
    image_id: str
    spot1: tuple[float, float]  # (row, col), 1-based on the FFT image
    spot2: tuple[float, float]
    pixel_size: float | None = None  # real-space; default from cal


@router.post("/analyze/lattice")
def analyze_lattice(req: LatticeRequest) -> dict:
    ds, raster = _raster(req.image_id)
    px = req.pixel_size
    if px is None:
        px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    try:
        res = lattice_measure(
            req.spot1, req.spot2,
            (raster.shape[0], raster.shape[1]),
            pixel_size=px,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "a": res.a, "b": res.b, "gamma_deg": res.gamma_deg,
        "d_spacing1": res.d_spacing1, "d_spacing2": res.d_spacing2,
        "unit_cell_area": res.unit_cell_area,
        "unit": ds.pixel_unit or "px",
    }


# ── CTF ───────────────────────────────────────────────────────────────


class CtfRequest(BaseModel):
    image_id: str
    voltage_kv: float = 200.0
    cs_mm: float = 1.2
    pixel_size_a: float = Field(default=1.0, gt=0)  # Å/px


@router.post("/analyze/ctf")
def analyze_ctf(req: CtfRequest) -> dict:
    _, raster = _raster(req.image_id)
    res = estimate_ctf(
        raster, voltage_kv=req.voltage_kv, cs_mm=req.cs_mm,
        pixel_size=req.pixel_size_a,
    )
    return {
        "defocus_a": res.defocus,
        "defocus_nm": res.defocus_nm,
        "r_squared": res.r_squared,
        "lambda_a": res.lambda_a,
        "radial_freq": res.radial_freq.tolist(),
        "radial_power": res.radial_power.tolist(),
        "ctf_fit": res.ctf_fit.tolist(),
    }


# ── noise estimate + defect count (checklist F closers) ─────────────


class NoiseRequest(BaseModel):
    image_id: str
    method: str = "mad"


@router.post("/analyze/noise")
def analyze_noise(req: NoiseRequest) -> dict:
    from fermiviewer.calc.texture import noise_estimate

    _, raster = _raster(req.image_id)
    try:
        res = noise_estimate(raster, method=req.method)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    # filter recommendation mirrors the MATLAB heuristic: Poisson-like
    # noise → median; Gaussian-like → gaussian; low SNR → stronger
    if res.noise_type == "poisson":
        rec = "median (window 3–5)"
    elif res.snr_db < 10:
        rec = "gaussian (sigma 2) — low SNR"
    else:
        rec = "gaussian (sigma 1)"
    return {
        "sigma": res.sigma,
        "snr_db": res.snr_db,
        "snr_linear": res.snr_linear,
        "noise_type": res.noise_type,
        "method": res.method,
        "recommendation": rec,
    }


class DefectsRequest(BaseModel):
    image_id: str
    direction: float | None = None
    kernel_length: int = 15
    grid_spacing: int = 50


@router.post("/analyze/defects")
def analyze_defects(req: DefectsRequest) -> dict:
    from fermiviewer.calc.defects import count_defect_lines

    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    try:
        res = count_defect_lines(
            raster, direction=req.direction,
            kernel_length=req.kernel_length,
            grid_spacing=req.grid_spacing,
            pixel_size=px, pixel_unit=ds.pixel_unit or "px",
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    name = store.name(req.image_id)
    return {
        "intersections": res.intersection_count,
        "test_lines": res.num_test_lines,
        "density": res.density,
        "density_unit": res.density_unit,
        "enhanced": _register(
            res.enhanced, f"defects({name})", ds, req.image_id,
        ),
    }


# ── montage (Tier-2 #7) ───────────────────────────────────────────────


class MontageRequest(BaseModel):
    image_ids: list[str]
    cols: int | None = None          # None → ceil(sqrt(n)); mirrors auto mode
    labels: bool = True              # bake per-tile labels (frame name)
    gap: int = Field(default=4, ge=0, le=64)   # px gap between tiles
    bg: float = 0.0                  # background fill value
    overlap: float = Field(default=0.0, ge=0.0, lt=1.0)  # fractional overlap
    font_size: int = Field(default=14, ge=6, le=48)


@router.post("/analyze/montage")
def analyze_montage(req: MontageRequest) -> dict:
    """Arrange selected images into a labeled-tile montage grid.

    Mirrors executeMontage.m layout arithmetic (tile step, weight-averaged
    overlap regions, ceil(n/cols) rows).  The composite is registered as a
    derived library image so it appears in the filmstrip immediately.

    Request
    -------
    image_ids : list[str]   — at least 2 image IDs (1 is allowed for testing)
    cols      : int | null  — grid columns; null → ceil(sqrt(n))
    labels    : bool        — bake the source image name into each tile
    gap       : int         — inter-tile gap in pixels (ignored when overlap>0)
    bg        : float       — background fill (default 0.0)
    overlap   : float       — fractional overlap [0,1); 0 = no overlap
    font_size : int         — label font size in pixels

    Response
    --------
    {"image": <ImageMeta>}  — the registered derived montage image
    """
    if len(req.image_ids) < 1:
        raise HTTPException(422, "montage: provide at least 1 image id")

    pairs: list[tuple] = []
    for img_id in req.image_ids:
        try:
            ds = store.get(img_id)
        except UnknownImageError:
            raise HTTPException(404, f"unknown image id: {img_id}") from None
        if ds.kind is DataKind.IMAGE:
            raster = np.asarray(ds.data, dtype=np.float64)
        elif ds.kind is DataKind.SPECTRUM_IMAGE:
            raster = np.asarray(ds.data, dtype=np.float64).sum(axis=2)
        else:
            raise HTTPException(400, f"image {img_id} has no 2-D raster")
        pairs.append((ds, raster))

    frames = [r for _, r in pairs]
    tile_labels: list[str] | None = None
    if req.labels:
        tile_labels = [store.name(img_id) for img_id in req.image_ids]

    try:
        out = calc_montage(
            frames,
            cols=req.cols,
            labels=tile_labels,
            gap=req.gap,
            bg=req.bg,
            overlap=req.overlap,
            font_size=req.font_size,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None

    n = len(req.image_ids)
    name = f"montage({n})"
    parent_ds, _ = pairs[0]
    result = _register(out, name, parent_ds, req.image_ids[0])
    return {"image": result}
