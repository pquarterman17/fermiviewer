"""Route-layer helpers shared by the model-based EDS route modules.

`routes/eds_advanced.py` carries the continuum/peakfit/artifacts/
recalibrate surface; `routes/eds_zeta.py` carries ζ-factor
quantification. Both fit the same summed-spectrum peak model with the
same background choices and the same escape/sum-peak pre-pass, and
neither can import the other without a cycle — so the shared glue lives
here, following `routes/_fourd_common.py`'s precedent for a shared
route-layer helper module.

The composition numerics were lifted to the pure layer in wave D
(ADR 0005 §1): `background_component` → `calc.eds_continuum`,
`fit_summed_peaks` → `calc.eds_peakfit`, `artifact_prepass` /
`artifact_block` → `calc.eds_artifacts`. What remains here is genuinely
route-layer: session lookup (`spectral_dataset`), the ValueError → 422
translation the calc versions delegate upward, and re-exports so both
route modules keep one import site.
"""

from __future__ import annotations

import numpy as np
from fastapi import HTTPException

from fermiviewer.calc.eds_artifacts import (
    ArtifactRemoval,
    artifact_block,
    artifact_prepass,
)
from fermiviewer.calc.eds_continuum import (
    background_component as _background_component,
)
from fermiviewer.calc.eds_peakfit import (
    PeakFitResult,
    fit_peaks,
)
from fermiviewer.calc.eds_peakfit import (
    fit_summed_peaks as _fit_summed_peaks,
)
from fermiviewer.calc.spectral_fit import Component
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
    """`calc.eds_continuum.background_component` with ValueError → 422."""
    try:
        return _background_component(background, e0_kev)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


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
    """`calc.eds_peakfit.fit_summed_peaks` with ValueError → 422.

    Passes this module's `fit_peaks` global as the fit entry point so the
    call stays late-bound here — the patch seam the endpoint tests use.
    """
    try:
        return _fit_summed_peaks(
            energy,
            spectrum,
            elements,
            beam_kv=beam_kv,
            background=background,
            weights=weights,
            center_tol_kev=center_tol_kev,
            strip_artifacts=strip_artifacts,
            escape_fraction=escape_fraction,
            fit=fit_peaks,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
