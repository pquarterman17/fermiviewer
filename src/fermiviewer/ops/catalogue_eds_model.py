"""Model-based EDS operation catalogue — wave D (roadmap 3E): batch/
scripting reach for the continuum fit, artifact detection, and ζ-factor
quantification behind ``routes/eds_advanced.py`` / ``routes/eds_zeta.py``.
New module because no existing catalogue has the headroom (the
``catalogue_analysis.py`` precedent); the energy-recalibration and
auto-assign ops live in ``catalogue_eds_calib.py``.

The `eds` category does NOT imply a value result, so every op here sets
``produces_value=True`` explicitly (ADR 0005 §3). Every op calls the SAME
calc composition its route calls — the wave-D lifts
(``calc/eds_continuum.background_component``,
``calc/eds_peakfit.fit_summed_peaks``, ``calc/eds_artifacts
.artifact_prepass``/``artifact_block``, ``calc/eds_zeta
.zeta_uncertainty``) exist so op and route run one code path. The ops
call ``fit_summed_peaks`` WITHOUT its keyword-only ``fit`` override —
that parameter is the route layer's late-binding patch seam
(``routes/_eds_common.py``), not op vocabulary.

Param spellings follow the shipped conventions: comma lists for element
symbols and per-element ζ factors, ``"lo:hi"`` windows, NaN sentinels for
optional floats (``e0_kev``, ``zeta_si``, ``density_g_cm3``), and
``eds_peakfit``'s ``weights`` choices where ``"uniform"`` maps to the
calc layer's ``None``. One deliberate tightening over ``/eds/zeta``:
giving BOTH ``zeta_factors`` and ``zeta_si`` is an error here (the route
silently prefers ``zeta_factors``) — a batch recipe carrying two
conflicting calibrations should fail loudly, never quietly half-apply.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from fermiviewer.calc.eds_artifacts import (
    DEFAULT_ESCAPE_FRACTION,
    ArtifactRemoval,
    artifact_block,
    artifact_prepass,
)
from fermiviewer.calc.eds_continuum import background_component, fit_continuum
from fermiviewer.calc.eds_peakfit import fit_peaks, fit_summed_peaks
from fermiviewer.calc.eds_zeta import (
    dose_electrons,
    zeta_from_k_factors,
    zeta_quantify,
    zeta_uncertainty,
)
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.fit_quality import r_squared
from fermiviewer.datastruct import SPECTRAL_KINDS, DataStruct
from fermiviewer.ops._envelopes import nan_none, output, scalar
from fermiviewer.ops._parsing import parse_windows, split_csv
from fermiviewer.ops.base import OpParam, OpResult, OpSpec
from fermiviewer.ops.registry import register

__all__: list[str] = []


# ── shared spellings (mirror the routes' request models) ──────────────

#: the shared background vocabulary (calc.eds_continuum.background_component)
_BACKGROUND_PARAM = OpParam(
    str,
    "linear",
    choices=("none", "linear", "bremsstrahlung"),
    doc="background fit jointly with the peaks; 'bremsstrahlung' needs e0_kev",
)
#: 'uniform' maps to the calc layer's None (the eds_peakfit spelling)
_WEIGHTS_PARAM = OpParam(str, "poisson", choices=("poisson", "uniform"), doc="fit weighting scheme")
_E0_PARAM = OpParam(
    float,
    float("nan"),
    doc="beam energy (keV, the Duane-Hunt cutoff); required when "
    "background='bremsstrahlung', otherwise unused — leave unset (NaN)",
)
_ESCAPE_PARAM = OpParam(
    float,
    DEFAULT_ESCAPE_FRACTION,
    minimum=0.0,
    doc="Si escape probability for modeled (blocked) escape peaks",
)


def _spectral_energy_kev(ds: DataStruct, opname: str) -> np.ndarray:
    """The routes' spectral guard + keV axis conversion, mirrored."""
    if ds.kind not in SPECTRAL_KINDS:
        raise ValueError(f"{opname} requires spectral input (got {ds.kind.value})")
    return to_kev(ds.energy_axis, ds.energy_cal.units)


def _weights(params: dict[str, Any]) -> str | None:
    return None if params["weights"] == "uniform" else str(params["weights"])


def _e0_or_none(params: dict[str, Any]) -> float | None:
    e0 = params["e0_kev"]
    return float(e0) if math.isfinite(e0) else None


