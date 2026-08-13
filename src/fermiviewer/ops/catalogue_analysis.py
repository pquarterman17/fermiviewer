"""Analysis-fit operation catalogue — batch/scripting reach for model-based
spectral fitting and population statistics (ANALYSIS_PRESENTATION_PLAN.md
#8, audit R7).

The op catalogue is what batch recipes, macros, and ``fermiviewer.api``
scripts can reach; before this module, none of the fit routes had an op
counterpart, so a script could load a cube but never fit it. Same rule as
``catalogue.py``/``catalogue_spectral.py``: every op below calls the SAME
pure ``calc/`` function its matching FastAPI route calls — wiring + schema
only, no reimplemented physics. Kept in its own module (rather than growing
``catalogue_spectral.py``, already at the repo's god-module ceiling
neighbourhood) per the same rule.

List-shaped params use ``catalogue_spectral``'s established string
conventions (see ``ops/_parsing.py``): comma lists (``"Fe,O"``) and
``"lo:hi"`` windows.

``distribution_fit`` is the one op here whose subject isn't the input
``DataStruct`` at all — a size distribution is a property of a list of
already-measured numbers (particle/grain diameters, ...), not of any
particular image (see ``routes/distributions.py``'s own docstring). The
input image is still required by the op/scripting contract (``img.<op>(...)``
always runs against SOME loaded image) but its data is unused; the values
travel as a comma-separated param like every other list-shaped op input.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.distributions import (
    fit_all,
    fit_distribution,
    histogram_bins,
    summarize,
)
from fermiviewer.calc.eds import ClResult, ZafResult, cliff_lorimer, zaf_correction
from fermiviewer.calc.eds_maps import (
    composition_profile,
    composition_profile_sigma,
    element_map,
    extract_element_maps,
)
from fermiviewer.calc.eds_peakfit import quantify_peaks
from fermiviewer.calc.eels_model import fit_edges
from fermiviewer.calc.eels_quant import ElementEdge
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.uncertainty import atomic_fraction_sigma, default_k_factors
from fermiviewer.datastruct import SPECTRAL_KINDS, DataKind, DataStruct
from fermiviewer.ops._parsing import parse_windows, split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── EELS: model-based multi-edge fit ───────────────────────────────────

def _eels_fit(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"eels_fit requires spectral input (got {ds.kind.value})")
    elements = split_csv(params["elements"])
    shells = split_csv(params["shells"])
    z_list = [int(v) for v in split_csv(params["z"])]
    onsets = [float(v) for v in split_csv(params["onset_ev"])]
    sig_windows = parse_windows(params["signal_windows"])
    bg_windows = parse_windows(params["bg_windows"])
    lengths = {len(elements), len(shells), len(z_list), len(onsets),
              len(sig_windows), len(bg_windows)}
    if len(lengths) != 1 or not elements:
        raise ValueError(
            "eels_fit: elements/shells/z/onset_ev/signal_windows/bg_windows "
            f"must all list the same non-zero number of edges (got lengths {sorted(lengths)})"
        )
    edges = [
        ElementEdge(elements[i], shells[i], z_list[i], onsets[i],
                   sig_windows[i], bg_windows[i])
        for i in range(len(elements))
    ]
    fit_range = None
    if np.isfinite(params["fit_range_lo"]) and np.isfinite(params["fit_range_hi"]):
        fit_range = (params["fit_range_lo"], params["fit_range_hi"])

    res = fit_edges(
        ds.energy_axis, ds.sum_spectrum(), edges,
        params["e0_kv"], params["beta_mrad"], fit_range=fit_range,
    )
    at_err = atomic_fraction_sigma(res.amplitudes, res.amplitude_errors)
    value = {
        "elements": res.elements,
        "atomic_percent": res.atomic_percent.tolist(),
        "atomic_percent_error": at_err.tolist(),
        "amplitudes": res.amplitudes.tolist(),
        "amplitude_errors": res.amplitude_errors.tolist(),
        "background": res.background.tolist(),
        "edge_curves": res.edge_curves.tolist(),
        "model": res.model.tolist(),
        "reduced_chi2": res.reduced_chi2,
        "r_squared": res.r_squared,
        "success": res.success,
        "fit_range": list(res.fit_range),
    }
    return OpResult(op="eels_fit", params=params,
                    label="EELS simultaneous multi-edge fit", value=value)


register(OpSpec(
    name="eels_fit", category="eels", produces_value=True,
    summary="Simultaneous background + multi-edge model fit (calc/eels_model.fit_edges)",
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
                                      "e.g. '708:758,532:582' (unused by the fit itself, "
                                      "kept for parity with eels_quantify's edge schema)"),
        "bg_windows": OpParam(str, required=True,
                              doc="comma-separated 'lo:hi' pre-edge windows (eV); the "
                                  "first edge's lower bound seeds the default fit range"),
        "e0_kv": OpParam(float, 200.0, minimum=0.0, doc="beam energy (kV)"),
        "beta_mrad": OpParam(float, 10.0, minimum=0.0, doc="collection semi-angle (mrad)"),
        "fit_range_lo": OpParam(float, float("nan"),
                                doc="fit window lower edge (eV); leave unset (with "
                                    "fit_range_hi) to use the resolved default"),
        "fit_range_hi": OpParam(float, float("nan"), doc="fit window upper edge (eV)"),
    },
    fn=_eels_fit,
))


# ── EDS: peak-deconvolution quantify ────────────────────────────────────

def _eds_peakfit(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"eds_peakfit requires spectral input (got {ds.kind.value})")
    elements = split_csv(params["elements"])
    if not elements:
        raise ValueError("eds_peakfit: 'elements' must list at least one symbol")
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    weights = None if params["weights"] == "uniform" else params["weights"]
    pf, cl = quantify_peaks(
        energy_kev, ds.sum_spectrum(), elements,
        beam_kv=params["beam_kv"], weights=weights,
        center_tol_kev=params["center_tol_kev"],
        lorentzian_hwhm_kev=params["lorentzian_hwhm_kev"],
    )
    value = {
        "elements": elements,
        "net_areas": [pf.net_areas[s] for s in elements],
        "net_area_errors": [pf.net_area_errors[s] for s in elements],
        "line_energies": [pf.line_energies[s] for s in elements],
        "lines": [pf.lines[s] for s in elements],
        "reduced_chi2": pf.fit.reduced_chi2,
        "success": pf.fit.success,
        "mean_atomic_pct": cl.mean_atomic_pct.tolist(),
        "mean_weight_pct": cl.mean_weight_pct.tolist(),
        "k_factors": cl.k_factors.tolist(),
    }
    return OpResult(op="eds_peakfit", params=params,
                    label="EDS peak-deconvolution quantify", value=value)


register(OpSpec(
    name="eds_peakfit", category="eds", produces_value=True,
    summary="Constrained multi-Gaussian/Voigt peak deconvolution + "
            "Cliff-Lorimer quantify (calc/eds_peakfit.quantify_peaks)",
    params={
        "elements": OpParam(str, required=True,
                           doc="comma-separated element symbols, e.g. 'Fe,Si'"),
        "beam_kv": OpParam(float, 200.0, minimum=0.0, doc="beam energy (kV), selects K/L/M line"),
        "center_tol_kev": OpParam(float, 0.0, minimum=0.0,
                                  doc="allow each peak center to wander +/- this (keV); "
                                      "0 = fixed at the known line energy"),
        "lorentzian_hwhm_kev": OpParam(float, 0.0, minimum=0.0,
                                       doc="0 = pure Gaussian peaks; >0 switches to a "
                                           "fixed-width Voigt profile"),
        "weights": OpParam(str, "poisson", choices=("poisson", "uniform"),
                          doc="fit weighting scheme"),
    },
    fn=_eds_peakfit,
))


# ── EDS: batch per-element net maps ──────────────────────────────────────

def _eds_element_maps(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(
            f"eds_element_maps requires a spectrum-image cube (got {ds.kind.value})"
        )
    elements = split_csv(params["elements"])
    if not elements:
        raise ValueError("eds_element_maps: 'elements' must list at least one symbol")
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(
        ds.data, energy_kev, elements,
        half_window=params["half_window_kev"], bg=params["bg"],
    )
    if not entries:
        raise ValueError("no usable element lines in the energy range")
    value = {
        "elements": [e.symbol for e in entries],
        "lines": [e.line for e in entries],
        "energies_kev": [e.energy_kev for e in entries],
        "windows_kev": [list(e.window) for e in entries],
        "totals": [e.total for e in entries],
        "maps": [e.map.tolist() for e in entries],
        "shape": list(entries[0].map.shape),
    }
    return OpResult(op="eds_element_maps", params=params,
                    label="EDS per-element net maps (batch)", value=value)


register(OpSpec(
    name="eds_element_maps", category="eds", produces_value=True,
    summary="Batch per-element net intensity maps at each element's principal "
            "line (calc/eds_maps.extract_element_maps) — one call, every "
            "requested element's map, unlike eds_element_map's single window",
    params={
        "elements": OpParam(str, required=True,
                           doc="comma-separated element symbols, e.g. 'Fe,Si,O'"),
        "half_window_kev": OpParam(float, 0.085, minimum=0.0, doc="line window half-width (keV)"),
        "bg": OpParam(str, "linear", choices=("none", "linear"),
                     doc="background model subtracted from each window sum"),
    },
    fn=_eds_element_maps,
))


# ── EDS: composition profile along a line (compound: quantify + sample) ──

def _composition_profile_op(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    if ds.kind is not DataKind.SPECTRUM_IMAGE:
        raise ValueError(
            f"composition_profile requires a spectrum-image cube (got {ds.kind.value})"
        )
    elements = split_csv(params["elements"])
    if not elements:
        raise ValueError("composition_profile: 'elements' must list at least one symbol")
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(ds.data, energy_kev, elements,
                                   half_window=params["half_window_kev"])
    if not entries:
        raise ValueError("no usable element lines in the energy range")
    net_maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]

    res: ClResult | ZafResult
    if params["method"] == "zaf":
        res = zaf_correction(net_maps, syms, thickness_nm=params["thickness_nm"],
                             take_off_angle_deg=params["take_off_angle_deg"])
    else:
        res = cliff_lorimer(net_maps, syms)

    px = ds.pixel_size if np.isfinite(ds.pixel_size) and ds.pixel_size > 0 else 1.0
    dist, pct = composition_profile(
        res.atomic_pct_maps, syms,
        params["x1"], params["y1"], params["x2"], params["y2"],
        n_points=params["n_points"], pixel_size=px, width=params["width"],
    )
    value: dict[str, Any] = {
        "distance": dist.tolist(),
        "atomic_pct": pct.T.tolist(),  # [n_elements, n_points]
        "elements": syms,
        "unit": ds.pixel_unit or "px",
    }
    if params["method"] == "cliff-lorimer":
        gross_maps = [
            element_map(ds.data, energy_kev, e.window[0], e.window[1], bg="none")
            for e in entries
        ]
        sigma = composition_profile_sigma(
            net_maps, gross_maps, syms, default_k_factors(syms),
            params["x1"], params["y1"], params["x2"], params["y2"],
            n_points=params["n_points"], width=params["width"],
        )
        value["atomic_percent_error"] = sigma.T.tolist()
    return OpResult(op="composition_profile", params=params,
                    label="EDS composition profile", value=value)


register(OpSpec(
    name="composition_profile", category="eds", produces_value=True,
    summary="Width-averaged element at% line profile through an EDS SI cube: "
            "quantifies (Cliff-Lorimer/ZAF) then samples "
            "calc/eds_maps.composition_profile along one line in a single call "
            "(the HTTP route samples pre-registered map images instead)",
    params={
        "elements": OpParam(str, required=True, doc="comma-separated element symbols, e.g. 'Fe,O'"),
        "x1": OpParam(float, required=True, doc="line start column, 1-based (x)"),
        "y1": OpParam(float, required=True, doc="line start row, 1-based (y)"),
        "x2": OpParam(float, required=True, doc="line end column, 1-based (x)"),
        "y2": OpParam(float, required=True, doc="line end row, 1-based (y)"),
        "n_points": OpParam(int, 200, minimum=2, doc="samples along the line"),
        "width": OpParam(float, 1.0, minimum=1.0, doc="perpendicular averaging width (px)"),
        "half_window_kev": OpParam(float, 0.085, minimum=0.0, doc="line window half-width (keV)"),
        "method": OpParam(str, "cliff-lorimer", choices=("cliff-lorimer", "zaf")),
        "thickness_nm": OpParam(float, 100.0, minimum=0.0, doc="specimen thickness (zaf only, nm)"),
        "take_off_angle_deg": OpParam(float, 20.0, minimum=0.1, maximum=89.9,
                                      doc="detector take-off angle (zaf only, deg)"),
    },
    fn=_composition_profile_op,
))


# ── Population statistics + distribution fitting ────────────────────────

def _dist_payload(f: Any) -> dict[str, Any]:
    """A ``calc.distributions.DistFit`` as a JSON-shaped dict (mirrors
    ``routes/distributions.py``'s ``_fit_payload``, kept as its own copy
    here since ``ops/`` may not import a ``routes/*`` module)."""
    return {
        "kind": f.kind, "params": f.params,
        "log_likelihood": f.log_likelihood, "aic": f.aic,
        "ks_statistic": f.ks_statistic, "ks_pvalue": f.ks_pvalue,
    }


def _distribution_fit(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    # ds is unused: a size distribution is a property of the VALUES, not of
    # any particular image — see the module docstring.
    del ds
    values = np.array([float(v) for v in split_csv(params["values"])], dtype=np.float64)
    if values.size == 0:
        raise ValueError("distribution_fit: 'values' must list at least one number")
    summary = summarize(values)
    histogram = histogram_bins(values)
    fit_choice = params["fit"]
    fits: dict[str, Any] | None
    if fit_choice == "all":
        allf = fit_all(values)
        fits = {
            "normal": _dist_payload(allf.normal),
            "lognormal": _dist_payload(allf.lognormal),
            "weibull": _dist_payload(allf.weibull),
            "best": allf.best,
        }
    elif fit_choice == "none":
        fits = None
    else:
        fits = {"normal": None, "lognormal": None, "weibull": None, "best": None}
        fits[fit_choice] = _dist_payload(fit_distribution(values, fit_choice))

    value = {
        "summary": {
            "n": summary.n, "n_dropped": summary.n_dropped, "mean": summary.mean,
            "std": summary.std, "min": summary.minimum, "max": summary.maximum,
            "median": summary.median, "q1": summary.q1, "q3": summary.q3,
        },
        "histogram": {"edges": histogram.edges.tolist(), "counts": histogram.counts.tolist()},
        "fits": fits,
    }
    return OpResult(op="distribution_fit", params=params,
                    label="population summary + distribution fit", value=value)


register(OpSpec(
    name="distribution_fit", category="analysis",
    summary="Population summary + histogram + normal/lognormal/weibull fit "
            "over a raw value list (calc/distributions.py) — for particle/"
            "grain size populations extracted elsewhere in a script",
    params={
        "values": OpParam(str, required=True,
                          doc="comma-separated numeric values, e.g. particle "
                              "equivalent diameters '12.3,45.6,78.9'"),
        "fit": OpParam(str, "all", choices=("all", "normal", "lognormal", "weibull", "none"),
                      doc="'all' fits + AIC-picks the best; a single kind fits only that "
                          "one; 'none' returns summary + histogram only"),
    },
    fn=_distribution_fit,
))
