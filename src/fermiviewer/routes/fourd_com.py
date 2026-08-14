"""COM-derived phase-contrast endpoints for 4D-STEM (PLAN_4DSTEM #7-#9).

Split out of `routes/fourd.py`, which carries the Phase-1 surface
(list/meta/nav/pattern/mean-pattern/reshape/virtual-detector) and was at
430 of its 500-line ceiling with the DPC (#8) and iDPC (#9) routes still
to land. The two modules share their dataset lookup, streamed block-size
cap and optional-center contract via `routes/_fourd_common.py`.

Thin adapters only — all real work lives in `calc/fourd/`.

RAM: `POST /api/fourd/{id}/com` streams row-blocks under the same
`block_rows_for_byte_cap` cap `/virtual-detector` uses, once, into two
scan-shaped maps (COMy, COMx), each registered as an ordinary derived 2D
image the same way `/nav` does. A null center costs one extra whole-cube
pass via `ds4.mean_pattern` (cached after first use) to seed an auto
center; an explicit center never touches `ds4.mean_pattern` at all.
`POST /api/fourd/{id}/dpc` pays the exact same streamed cost to obtain the
COM field, then runs `calc.fourd.dpc.dpc_maps` — pure numpy over three
already-small `(scan_y, scan_x)` arrays, negligible next to the streamed
pass. It is a SEPARATE route (not a `/com` response extension): #9 (iDPC)
also lands in this module and would otherwise need to edit the same shared
response schema, so each phase-contrast product gets its own route and
response type instead. `POST /api/fourd/{id}/idpc` pays the same streamed
cost again, then runs `calc.fourd.idpc.idpc_image` — one FFT-based
integration over the same small `(scan_y, scan_x)` field, also negligible
next to the streamed pass — and registers the ONE resulting phase-contrast
map (unlike `/com`/`/dpc`, which each register several).
"""

from __future__ import annotations

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field

from fermiviewer.calc.fourd.com import com_maps, resolve_center
from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.calc.fourd.dpc import DpcMaps, dpc_maps
from fermiviewer.calc.fourd.idpc import DEFAULT_HIGH_PASS_CUTOFF, idpc_image
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.models import ImageMeta
from fermiviewer.routes._arrays import value_error_as_422
from fermiviewer.routes._fourd_common import (
    block_rows_for_byte_cap,
    get_fourd,
    validate_optional_center,
)
from fermiviewer.session import store as image_store
from fermiviewer.session_fourd import fourd_store

router = APIRouter(prefix="/api")