def _elements(params: dict[str, Any], opname: str) -> list[str]:
    elements = split_csv(params["elements"])
    if not elements:
        raise ValueError(f"{opname}: 'elements' must list at least one symbol")
    return elements


def _spectrum_curve(energy: np.ndarray, spectrum: np.ndarray) -> dict[str, Any]:
    return output(
        "curve",
        "spectrum",
        {
            "x_name": "energy",
            "x_unit": "keV",
            "y_name": "counts",
            "y_unit": "",
            "x": energy.tolist(),
            "y": spectrum.tolist(),
        },
    )


_ARTIFACT_COLUMNS = ("name", "label", "kind", "energy_kev", "status", "area", "area_error")


def _artifact_table(removal: ArtifactRemoval) -> dict[str, Any]:
    """`calc.eds_artifacts.artifact_block`'s marker dicts as a table envelope
    (area/area_error are None for modeled/skipped rows, like the route)."""
    rows = [[marker[c] for c in _ARTIFACT_COLUMNS] for marker in artifact_block(removal)]
    return output(
        "table",
        "artifacts",
        {
            "columns": list(_ARTIFACT_COLUMNS),
            "units": ["", "", "", "keV", "", "counts", "counts"],
            "rows": rows,
        },
    )


# ── eds_continuum: Kramers bremsstrahlung background fit ───────────────


def _eds_continuum(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    energy = _spectral_energy_kev(ds, "eds_continuum")
    spectrum = ds.sum_spectrum()
    fit = fit_continuum(
        energy,
        spectrum,
        params["e0_kev"],
        exclude_lines=list(split_csv(params["exclude_lines"])),
        exclude_windows=parse_windows(params["exclude_windows"]),
        fit_absorption=params["fit_absorption"],
        weights=_weights(params),
    )
    outputs = [
        output(
            "fit",
            "continuum",
            {
                "model": "kramers",
                "x_name": "energy",
                "x_unit": "keV",
                "y_name": "counts",
                "y_unit": "",
                "coefficients": {"amp": fit.amp, "absorption": fit.absorption},
                "reduced_chi2": fit.fit.reduced_chi2,
                "success": fit.fit.success,
                "x_fit": energy.tolist(),
                "y_fit": fit.continuum.tolist(),
            },
        ),
        _spectrum_curve(energy, spectrum),
    ]
    return OpResult(
        op="eds_continuum",
        params=params,
        label="EDS bremsstrahlung continuum fit",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eds_continuum",
        category="eds",
        produces_value=True,
        summary="Kramers bremsstrahlung continuum fit through masked "
        "characteristic peaks (calc/eds_continuum.fit_continuum)",
        params={
            "e0_kev": OpParam(
                float,
                required=True,
                doc="beam energy (keV, the Duane-Hunt cutoff); fixed, not fitted",
            ),
            "exclude_lines": OpParam(
                str,
                "",
                doc="comma-separated element symbols whose K/L/M peaks are "
                "masked before fitting, e.g. 'Fe,Cu'; empty = none",
            ),
            "exclude_windows": OpParam(
                str,
                "",
                doc="comma-separated 'lo:hi' keV regions also masked, "
                "e.g. '6.2:6.6,8.0:8.2'; empty = none",
            ),
            "fit_absorption": OpParam(
                bool, True, doc="free the low-energy detector-absorption rolloff"
            ),
            "weights": _WEIGHTS_PARAM,
        },
        fn=_eds_continuum,
    )
)


# ── eds_artifacts: escape/sum peak detection + measurement ─────────────


