"""Imaging-analysis endpoints: GPA, VDF, radial/azimuthal profiles,
roughness, interface width, lattice measure, CTF, montage (plan item 28 +
Tier-2 #7 — thin adapters over W3/W4 calc; derived maps register in the
session)."""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from fermiviewer.calc.calibration import spacing_at_column_scale, usable_spacing
from fermiviewer.calc.ctf import estimate_ctf
from fermiviewer.calc.eds_maps import virtual_dark_field
from fermiviewer.calc.fourier import fft_mask_inverse
from fermiviewer.calc.gpa import geometric_phase_analysis, gpa_mean_strain
from fermiviewer.calc.lattice import lattice_measure
from fermiviewer.calc.montage import montage as calc_montage
from fermiviewer.calc.profile_stats import fit_interface_width
from fermiviewer.calc.radial import azimuthal_integrate, radial_profile_stats
from fermiviewer.calc.raster import NoRasterError, raster_of
from fermiviewer.calc.roi import extract_rect_roi
from fermiviewer.calc.roughness import surface_roughness
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _raster(img_id: str) -> tuple[DataStruct, np.ndarray]:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    try:
        return ds, raster_of(ds)
    except NoRasterError:
        raise HTTPException(400, "1D spectra have no raster") from None


def _register(
    arr: np.ndarray,
    name: str,
    parent: DataStruct,
    parent_id: str,
    metadata: dict[str, object] | None = None,
) -> dict:
    derived = DataStruct(
        data=np.ascontiguousarray(arr),
        kind=DataKind.IMAGE,
        axes=(parent.axes[0], parent.axes[1]),
        metadata={"source": name, "parser": "derived", **(metadata or {})},
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
        "mean": gpa_mean_strain(res),
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
    """Radial average/max profile, or (azimuthal=True) a sector-masked
    azimuthal average.

    The non-azimuthal response additionally carries ``intensity_sigma``:
    the STANDARD ERROR OF THE MEAN per ring (sem = std/sqrt(n_pixels)) —
    how precisely each ring's average intensity is known. This is NOT the
    ring's own intensity spread (a much fatter quantity, sqrt(n) wider);
    see calc/radial.py::radial_profile_stats for that distinction. The
    frontend shades ``intensity`` ± ``intensity_sigma`` as a confidence
    band on the ring average, matching the composition-profile and
    fit-view bands (ANALYSIS_PRESENTATION_PLAN item 3). The field is
    additive and omitted for the azimuthal-integration branch, which does
    not compute per-ring statistics, and for old cached results — the
    frontend treats its absence as "no band".
    """
    ds, raster = _raster(req.image_id)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    # both extents when the image has them: the rings are then drawn in
    # physical space and the radii come back calibrated; otherwise the
    # calc bins in pixels and the column scale converts, as before
    spacing = usable_spacing(ds.pixel_spacing)
    sem: np.ndarray | None = None
    with value_error_as_422():
        if req.azimuthal:
            radii, intensity = azimuthal_integrate(
                raster, center=req.center, n_bins=req.n_bins,
                sector_min=req.sector_min, sector_max=req.sector_max,
                pixel_size=px, spacing=spacing,
            )
            avg = intensity
            mx = intensity
        else:
            radii, avg, mx, std, n = radial_profile_stats(
                raster, center=req.center, n_bins=req.n_bins, spacing=spacing,
            )
            if spacing is None:
                radii = radii * px
            with np.errstate(invalid="ignore", divide="ignore"):
                sem = std / np.sqrt(n)
    unit = ds.pixel_unit or "px"
    nan_to_none = [None if not np.isfinite(v) else float(v) for v in avg]
    result: dict = {
        "radii": radii.tolist(),
        "intensity": nan_to_none,
        "max_intensity": [
            None if not np.isfinite(v) else float(v) for v in mx
        ],
        "unit": unit,
    }
    if sem is not None:
        result["intensity_sigma"] = [
            None if not np.isfinite(v) else float(v) for v in sem
        ]
    return result


# ── roughness ─────────────────────────────────────────────────────────


class RoughnessRequest(BaseModel):
    image_id: str
    level: str = "plane"
    roi: tuple[int, int, int, int] | None = None  # 1-based, inclusive


@router.post("/analyze/roughness")
def analyze_roughness(req: RoughnessRequest) -> dict:
    ds, raster = _raster(req.image_id)
    try:
        raster = extract_rect_roi(raster, req.roi)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else 1.0
    try:
        r = surface_roughness(raster, pixel_size=px, level=req.level)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    # The full bearing curve has one point per pixel and can be millions of
    # values. Preserve its shape while bounding the interactive response.
    n_bearing = r.bearing_heights.size
    if n_bearing > 512:
        bearing_idx = np.linspace(0, n_bearing - 1, 512).round().astype(int)
    else:
        bearing_idx = np.arange(n_bearing)
    return {
        "Ra": r.ra, "Rq": r.rq, "Rz": r.rz, "Rsk": r.rsk, "Rku": r.rku,
        "Rp": r.rp, "Rv": r.rv, "SAR": r.sar,
        "unit": ds.pixel_unit or "px",
        "n_pixels": r.n_pixels,
        "level": r.level,
        "roi": list(req.roi) if req.roi is not None else None,
        "bearing_fraction": r.bearing_fraction[bearing_idx].tolist(),
        "bearing_heights": r.bearing_heights[bearing_idx].tolist(),
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
            # `px` is the column scale (a user override included); the row
            # extent follows the image's own ratio, or is `px` when it has none
            spacing=spacing_at_column_scale(px, ds.pixel_spacing),
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
    ds, raster = _raster(req.image_id)
    with value_error_as_422():
        res = estimate_ctf(
            raster, voltage_kv=req.voltage_kv, cs_mm=req.cs_mm,
            pixel_size=req.pixel_size_a,
            # the typed Å/px is the column scale; rows follow the image's ratio
            spacing=spacing_at_column_scale(req.pixel_size_a, ds.pixel_spacing),
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


# ── noise estimate (checklist F closer) ─────────────────────────────


class NoiseRequest(BaseModel):
    image_id: str
    method: str = "mad"
    roi: tuple[int, int, int, int] | None = None


@router.post("/analyze/noise")
def analyze_noise(req: NoiseRequest) -> dict:
    from fermiviewer.calc.texture import noise_estimate

    _, raster = _raster(req.image_id)
    try:
        analysis = extract_rect_roi(raster, req.roi)
        if min(analysis.shape) < 3:
            raise ValueError("noise analysis region must be at least 3×3 pixels")
        res = noise_estimate(analysis, method=req.method)
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
    # Keep the diagnostic payload bounded for very large rasters while the
    # regression itself continues to use every block in the pure calculation.
    n_blocks = int(res.block_means.size)
    if n_blocks > 512:
        sample = np.linspace(0, n_blocks - 1, 512, dtype=np.int64)
        block_means = res.block_means[sample]
        block_variances = res.block_variances[sample]
    else:
        block_means = res.block_means
        block_variances = res.block_variances
    return {
        "sigma": res.sigma,
        "snr_db": res.snr_db if np.isfinite(res.snr_db) else None,
        "snr_linear": res.snr_linear if np.isfinite(res.snr_linear) else None,
        "noise_type": res.noise_type,
        "method": res.method,
        "recommendation": rec,
        "roi": req.roi,
        "n_pixels": int(analysis.size),
        "block_size": 16,
        "n_blocks": n_blocks,
        "block_means": block_means.tolist(),
        "block_variances": block_variances.tolist(),
        "regression_slope": (
            res.regression_slope if np.isfinite(res.regression_slope) else None
        ),
        "regression_intercept": (
            res.regression_intercept if np.isfinite(res.regression_intercept) else None
        ),
        "regression_r_squared": (
            res.regression_r_squared
            if np.isfinite(res.regression_r_squared)
            else None
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
        try:
            raster = raster_of(ds)
        except NoRasterError:
            raise HTTPException(400, f"image {img_id} has no 2-D raster") from None
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
