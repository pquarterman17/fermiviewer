"""Advanced-EELS operation catalogue — wave D (roadmap 3E): batch/scripting
reach for the deconvolution/decomposition suite behind ``routes/analysis.py``
and ``routes/eels_advanced.py``.

Same rule as every wave catalogue (ADR 0005 §1): each op calls the SAME pure
``calc/eels_advanced`` composition its route calls — no reimplemented physics.
The `eels` category implies nothing about the result shape, so the four value
ops set ``produces_value=True`` explicitly and the two alignment ops leave it
UNSET (they produce a derived cube).

Wave-D rules exercised here (ADR 0005, wave-D addendum):

- **Modes without an op**: `eels_svd` drops the route's ``denoise`` flag —
  ``produces_value_result`` is a schema-time predicate, and a spec whose
  payload kind depends on a param cannot exist. The denoised-cube mode is
  annotated "no op" in the audit.
- **Derived DataStructs + metadata diagnostics**: the aligned SI cubes from
  `eels_align_zlp` / `eels_subpixel_align` stay in ``OpResult.derived`` (ADR
  0004 has no cube kind to inline as); their scalar diagnostics (``max_shift``,
  ``shifted_fraction``) ride ``derived.metadata`` — the `savgol_derivative`
  precedent. Each op mirrors its OWN route's diagnostic spelling: integer
  alignment reports ``int(|shifts|.max())`` and the ``shifts != 0`` fraction,
  sub-pixel reports the float max and the ``|shifts| > 0.01`` fraction.

Spectral/cube guards mirror the routes' 400 checks as ``ValueError``. The
curve envelopes label x with the input's own energy-axis units rather than
hard-coding eV — the calcs, like the routes, assume eV physics but never
check it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from fermiviewer.calc.eels_advanced import (
    align_zlp,
    fourier_log,
    kramers_kronig,
    richardson_lucy,
    svd,
    zlp_psf,
)
from fermiviewer.calc.eels_report import svd_view
from fermiviewer.datastruct import SPECTRAL_KINDS, DataKind, DataStruct
from fermiviewer.ops._envelopes import nan_none, output, scalar
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


def _require_spectral(ds: DataStruct, opname: str) -> None:
    """The routes' `_spectral` 400 guard, as ValueError."""
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"{opname} requires spectral input (got {ds.kind.value})")


def _require_cube(ds: DataStruct, opname: str) -> None:
    """The routes' `_cube` 400 guard, as ValueError."""
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(f"{opname} requires a spectrum-image cube (got {ds.kind.value})")


def _curve(
    name: str,
    x: Any,
    y: Any,
    *,
    x_name: str = "energy",
    x_unit: str = "",
    y_name: str = "intensity",
    y_unit: str = "",
) -> dict[str, Any]:
    return output(
        "curve",
        name,
        {
            "x_name": x_name,
            "x_unit": x_unit,
            "y_name": y_name,
            "y_unit": y_unit,
            "x": np.asarray(x).tolist(),
            "y": np.asarray(y).tolist(),
        },
    )


def _map_values(arr: np.ndarray) -> list[list[float | None]]:
    """2-D raster as nested lists, NaN/inf -> None so the inline envelope
    survives JSON (the wave-B `map` rule)."""
    return [[nan_none(float(v)) for v in row] for row in arr]


def _zlp_window_params(doc_what: str) -> dict[str, OpParam]:
    """The ``zlp_window: tuple = (-5, 5)`` request field, flattened to the
    blessed lo/hi pair (kk, fourier_log, richardson_lucy share the default)."""
    return {
        "zlp_lo": OpParam(float, -5.0, doc=f"{doc_what} lower edge (eV)"),
        "zlp_hi": OpParam(float, 5.0, doc=f"{doc_what} upper edge (eV)"),
    }


# ── Kramers-Kronig dielectric analysis ────────────────────────────────