def _resolve_and_stream_com(
    ds4: FourDDataset, center_ky: float | None, center_kx: float | None
) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Shared by `/com` and `/dpc`: resolve the descan center (recording
    the RESOLVED value, never the request's null — see `ComRequest`'s
    docstring for why), then stream the cube once into the COM maps.

    Returns ``(center_ky, center_kx, com_y_shift, com_x_shift)``.
    """
    if center_ky is not None and center_kx is not None:
        cy, cx = center_ky, center_kx
    else:
        # only the auto-center path pays for a (possibly first-touch,
        # whole-cube) mean_pattern access — an explicit center never does.
        with value_error_as_422():
            cy, cx = resolve_center(None, ds4.mean_pattern)

    block_rows = block_rows_for_byte_cap(ds4)
    with value_error_as_422():
        com_y, com_x = com_maps(
            ds4.iter_scan_rows(block_rows=block_rows), center=(cy, cx)
        )
    return cy, cx, com_y, com_x


class ComRequest(BaseModel):
    """Descan reference center in 0-based ``(ky, kx)`` float pixels (see
    `calc/fourd/geometry.py`). A null ``center_ky``/``center_kx`` pair
    auto-seeds from ``pattern_center(mean_pattern)`` — the SAME auto-center
    policy `/virtual-detector` uses. The policy itself lives in
    `calc.fourd.resolve_center` (this route does no math); the route calls
    it explicitly so it can RECORD the resolved center on both maps."""

    center_ky: float | None = None
    center_kx: float | None = None
    name: str | None = None


class ComMapsResponse(BaseModel):
    """Both derived maps from one `/com` call, each an ordinary registered
    2D image (own id, own metadata) — this wrapper is just the pair."""

    comy: ImageMeta
    comx: ImageMeta


def _register_fourd_map(
    map_arr: np.ndarray,
    *,
    fourd_id: str,
    ds4: FourDDataset,
    parser: str,
    analysis: str,
    label: str,
    base_name: str,
    req_name: str | None,
    extra_metadata: dict[str, float | str],
) -> ImageMeta:
    """Register one scan-shaped derived map — shared by every `/com`/`/dpc`
    output. ``analysis``/``extra_metadata`` land verbatim in the image's
    metadata (surfaced to clients as `ImageMeta.meta`); ``label`` only
    controls the default display name."""
    name = f"{req_name} ({label})" if req_name else f"{label}({base_name})"
    struct = DataStruct(
        data=np.ascontiguousarray(map_arr),
        kind=DataKind.IMAGE,
        axes=(ds4.scan_axes[0], ds4.scan_axes[1]),
        metadata={
            "source": name,
            "parser": parser,
            "analysis": analysis,
            "fourd_id": fourd_id,
            **extra_metadata,
        },
    )
    img_id = image_store.add_derived(struct, name, fourd_id)
    return ImageMeta.from_datastruct(img_id, image_store.name(img_id), struct)


@router.post("/fourd/{fourd_id}/com")
def fourd_com(fourd_id: str, req: ComRequest) -> ComMapsResponse:
    """Per-probe center-of-mass shift maps — the basis for DPC/iDPC
    (PLAN_4DSTEM #8/#9). Registers COMy and COMx as two ordinary derived 2D
    images through the same `add_derived` path `/nav` and
    `/virtual-detector` use, so they inherit LUT/measure/export for free
    (same always-register convention as `/virtual-detector`: each call is a
    distinct analysis, not deduplicated like `/nav`).

    All center-resolution policy (caller-supplied vs.
    ``pattern_center(mean_pattern)`` auto-seed) lives in
    `calc.fourd.com.com_maps` — this route only validates the request,
    streams the cube once, and registers the two results. See the module
    docstring for the RAM budget.
    """
    ds4 = get_fourd(fourd_id)
    validate_optional_center(req.center_ky, req.center_kx, ds4.det_shape)
    cy, cx, com_y, com_x = _resolve_and_stream_com(ds4, req.center_ky, req.center_kx)

    base_name = fourd_store.name(fourd_id)
    center_meta: dict[str, float | str] = {
        "center_ky": float(cy),
        "center_kx": float(cx),
    }

    def _register(map_arr: np.ndarray, axis: str, label: str) -> ImageMeta:
        return _register_fourd_map(
            map_arr,
            fourd_id=fourd_id,
            ds4=ds4,
            parser="fourd-com",
            analysis=axis,
            label=label,
            base_name=base_name,
            req_name=req.name,
            extra_metadata=center_meta,
        )

    return ComMapsResponse(
        comy=_register(com_y, "com_y", "COMy"),
        comx=_register(com_x, "com_x", "COMx"),
    )


# ── differential phase contrast (PLAN_4DSTEM #8) ───────────────────────


class DpcRequest(BaseModel):
    """Same descan-center contract as `ComRequest` (see its docstring), plus
    the ONE calibration this whole endpoint exists to apply:
    ``mrad_per_px`` — the detector's isotropic milliradians-per-pixel scale.

    That calibration is not reliably available on every `FourDDataset` (a
    bare `.mib` with no `.hdr` sidecar is uncalibrated) and is never
    guessed here — required, with no default, so a client that has not
    actually calibrated its detector cannot silently get a `1.0`-scaled
    "field" that is really just the raw pixel-shift map relabeled. See
    `calc/fourd/dpc.py`'s module docstring for the full rationale.
    """

    center_ky: float | None = None
    center_kx: float | None = None
    mrad_per_px: float = Field(gt=0)
    name: str | None = None


class DpcMapsResponse(BaseModel):
    """Three derived maps from one `/dpc` call, each an ordinary registered
    2D image. See `calc/fourd/dpc.py`'s `DpcMaps` for the units of each."""

    magnitude: ImageMeta
    direction: ImageMeta
    divergence: ImageMeta


@router.post("/fourd/{fourd_id}/dpc")
def fourd_dpc(fourd_id: str, req: DpcRequest) -> DpcMapsResponse:
    """Differential phase contrast: magnitude/direction of the calibrated
    COM deflection field, plus its divergence (projected charge density by
    Gauss's law). A SEPARATE route from `/com` (not a response extension of
    it) — see the module docstring for why, and PLAN_4DSTEM #8.

    All math lives in `calc.fourd.dpc.dpc_maps` — this route validates the
    request, resolves the descan center and streams the cube exactly once
    (identical cost to `/com`, see the module docstring for the RAM
    budget), then registers the three results, recording the resolved
    center AND the calibration used on every map's metadata.
    """
    ds4 = get_fourd(fourd_id)
    validate_optional_center(req.center_ky, req.center_kx, ds4.det_shape)
    cy, cx, com_y, com_x = _resolve_and_stream_com(ds4, req.center_ky, req.center_kx)

    with value_error_as_422():
        maps: DpcMaps = dpc_maps(com_y, com_x, req.mrad_per_px)

    base_name = fourd_store.name(fourd_id)
    shared_meta: dict[str, float | str] = {
        "center_ky": float(cy),
        "center_kx": float(cx),
        "mrad_per_px": float(req.mrad_per_px),
    }

    def _register(
        map_arr: np.ndarray,
        axis: str,
        label: str,
        units: str,
        interpretation: str | None = None,
    ) -> ImageMeta:
        extra: dict[str, float | str] = {**shared_meta, "units": units}
        if interpretation is not None:
            extra["interpretation"] = interpretation
        return _register_fourd_map(
            map_arr,
            fourd_id=fourd_id,
            ds4=ds4,
            parser="fourd-dpc",
            analysis=axis,
            label=label,
            base_name=base_name,
            req_name=req.name,
            extra_metadata=extra,
        )

    return DpcMapsResponse(
        magnitude=_register(maps.magnitude_mrad, "dpc_magnitude", "DPCmagnitude", "mrad"),
        direction=_register(maps.direction_rad, "dpc_direction", "DPCdirection", "rad"),
        # Labelled for what it MEASURABLY is, not for its interpretation:
        # this is the divergence of the deflection field, in mrad per scan
        # pixel. It is proportional to projected charge density, but the
        # constant relating them needs the specimen thickness, the
        # accelerating voltage and the physical scan pitch, none of which
        # this route has (see divergence_map's docstring). A map on the
        # Stage reading "ChargeDensity" in units of mrad/scan-px invites
        # exactly the misreading the calc layer is careful to avoid — the
        # interpretation belongs in metadata, where it can carry its
        # caveat, not in the name.
        divergence=_register(
            maps.divergence,
            "dpc_divergence",
            "DPCdivergence",
            "mrad_per_scan_px",
            interpretation=(
                "proportional to projected charge density (Gauss's law); "
                "absolute density needs specimen thickness, accelerating "
                "voltage and the physical scan pixel pitch"
            ),
        ),
    )


# ── integrated differential phase contrast (PLAN_4DSTEM #9) ────────────


class IdpcRequest(BaseModel):
    """Same descan-center + `mrad_per_px` calibration contract as
    `DpcRequest` (see its docstring), plus the ONE knob unique to iDPC:
    ``high_pass_cutoff`` — the Gaussian high-pass cutoff, in cycles per
    scan pixel, that suppresses the low-frequency reconstruction artifact
    (see `calc/fourd/idpc.py`'s module docstring for the full derivation).
    Optional, defaulting to `idpc.DEFAULT_HIGH_PASS_CUTOFF` — the calc
    module's own documented default, not re-invented here."""

    center_ky: float | None = None
    center_kx: float | None = None
    mrad_per_px: float = Field(gt=0)
    high_pass_cutoff: float = Field(default=DEFAULT_HIGH_PASS_CUTOFF, ge=0)
    name: str | None = None


@router.post("/fourd/{fourd_id}/idpc")
def fourd_idpc(fourd_id: str, req: IdpcRequest) -> ImageMeta:
    """Integrated DPC (iDPC): Fourier-space integration of the calibrated
    COM deflection field into a single phase-contrast image (PLAN_4DSTEM
    #9). All math lives in `calc.fourd.idpc.idpc_image` — this route
    validates the request, resolves the descan center and streams the cube
    exactly once (identical cost/path to `/com` and `/dpc`, see the module
    docstring for the RAM budget), then registers the ONE resulting map,
    recording the resolved center, the `mrad_per_px` calibration used AND
    the `high_pass_cutoff` applied in its metadata.

    Unlike `/com`/`/dpc`, this registers a SINGLE image (an `ImageMeta`
    directly, not a wrapper response) — iDPC produces one phase-contrast
    map, not a family of derived maps, matching `/nav`'s and
    `/virtual-detector`'s single-image response shape.
    """
    ds4 = get_fourd(fourd_id)
    validate_optional_center(req.center_ky, req.center_kx, ds4.det_shape)
    cy, cx, com_y, com_x = _resolve_and_stream_com(ds4, req.center_ky, req.center_kx)

    with value_error_as_422():
        map_arr = idpc_image(com_y, com_x, req.mrad_per_px, req.high_pass_cutoff)

    base_name = fourd_store.name(fourd_id)
    return _register_fourd_map(
        map_arr,
        fourd_id=fourd_id,
        ds4=ds4,
        parser="fourd-idpc",
        analysis="idpc",
        label="iDPC",
        base_name=base_name,
        req_name=req.name,
        extra_metadata={
            "center_ky": float(cy),
            "center_kx": float(cx),
            "mrad_per_px": float(req.mrad_per_px),
            "high_pass_cutoff": float(req.high_pass_cutoff),
            # mrad * scan px, NOT plain mrad: the integration is with
            # respect to the scan-pixel index, so it multiplies by a scan
            # pixel exactly as /dpc's divergence divides by one. The scale
            # therefore depends on the scan step — see idpc.py's UNITS note.
            "units": "mrad_scan_px",
            # What this measurably is, not what it is popularly called: see
            # calc/fourd/idpc.py's module docstring for the full accounting
            # of the accelerating-voltage/electron-wavelength and physical
            # scan-pixel-pitch constants an absolute potential in volts
            # would additionally require — neither is invented here.
            "interpretation": (
                "proportional to the projected potential (phase image) up to "
                "an unrecoverable additive constant; absolute phase/potential "
                "needs the accelerating voltage (electron wavelength) and the "
                "physical scan pixel pitch"
            ),
        },
    )
