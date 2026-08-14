"""Route-layer helpers shared by the model-based EDS route modules.

`routes/eds_advanced.py` carries the continuum/peakfit/artifacts/
recalibrate surface; `routes/eds_zeta.py` carries ζ-factor
quantification. Both fit the same summed-spectrum peak model with the
same background choices and the same escape/sum-peak pre-pass, and
neither can import the other without a cycle — so that shared machinery
lives here, following `routes/_fourd_common.py`'s precedent for a
shared route-layer helper module.

These are route-layer, not `calc/`: they raise `HTTPException`, which
the pure layer must never do.
"""

from __future__ import annotations

import numpy as np
from fastapi import HTTPException

from fermiviewer.calc.eds_artifacts import ArtifactRemoval, remove_artifacts
from fermiviewer.calc.eds_continuum import bremsstrahlung_component
from fermiviewer.calc.eds_peakfit import PeakFitResult, fit_peaks
from fermiviewer.calc.spectral_fit import Component, linear_background
from fermiviewer.datastruct import SPECTRAL_KINDS, DataStruct
from fermiviewer.session import UnknownImageError, store

__all__ = [
    "artifact_block",
    "artifact_prepass",
    "background_component",
    "fit_summed_peaks",
    "spectral_dataset",
]


def spectral_dataset(img_id: str) -> DataStruct:
    """Fetch an image and require a spectral axis (SPECTRUM / SI cube)."""
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind not in SPECTRAL_KINDS:
        raise HTTPException(400, "image has no spectral axis")
    return ds


def background_component(background: str, e0_kev: float | None) -> Component | None:
    if background == "none":
        return None
    if background == "linear":
        return linear_background("bg")
    if background == "bremsstrahlung":
        if e0_kev is None:
            raise HTTPException(422, "background='bremsstrahlung' needs e0_kev")
        # pure Kramers (absorption fixed): keeps the joint peak+continuum fit
        # linear in all amplitudes and well-conditioned. The low-energy
        # detector rolloff is recovered separately by /eds/continuum, which
        # fits absorption with the peaks masked out.
        return bremsstrahlung_component(e0_kev, fit_absorption=False)
    raise HTTPException(422, f"unknown background '{background}'")


def artifact_prepass(
    energy: np.ndarray,
    spectrum: np.ndarray,
    pf: PeakFitResult,
    escape_fraction: float,
) -> ArtifactRemoval:
    """Predict + measure/model escape and sum peaks from an initial fit."""
    lines = {s: e for s, e in pf.line_energies.items() if np.isfinite(e)}
    return remove_artifacts(
        energy, spectrum, lines,
        residual=spectrum - pf.fit.model,
        parent_areas=pf.net_areas,
        escape_fraction=escape_fraction,
    )


def artifact_block(removal: ArtifactRemoval) -> list[dict]:
    """Serialise an ArtifactRemoval into per-peak marker dicts for the UI."""
    out = []
    for a in removal.artifacts:
        if a.name in removal.measured:
            status, area = "measured", removal.measured[a.name]
            err = removal.measured_errors.get(a.name)
        elif a.name in removal.modeled:
            status, area, err = "modeled", removal.modeled[a.name], None
        else:
            status, area, err = "skipped", None, None
        out.append({
            "name": a.name, "label": a.label, "kind": a.kind,
            "energy_kev": a.energy_kev, "status": status,
            "area": area, "area_error": err,
        })
    return out


def fit_summed_peaks(
    energy: np.ndarray,
    spectrum: np.ndarray,
    elements: list[str],
    *,
    beam_kv: float,
    background: Component | None,
    weights: str | None,
    center_tol_kev: float,
    strip_artifacts: bool,
    escape_fraction: float,
) -> tuple[PeakFitResult, ArtifactRemoval | None]:
    """fit_peaks with an optional escape/sum-peak removal pre-pass (#8)."""
    try:
        pf = fit_peaks(
            energy, spectrum, elements,
            beam_kv=beam_kv, background=background,
            weights=weights, center_tol_kev=center_tol_kev,
        )
        if not strip_artifacts:
            return pf, None
        removal = artifact_prepass(energy, spectrum, pf, escape_fraction)
        pf = fit_peaks(
            energy, removal.corrected, elements,
            beam_kv=beam_kv, background=background,
            weights=weights, center_tol_kev=center_tol_kev,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return pf, removal