def _eels_kk(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_spectral(ds, "eels_kk")
    # NaN params pass straight through: NaN IS the calc's own "not given"
    # default for refractive_index (unnormalised ELF) and thickness
    # (estimate from t/λ) — exactly the route's None → nan mapping.
    res = kramers_kronig(
        ds.energy_axis,
        ds.sum_spectrum(),
        (params["zlp_lo"], params["zlp_hi"]),
        refractive_index=params["refractive_index"],
        collection_angle=params["collection_angle_mrad"],
        acc_voltage=params["acc_voltage_kv"],
        thickness=params["thickness_nm"],
    )
    e_unit = ds.energy_cal.units
    outputs = [
        _curve("eps1", res.energy, res.eps1, x_unit=e_unit, y_name="Re(eps)"),
        _curve("eps2", res.energy, res.eps2, x_unit=e_unit, y_name="Im(eps)"),
        _curve("elf", res.energy, res.elf, x_unit=e_unit, y_name="energy-loss function"),
        _curve(
            "optical_conductivity",
            res.energy,
            res.optical_conductivity,
            x_unit=e_unit,
            y_name="optical conductivity",
            y_unit="S/m",
        ),
        _curve(
            "refractive_index",
            res.energy,
            res.refractive_index,
            x_unit=e_unit,
            y_name="n",
        ),
    ]
    # absent — not null — when non-finite (ADR 0005 §5)
    if nan_none(res.thickness) is not None:
        outputs.append(scalar("thickness_nm", res.thickness, unit="nm"))
    if nan_none(res.t_over_lambda) is not None:
        outputs.append(scalar("t_over_lambda", res.t_over_lambda))
    return OpResult(
        op="eels_kk",
        params=params,
        label="Kramers-Kronig dielectric analysis",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_kk",
        category="eels",
        produces_value=True,
        summary="Kramers-Kronig dielectric analysis of the (spatially summed) "
        "spectrum (calc/eels_advanced.kramers_kronig, Egerton Ch. 4); "
        "the thickness_nm/t_over_lambda scalars are absent when "
        "non-finite",
        params={
            **_zlp_window_params("ZLP window"),
            "refractive_index": OpParam(
                float,
                float("nan"),
                doc="refractive index for ELF normalisation; leave unset "
                "(NaN) for an unnormalised ELF — NaN is the calc's own "
                "default and passes through directly",
            ),
            "collection_angle_mrad": OpParam(float, 10.0, doc="collection semi-angle (mrad)"),
            "acc_voltage_kv": OpParam(float, 200.0, doc="beam voltage (kV)"),
            "thickness_nm": OpParam(
                float,
                float("nan"),
                doc="specimen thickness (nm); leave unset (NaN) to estimate from t/λ",
            ),
        },
        fn=_eels_kk,
    )
)


# ── Fourier-log deconvolution ─────────────────────────────────────────


def _eels_fourier_log(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_spectral(ds, "eels_fourier_log")
    energy = ds.energy_axis
    spec = ds.sum_spectrum()
    # zlp_ref stays the calc's own None default — the route never passes it
    ssd, t_l = fourier_log(
        energy,
        spec,
        (params["zlp_lo"], params["zlp_hi"]),
        regularize=params["regularize"],
    )
    e_unit = ds.energy_cal.units
    outputs = [
        _curve("spectrum", energy, spec, x_unit=e_unit, y_name="counts"),
        _curve("ssd", energy, ssd, x_unit=e_unit, y_name="counts"),
    ]
    if nan_none(t_l) is not None:
        outputs.append(scalar("t_over_lambda", t_l))
    return OpResult(
        op="eels_fourier_log",
        params=params,
        label="Fourier-log single-scattering distribution",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_fourier_log",
        category="eels",
        produces_value=True,
        summary="Fourier-log plural-scattering removal on the (spatially "
        "summed) spectrum (calc/eels_advanced.fourier_log)",
        params={
            **_zlp_window_params("ZLP window"),
            "regularize": OpParam(
                float,
                1e-6,
                minimum=0.0,
                doc="relative regularisation floor for the deconvolution",
            ),
        },
        fn=_eels_fourier_log,
    )
)


# ── SVD/MSA decomposition ─────────────────────────────────────────────


def _eels_svd(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_cube(ds, "eels_svd")
    energy = ds.energy_axis
    # denoise is hard-wired False: the route's denoise=True flips the payload
    # to a derived cube, a mode without an op (ADR 0005 wave-D addendum)
    res = svd(ds.data, energy, params["n_components"], False)
    view = svd_view(res, params["n_score_maps"])
    component = list(range(1, res.explained.size + 1))
    e_unit = ds.energy_cal.units
    outputs = [
        _curve(
            "explained",
            component,
            res.explained,
            x_name="component",
            y_name="explained variance",
            y_unit="%",
        ),
        _curve(
            "cumulative",
            component,
            res.cumulative,
            x_name="component",
            y_name="cumulative explained variance",
            y_unit="%",
        ),
    ]
    for j in range(view.k_show):
        outputs.append(
            _curve(
                f"eigenspectrum_{j + 1}",
                energy,
                view.eigenspectra[j],
                x_unit=e_unit,
                y_name="loading",
            )
        )
        outputs.append(
            output(
                "map",
                f"score_{j + 1}",
                {"values": _map_values(view.score_maps[j]), "quantity": "score"},
            )
        )
    return OpResult(
        op="eels_svd",
        params=params,
        label="SVD/MSA decomposition",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_svd",
        category="eels",
        produces_value=True,
        summary="SVD/MSA decomposition of an SI cube (calc/eels_advanced.svd "
        "+ calc/eels_report.svd_view): scree curves plus the first "
        "n_score_maps eigenspectra and score maps inlined as envelopes. "
        "The route's denoise=True derived-cube mode has no op — the "
        "payload kind would depend on a param (ADR 0005 wave-D "
        "addendum)",
        params={
            "n_components": OpParam(
                int, 0, minimum=0, doc="components to keep; 0 = auto (min(20, rank))"
            ),
            "n_score_maps": OpParam(
                int,
                4,
                minimum=1,
                doc="eigenspectrum/score-map pairs to emit (capped at the component count)",
            ),
        },
        fn=_eels_svd,
    )
)


