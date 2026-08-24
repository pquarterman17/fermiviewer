"""Spectral/diffraction operation catalogue — EELS/EDS/diffraction verbs for
the batch recipe runner (Scripting #6, remaining half).

Same rule as ``catalogue.py``: every op below calls the SAME pure ``calc/``
function the matching FastAPI route calls — no reimplemented physics, no
parallel copy of a lookup table. Kept in its own module (rather than growing
``catalogue.py``) per the repo's god-module ceiling.

``OpParam`` only carries float/int/str/bool, so a multi-edge EELS quantify or
a multi-element EDS quantify takes its list as a delimited string, parsed
here. Format is documented on each param's ``doc``:

- plain comma lists: ``"Fe,O"``, ``"L,K"``, ``"26,8"``
- windows: comma-separated ``"lo:hi"`` pairs, e.g. ``"708:758,532:582"``

These EELS/EDS ops validate ``ds.kind`` explicitly and raise ``ValueError``
on the wrong kind — never ``raster_of`` (that's for the 2D-raster filter/
geometry/diffraction ops in ``catalogue.py``; EELS/EDS ops need the energy
axis, which a summed raster would discard).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.eds import ClResult, ZafResult, cliff_lorimer, zaf_correction
from fermiviewer.calc.eds_maps import element_map, extract_element_maps
from fermiviewer.calc.eels import extract_map
from fermiviewer.calc.eels_quant import quantify
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.radial import radial_profile
from fermiviewer.calc.smoothing import savgol_derivative, savgol_smooth
from fermiviewer.datastruct import SPECTRAL_KINDS, DataKind, DataStruct
from fermiviewer.ops._parsing import clean_values as _clean
from fermiviewer.ops._parsing import edges_from_params
from fermiviewer.ops._parsing import split_csv as _split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.catalogue import raster_of
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── EELS ───────────────────────────────────────────────────────────────

def _eels_map(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(
            f"eels_map requires a spectrum-image cube (got {ds.kind.value})"
        )
    energy = ds.energy_axis
    bg_window = None
    if np.isfinite(params["bg_lo"]) and np.isfinite(params["bg_hi"]):
        bg_window = (params["bg_lo"], params["bg_hi"])
    m = extract_map(
        ds.data, energy, (params["signal_lo"], params["signal_hi"]),
        bg_window, params["method"],
    )
    derived = DataStruct(
        data=np.ascontiguousarray(m), kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={"parser": "derived", "source": "eels_map"},
    )
    return OpResult(op="eels_map", params=params, label="EELS elemental map",
                    derived=derived)


register(OpSpec(
    name="eels_map", category="eels",
    summary="EELS background-subtracted elemental map",
    params={
        "signal_lo": OpParam(float, required=True, doc="signal window lower edge (eV)"),
        "signal_hi": OpParam(float, required=True, doc="signal window upper edge (eV)"),
        "bg_lo": OpParam(float, float("nan"),
                        doc="pre-edge fit window lower edge (eV); leave unset "
                            "(with bg_hi) for a direct window sum, no background fit"),
        "bg_hi": OpParam(float, float("nan"), doc="pre-edge fit window upper edge (eV)"),
        "method": OpParam(str, "powerlaw", choices=("powerlaw", "exponential"),
                          doc="pre-edge background model"),
    },
    fn=_eels_map,
))


def _eels_quantify(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError("eels_quantify requires spectral input (got a 2D image)")
    edges = edges_from_params(params, "eels_quantify")
    res = quantify(ds.energy_axis, ds.sum_spectrum(), edges,
                   params["e0_kv"], params["beta_mrad"], params["method"])
    value = {
        "elements": res.elements,
        "atomic_percent": res.atomic_percent.tolist(),
        "intensity": res.intensity.tolist(),
        "sigma": res.sigma.tolist(),
    }
    return OpResult(op="eels_quantify", params=params,
                    label="EELS at% quantification", value=value)


register(OpSpec(
    name="eels_quantify", category="eels", produces_value=True,
    summary="EELS at% composition from core-loss edges",
    params={
        "elements": OpParam(str, required=True,
                           doc="comma-separated element symbols, e.g. 'Fe,O'"),
        "shells": OpParam(str, required=True,
                         doc="comma-separated shells matching elements, 'K'|'L', e.g. 'L,K'"),
        "z": OpParam(str, required=True,
                    doc="comma-separated atomic numbers matching elements, e.g. '26,8'"),
        "onset_ev": OpParam(str, required=True,
                            doc="comma-separated edge onsets (eV), e.g. '708,532'"),
        "signal_windows": OpParam(str, required=True,
                                  doc="comma-separated 'lo:hi' signal windows (eV), "
                                      "e.g. '708:758,532:582'"),
        "bg_windows": OpParam(str, required=True,
                              doc="comma-separated 'lo:hi' pre-edge fit windows (eV), "
                                  "e.g. '650:700,490:520'"),
        "e0_kv": OpParam(float, 200.0, minimum=0.0, doc="beam energy (kV)"),
        "beta_mrad": OpParam(float, 10.0, minimum=0.0, doc="collection semi-angle (mrad)"),
        "method": OpParam(str, "powerlaw", choices=("powerlaw", "exponential")),
    },
    fn=_eels_quantify,
))


# ── EDS ──────────────────────────────────────────────────────────────

def _eds_element_map(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(
            f"eds_element_map requires a spectrum-image cube (got {ds.kind.value})"
        )
    energy = to_kev(ds.energy_axis, ds.energy_cal.units)
    m = element_map(
        ds.data, energy, params["e_lo"], params["e_hi"],
        bg=params["bg"], bg_width=params["bg_width"],
        bg_gap=params["bg_gap"], e0_kev=params["e0_kev"],
    )
    derived = DataStruct(
        data=np.ascontiguousarray(m), kind=DataKind.IMAGE,
        axes=(ds.axes[0], ds.axes[1]),
        metadata={"parser": "derived", "source": "eds_element_map"},
    )
    return OpResult(op="eds_element_map", params=params, label="EDS element map",
                    derived=derived)


register(OpSpec(
    name="eds_element_map", category="eds",
    summary="EDS energy-window element map",
    params={
        "e_lo": OpParam(float, required=True, doc="window lower edge (keV)"),
        "e_hi": OpParam(float, required=True, doc="window upper edge (keV)"),
        "bg": OpParam(str, "linear", choices=("none", "linear", "bremsstrahlung"),
                     doc="background model subtracted from the window sum"),
        "bg_width": OpParam(float, float("nan"),
                           doc="background window width (keV); NaN -> same as peak width"),
        "bg_gap": OpParam(float, 0.0, minimum=0.0,
                         doc="gap between peak and background windows (keV)"),
        "e0_kev": OpParam(float, float("nan"),
                         doc="beam energy (keV); required when bg='bremsstrahlung'"),
    },
    fn=_eds_element_map,
))


def _eds_quantify(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(
            f"eds_quantify requires a spectrum-image cube (got {ds.kind.value})"
        )
    elements = _split_csv(params["elements"])
    if not elements:
        raise ValueError("eds_quantify: 'elements' must list at least one symbol")
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(ds.data, energy_kev, elements,
                                   half_window=params["half_window_kev"])
    if not entries:
        raise ValueError("no usable element lines in the energy range")
    maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]
    res: ClResult | ZafResult
    if params["method"] == "zaf":
        res = zaf_correction(maps, syms, thickness_nm=params["thickness_nm"],
                             take_off_angle_deg=params["take_off_angle_deg"])
    else:
        res = cliff_lorimer(maps, syms)
    value = {
        "elements": syms,
        "lines": [e.line for e in entries],
        "mean_atomic_pct": res.mean_atomic_pct.tolist(),
        "mean_weight_pct": res.mean_weight_pct.tolist(),
        "k_factors": res.k_factors.tolist(),
    }
    return OpResult(op="eds_quantify", params=params, label="EDS quantification",
                    value=value)


register(OpSpec(
    name="eds_quantify", category="eds", produces_value=True,
    summary="EDS at%/wt% quantification (Cliff-Lorimer / ZAF)",
    params={
        "elements": OpParam(str, required=True, doc="comma-separated element symbols, e.g. 'Fe,O'"),
        "method": OpParam(str, "cliff-lorimer", choices=("cliff-lorimer", "zaf")),
        "half_window_kev": OpParam(float, 0.085, minimum=0.0, doc="line window half-width (keV)"),
        "thickness_nm": OpParam(float, 100.0, minimum=0.0, doc="specimen thickness (zaf only, nm)"),
        "take_off_angle_deg": OpParam(float, 20.0, minimum=0.1, maximum=89.9,
                                      doc="detector take-off angle (zaf only, deg)"),
    },
    fn=_eds_quantify,
))


# ── Diffraction ────────────────────────────────────────────────────────

def _diffraction_radial_profile(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    raster = raster_of(ds)
    px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else 1.0
    center = None
    if np.isfinite(params["center_x"]) and np.isfinite(params["center_y"]):
        center = (params["center_x"], params["center_y"])
    radii_px, avg, mx = radial_profile(
        raster, center=center, n_bins=params["n_bins"], normalize=params["normalize"],
    )
    value = {
        "radii": (radii_px * px).tolist(),
        "avg_profile": _clean(avg),
        "max_profile": _clean(mx),
        "unit": ds.pixel_unit or "px",
    }
    return OpResult(op="radial_profile", params=params,
                    label="radial intensity profile", value=value)


register(OpSpec(
    name="radial_profile", category="diffraction", produces_value=True,
    summary="Radial average/max intensity profile about a centre",
    params={
        "n_bins": OpParam(int, 0, minimum=0, doc="bin count; 0 -> floor(min(H,W)/2)"),
        "center_x": OpParam(float, float("nan"),
                           doc="centre column, 1-based (x); NaN -> image centre"),
        "center_y": OpParam(float, float("nan"),
                           doc="centre row, 1-based (y); NaN -> image centre"),
        "normalize": OpParam(bool, False, doc="rescale both profiles to [0, 1]"),
    },
    fn=_diffraction_radial_profile,
))


# ── Smoothing (Savitzky-Golay, ANALYSIS_PRESENTATION_PLAN.md #5) ──────
#
# calc/smoothing.py's savgol_smooth/savgol_derivative are deliberately
# 1-D only, so a SPECTRUM_IMAGE cube is reduced to its spatially-summed
# trace first via ds.sum_spectrum() — the same reduction eels_quantify
# uses to accept both SPECTRUM and SPECTRUM_IMAGE input above. The
# derived result is a SPECTRUM DataStruct on the input's own energy
# axis, not a per-pixel cube.
#
# delta (the derivative's sample spacing) is an op-layer policy, not a
# calc/ decision: taken from the energy axis's calibration
# (AxisCal.scale, e.g. eV/channel or keV/channel) when the axis is
# calibrated, else 1.0 per channel — so an uncalibrated spectrum still
# gets a well-defined (per-channel) derivative instead of an error.
#
# Units note: savgol_derivative's output is d(counts)/d(energy unit), a
# different physical quantity from the input's raw counts. DataStruct
# has no separate "value units" field for any op in this catalogue
# (eels_map's background-subtracted counts and eds_element_map's summed
# counts are equally unlabeled) — so leaving the derivative's y-values
# unlabeled beyond the op's own summary/label matches existing
# convention rather than inventing a new metadata scheme here.

def _savgol_delta(ds: DataStruct) -> float:
    cal = ds.energy_cal
    return cal.scale if cal.calibrated else 1.0


def _savgol(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"savgol requires spectral input (got {ds.kind.value})")
    smoothed = savgol_smooth(
        ds.sum_spectrum(), window=params["window"], polyorder=params["polyorder"]
    )
    derived = DataStruct(
        data=smoothed, kind=DataKind.SPECTRUM, axes=(ds.energy_cal,),
        metadata={"parser": "derived", "source": "savgol"},
    )
    return OpResult(op="savgol", params=params,
                    label="Savitzky-Golay smoothed spectrum", derived=derived)


register(OpSpec(
    name="savgol", category="spectral",
    summary="Savitzky-Golay smoothing of a spectrum (a SPECTRUM_IMAGE cube "
            "is spatially summed first, like eels_quantify)",
    params={
        "window": OpParam(int, 11, minimum=1,
                          doc="filter window length (odd, samples); must be <= trace length"),
        "polyorder": OpParam(int, 3, minimum=0,
                             doc="fitted polynomial degree; must be < window"),
    },
    fn=_savgol,
))


def _savgol_derivative(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(
            f"savgol_derivative requires spectral input (got {ds.kind.value})"
        )
    delta = _savgol_delta(ds)
    deriv = savgol_derivative(
        ds.sum_spectrum(), window=params["window"], polyorder=params["polyorder"],
        order=params["order"], delta=delta,
    )
    derived = DataStruct(
        data=deriv, kind=DataKind.SPECTRUM, axes=(ds.energy_cal,),
        metadata={"parser": "derived", "source": "savgol_derivative", "delta": delta},
    )
    return OpResult(
        op="savgol_derivative", params=params,
        label=f"Savitzky-Golay order-{params['order']} derivative spectrum",
        derived=derived,
    )


register(OpSpec(
    name="savgol_derivative", category="spectral",
    summary="Savitzky-Golay derivative of a spectrum; delta is the energy "
            "axis's calibrated scale when calibrated, else 1.0/channel. "
            "Output y-units are d(counts)/d(energy unit), unlike the input's "
            "raw counts -- see the module docstring's units note",
    params={
        "window": OpParam(int, 11, minimum=1,
                          doc="filter window length (odd, samples); must be <= trace length"),
        "polyorder": OpParam(int, 3, minimum=0,
                             doc="fitted polynomial degree; must be < window"),
        "order": OpParam(int, 1, minimum=1,
                         doc="derivative order; must satisfy 1 <= order <= polyorder"),
    },
    fn=_savgol_derivative,
))