def _eds_artifacts(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    energy = _spectral_energy_kev(ds, "eds_artifacts")
    spectrum = ds.sum_spectrum()
    elements = _elements(params, "eds_artifacts")
    pf = fit_peaks(
        energy,
        spectrum,
        elements,
        beam_kv=params["beam_kv"],
        background=background_component(params["background"], _e0_or_none(params)),
        weights=_weights(params),
    )
    removal = artifact_prepass(energy, spectrum, pf, params["escape_fraction"])
    outputs = [
        _spectrum_curve(energy, spectrum),
        output(
            "curve",
            "corrected",
            {
                "x_name": "energy",
                "x_unit": "keV",
                "y_name": "counts",
                "y_unit": "",
                "x": energy.tolist(),
                "y": removal.corrected.tolist(),
            },
        ),
        _artifact_table(removal),
    ]
    return OpResult(
        op="eds_artifacts",
        params=params,
        label="EDS escape/sum peak detection",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eds_artifacts",
        category="eds",
        produces_value=True,
        summary="Detect + measure escape/sum/pile-up peaks and subtract them "
        "(calc/eds_peakfit.fit_peaks -> calc/eds_artifacts"
        ".artifact_prepass); headless reach is this endpoint's only reach",
        params={
            "elements": OpParam(
                str, required=True, doc="comma-separated element symbols, e.g. 'Fe,Cu'"
            ),
            "beam_kv": OpParam(
                float, 200.0, minimum=0.0, doc="beam energy (kV), selects K/L/M line"
            ),
            "background": _BACKGROUND_PARAM,
            "e0_kev": _E0_PARAM,
            "weights": _WEIGHTS_PARAM,
            "escape_fraction": _ESCAPE_PARAM,
        },
        fn=_eds_artifacts,
    )
)


# ── eds_zeta: ζ-factor (Watanabe) quantification ───────────────────────


def _zeta_vector(params: dict[str, Any], elements: list[str]) -> np.ndarray:
    """Resolve ζ from exactly one of zeta_factors / zeta_si (see the module
    docstring on the deliberate both-given tightening over the route)."""
    factors = split_csv(params["zeta_factors"])
    zeta_si = params["zeta_si"]
    if factors and math.isfinite(zeta_si):
        raise ValueError("eds_zeta: give exactly one of zeta_factors or zeta_si (got both)")
    if factors:
        if len(factors) != len(elements):
            raise ValueError("zeta_factors must match elements length")
        return np.asarray([float(v) for v in factors], dtype=np.float64)
    if math.isfinite(zeta_si):
        return zeta_from_k_factors(elements, float(zeta_si))
    raise ValueError("provide zeta_factors or zeta_si")


def _eds_zeta(ds: DataStruct, params: dict[str, Any]) -> OpResult:
    energy = _spectral_energy_kev(ds, "eds_zeta")
    spectrum = ds.sum_spectrum()
    elements = _elements(params, "eds_zeta")
    zeta = _zeta_vector(params, elements)

    pf, removal = fit_summed_peaks(
        energy,
        spectrum,
        elements,
        beam_kv=params["beam_kv"],
        background=background_component(params["background"], _e0_or_none(params)),
        weights=_weights(params),
        center_tol_kev=params["center_tol_kev"],
        strip_artifacts=params["remove_artifacts"],
        escape_fraction=params["escape_fraction"],
    )

    dose = dose_electrons(params["probe_current_na"], params["live_time_s"])
    net = np.array([max(pf.net_areas[s], 0.0) for s in elements])
    if not np.all(np.isfinite(net)):
        raise ValueError("an element has no fittable line")
    density = params["density_g_cm3"]
    zr = zeta_quantify(
        [np.array([[v]]) for v in net],
        list(elements),
        zeta,
        dose,
        take_off_angle_deg=params["take_off_angle_deg"],
        absorption=params["absorption"],
        density_g_cm3=float(density) if math.isfinite(density) else None,
    )
    unc, rho_t_sigma = zeta_uncertainty(
        net,
        [pf.net_area_errors[s] for s in elements],
        elements,
        zeta,
        zr.absorption_factors,
        dose,
    )

    fit_data: dict[str, Any] = {
        "model": "constrained multi-gaussian peaks + background",
        "x_name": "energy",
        "x_unit": "keV",
        "y_name": "counts",
        "y_unit": "",
        "x_fit": energy.tolist(),
        "y_fit": pf.fit.model.tolist(),
        "reduced_chi2": pf.fit.reduced_chi2,
        "r_squared": r_squared(spectrum, pf.fit.model),
        "success": pf.fit.success,
    }
    # model-confidence band: present ONLY when the covariance was usable
    # (absent — not null — mirroring the route's null via §5 omission)
    if pf.model_sigma is not None:
        fit_data["y_sigma"] = pf.model_sigma.tolist()

    outputs = [
        output("fit", "model", fit_data),
        _spectrum_curve(energy, spectrum),
        output(
            "table",
            "elements",
            {
                "columns": ["symbol", "line", "energy_kev", "net_area", "net_area_error"],
                "units": ["", "", "keV", "counts", "counts"],
                "rows": [
                    [
                        s,
                        pf.lines[s],
                        pf.line_energies[s],
                        pf.net_areas[s],
                        pf.net_area_errors[s],
                    ]
                    for s in elements
                ],
            },
        ),
        output(
            "table",
            "quant",
            {
                "columns": [
                    "symbol",
                    "atomic_percent",
                    "atomic_percent_error",
                    "weight_percent",
                    "weight_percent_error",
                    "zeta_factor",
                    "absorption_factor",
                ],
                "units": ["", "%", "%", "%", "%", "kg/m^2", ""],
                "rows": [
                    [
                        elements[i],
                        nan_none(float(zr.mean_atomic_pct[i])),
                        nan_none(float(unc.atomic_pct_sigma[i])),
                        nan_none(float(zr.mean_weight_pct[i])),
                        nan_none(float(unc.weight_pct_sigma[i])),
                        float(zeta[i]),
                        float(zr.absorption_factors[i]),
                    ]
                    for i in range(len(elements))
                ],
            },
        ),
    ]
    # non-finite scalars are absent — not null (§5)
    if math.isfinite(zr.mean_mass_thickness):
        # a genuine §5 sigma-in-envelope: the counting-statistics 1σ on ρt
        outputs.append(
            scalar(
                "mass_thickness_kg_m2",
                zr.mean_mass_thickness,
                unit="kg/m^2",
                sigma=rho_t_sigma if math.isfinite(rho_t_sigma) else None,
            )
        )
    if math.isfinite(zr.mean_thickness_nm):
        outputs.append(scalar("thickness_nm", zr.mean_thickness_nm, unit="nm"))
    outputs.append(scalar("dose_electrons", dose, unit="e-"))
    if removal is not None:
        outputs.append(_artifact_table(removal))
    return OpResult(
        op="eds_zeta",
        params=params,
        label="EDS zeta-factor quantification",
        value={"outputs": outputs},
    )


