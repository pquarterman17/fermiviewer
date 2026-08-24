"""EELS summary/aggregate numerics — the payload-derived statistics behind
POST /eels/quantify-map, /eels/thickness and /eels/svd, lifted out of
`routes/analysis.py` (wave D, ADR 0005 §1) so the registered ops and the
HTTP routes compute the SAME per-element means, thickness summary and SVD
view instead of the ops re-deriving the route-local arithmetic.

Session-free by construction: the routes keep registering the maps/cubes as
derived images and shaping JSON (``.tolist()``); this module only turns
calc results into numbers and raw ndarray views. Lives in its own module
because `routes/analysis.py` sits at the 500-line module ceiling and
`calc/eels.py` / `calc/eels_advanced.py` are near it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eels_advanced import SVDResult

__all__ = ["SvdView", "mean_atomic_percent", "svd_view", "thickness_summary"]


def mean_atomic_percent(atomic_percent_cube: np.ndarray) -> list[float]:
    """Per-element spatial nanmean of a [Ny, Nx, nElem] at% cube — the
    ``mean_atomic_percent`` aggregate of /eels/quantify-map's payload."""
    cube = np.asarray(atomic_percent_cube)
    return [float(np.nanmean(cube[:, :, k])) for k in range(cube.shape[2])]


def thickness_summary(t: np.ndarray, valid: np.ndarray) -> tuple[float, float]:
    """``(mean_t_over_lambda, valid_fraction)`` for a `thickness_map` result.

    Exactly the route's arithmetic: the mean is ``nanmean(t)`` when any
    pixel is valid and 0.0 otherwise; the fraction is ``valid.mean()``.
    """
    mean_t = float(np.nanmean(t)) if valid.any() else 0.0
    return mean_t, float(valid.mean())


@dataclass(frozen=True)
class SvdView:
    """The displayed slice of an `SVDResult` — raw ndarrays; presentation
    layers do their own ``.tolist()`` / session registration."""

    #: the first ``k_show`` score maps, each [Ny, Nx]
    score_maps: list[np.ndarray]
    #: eigenspectra transposed to [k_show, nE] (one row per component)
    eigenspectra: np.ndarray
    k_show: int


def svd_view(res: SVDResult, n_score_maps: int) -> SvdView:
    """The ``k_show = min(n_score_maps, k)`` slicing /eels/svd applies to an
    `SVDResult` before shaping its payload."""
    k_show = min(int(n_score_maps), res.singular_values.size)
    return SvdView(
        score_maps=[res.score_maps[:, :, j] for j in range(k_show)],
        eigenspectra=res.eigenspectra[:, :k_show].T,
        k_show=k_show,
    )