# ── ZLP alignment (integer + sub-pixel) ───────────────────────────────


def _align_fn(
    opname: str, label: str, subpixel: bool
) -> Callable[[DataStruct, dict[str, Any]], OpResult]:
    """One fn for both alignment ops — same calc call, one flag apart; the
    diagnostics mirror each route's OWN spelling (int max_shift + exact
    nonzero fraction for the integer route, float max_shift + |shift|>0.01
    fraction for the sub-pixel route)."""

    def fn(ds: DataStruct, params: dict[str, Any]) -> OpResult:
        _require_cube(ds, opname)
        aligned, shifts = align_zlp(
            ds.data,
            ds.energy_axis,
            (params["window_lo"], params["window_hi"]),
            params["reference"],
            subpixel=subpixel,
        )
        diag: dict[str, Any]
        if subpixel:
            diag = {
                "max_shift": float(np.abs(shifts).max()),
                "shifted_fraction": float((np.abs(shifts) > 0.01).mean()),
            }
        else:
            diag = {
                "max_shift": int(np.abs(shifts).max()),
                "shifted_fraction": float((shifts != 0).mean()),
            }
        derived = DataStruct(
            data=np.ascontiguousarray(aligned),
            kind=DataKind.SPECTRUM_IMAGE,
            axes=ds.axes,
            metadata={"parser": "derived", "source": opname, **diag},
        )
        return OpResult(op=opname, params=params, label=label, derived=derived)

    return fn


def _align_params() -> dict[str, OpParam]:
    return {
        "window_lo": OpParam(float, -20.0, doc="alignment window lower edge (eV)"),
        "window_hi": OpParam(float, 20.0, doc="alignment window upper edge (eV)"),
        "reference": OpParam(
            str,
            "mean",
            choices=("mean", "max"),
            doc="alignment reference: the mean windowed spectrum, or the brightest pixel's",
        ),
    }


register(
    OpSpec(
        name="eels_align_zlp",
        category="eels",
        summary="Integer-channel ZLP alignment of an SI cube "
        "(calc/eels_advanced.align_zlp): the aligned cube is the derived "
        "result, with max_shift (channels) and shifted_fraction "
        "diagnostics in its metadata (ADR 0005 wave-D addendum)",
        params=_align_params(),
        fn=_align_fn("eels_align_zlp", "ZLP-aligned spectrum image", False),
    )
)


register(
    OpSpec(
        name="eels_subpixel_align",
        category="eels",
        summary="Sub-pixel ZLP alignment of an SI cube "
        "(calc/eels_advanced.align_zlp, subpixel=True — parabolic peak "
        "refine + fractional FFT shift): the aligned cube is the derived "
        "result, with float max_shift and |shift|>0.01 shifted_fraction "
        "diagnostics in its metadata",
        params=_align_params(),
        fn=_align_fn("eels_subpixel_align", "sub-pixel ZLP-aligned spectrum image", True),
    )
)


# ── Richardson-Lucy deconvolution ─────────────────────────────────────


def _eels_richardson_lucy(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    _require_spectral(ds, "eels_richardson_lucy")
    energy = ds.energy_axis
    spectrum = ds.sum_spectrum()
    psf = zlp_psf(energy, spectrum, (params["zlp_lo"], params["zlp_hi"]))
    deconv = richardson_lucy(spectrum, psf, iterations=params["iterations"])
    e_unit = ds.energy_cal.units
    outputs = [
        _curve("spectrum", energy, spectrum, x_unit=e_unit, y_name="counts"),
        _curve("deconvolved", energy, deconv, x_unit=e_unit, y_name="counts"),
        scalar("iterations", params["iterations"]),
    ]
    return OpResult(
        op="eels_richardson_lucy",
        params=params,
        label="Richardson-Lucy deconvolved spectrum",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eels_richardson_lucy",
        category="eels",
        produces_value=True,
        summary="Richardson-Lucy deconvolution of the (spatially summed) "
        "spectrum using its own ZLP as the PSF "
        "(calc/eels_advanced.zlp_psf + richardson_lucy)",
        params={
            **_zlp_window_params("ZLP/PSF window"),
            "iterations": OpParam(int, 15, minimum=1, doc="RL update iterations"),
        },
        fn=_eels_richardson_lucy,
    )
)