register(
    OpSpec(
        name="eds_zeta",
        category="eds",
        produces_value=True,
        summary="Zeta-factor (Watanabe) quantification of the summed spectrum: "
        "composition + mass-thickness (calc/eds_peakfit.fit_summed_peaks "
        "-> calc/eds_zeta.zeta_quantify + zeta_uncertainty); give exactly "
        "one of zeta_factors / zeta_si",
        params={
            "elements": OpParam(
                str, required=True, doc="comma-separated element symbols, e.g. 'Fe,Cu'"
            ),
            "beam_kv": OpParam(
                float, 200.0, minimum=0.0, doc="beam energy (kV), selects K/L/M line"
            ),
            "background": _BACKGROUND_PARAM,
            "e0_kev": _E0_PARAM,
            "center_tol_kev": OpParam(
                float,
                0.0,
                minimum=0.0,
                doc="allow each peak center to wander +/- this (keV); "
                "0 = fixed at the known line energy",
            ),
            "weights": _WEIGHTS_PARAM,
            "zeta_factors": OpParam(
                str,
                "",
                doc="comma-separated per-element zeta factors (kg/m^2) matching "
                "elements, e.g. '500,800'; empty = unset (use zeta_si)",
            ),
            "zeta_si": OpParam(
                float,
                float("nan"),
                doc="absolute zeta for Si scaling the built-in 200 kV k-factor "
                "table (kg/m^2); leave unset (NaN) when giving zeta_factors",
            ),
            "probe_current_na": OpParam(float, 1.0, doc="probe current (nA)"),
            "live_time_s": OpParam(float, 100.0, doc="acquisition live time (s)"),
            "take_off_angle_deg": OpParam(
                float, 20.0, doc="X-ray take-off angle (deg, in (0, 90))"
            ),
            "absorption": OpParam(
                bool, True, doc="iterate the self-consistent thin-film absorption correction"
            ),
            "density_g_cm3": OpParam(
                float,
                float("nan"),
                doc="density for the rho*t -> thickness (nm) conversion; "
                "leave unset (NaN) to skip the thickness scalar",
            ),
            "remove_artifacts": OpParam(
                bool, False, doc="escape/sum pre-pass, then refit on the corrected spectrum"
            ),
            "escape_fraction": _ESCAPE_PARAM,
        },
        fn=_eds_zeta,
    )
)
