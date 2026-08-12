"""Fit-quality scalar shared by the EELS/EDS model-fit routes (audit R4).

``calc/spectral_fit.py`` already computes ``reduced_chi2`` (a weighted
goodness-of-fit) and the raw ``residual``/``covariance``, but nothing
answers the plainer question a GUI readout wants: "how much of the
spectrum's own variance does the model explain?" That is the ordinary,
UNWEIGHTED coefficient of determination

    R^2 = 1 - SS_res / SS_tot
    SS_res = sum((actual - predicted)^2)
    SS_tot = sum((actual - mean(actual))^2)

— deliberately not weighted by the fit's 1/sigma^2 weights the way
``reduced_chi2`` is, so it stays a plain "fraction of variance explained"
number a non-statistician can read directly, matching the convention
already used by ``calc/ctf.py``'s ``CtfResult.r_squared``.

Callers MUST pass ``actual``/``predicted`` over the SAME window the fit
actually ran on (e.g. ``calc/eels_model.fit_edges``'s ``fit_range`` mask),
not a wider display range — R^2 answers "did the model explain what it
was fit to", and a window mismatch silently answers a different question.

Pure library: numpy only. No fastapi/pydantic/route imports (enforced by
tests/test_repo_integrity.py).
"""

from __future__ import annotations

import numpy as np

__all__ = ["r_squared"]


def r_squared(actual: np.ndarray, predicted: np.ndarray) -> float:
    """1 - SS_res/SS_tot over the given (already-windowed) arrays.

    Returns 0.0 when ``actual`` is degenerate (constant, so SS_tot == 0)
    instead of NaN/±inf — mirrors ``calc/ctf.py``'s ``r_squared``
    convention rather than leaving an undefined ratio for a flat/blank
    fit window.
    """
    a = np.asarray(actual, dtype=np.float64).ravel()
    p = np.asarray(predicted, dtype=np.float64).ravel()
    if a.shape != p.shape:
        raise ValueError("actual and predicted must be equal-length arrays")
    ss_tot = float(np.sum((a - a.mean()) ** 2))
    if ss_tot <= 0.0:
        return 0.0
    ss_res = float(np.sum((a - p) ** 2))
    return 1.0 - ss_res / ss_tot
