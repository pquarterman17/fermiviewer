"""Atom-column analysis composition — the detect → refine → lattice →
sublattice → strain pipeline behind POST /analyze/atoms, lifted out of
`routes/structure.py` (wave B, ADR 0005 §1) so the registered `atoms` op
and the HTTP route run the SAME branchy composition, and the peak-pair
strain aggregates (`pair_strain_payload`) are shared with
POST /atoms/strain instead of living route-locally.

Lives in its own module on the wave-A `*_report.py` precedent
(`grain_report.py`, `layers_report.py`): `calc/atoms.py`'s own docstring
records that `atom_strain.py` was split out specifically to respect the
500-line module ceiling, so neither should grow this composition.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.atoms import (
    LatticeVectors,
    PairStrain,
    assign_sublattice,
    detect_columns,
    find_lattice_vectors,
    fit_gaussian_2d,
    peak_pair_strain,
)

__all__ = ["AtomColumnReport", "atom_column_report", "pair_strain_payload"]


def _nan_none(v: float) -> float | None:
    return None if not np.isfinite(v) else float(v)


def _nanmean_or_nan(values: np.ndarray) -> float:
    """NaN-aware mean without warning when every sample is missing."""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or np.isnan(array).all():
        return float("nan")
    return float(np.nanmean(array))


def pair_strain_payload(st: PairStrain) -> dict:
    """A `PairStrain` as the JSON-shaped strain block (shared by
    /analyze/atoms' strain branch and /atoms/strain)."""
    _s = lambda a: [_nan_none(v) for v in a]  # noqa: E731
    return {
        "valid": bool(st.valid),
        "exx_mean": _nan_none(_nanmean_or_nan(st.exx)),
        "eyy_mean": _nan_none(_nanmean_or_nan(st.eyy)),
        "exy_mean": _nan_none(_nanmean_or_nan(st.exy)),
        "exx": _s(st.exx),
        "eyy": _s(st.eyy),
        "exy": _s(st.exy),
        "rotation": _s(st.rotation),
        "displacement": st.displacement.tolist() if st.valid else [],
    }


@dataclass(frozen=True)
class AtomColumnReport:
    """One /analyze/atoms run's raw pieces, before JSON shaping."""

    n_columns: int
    positions: np.ndarray  # (n, 2) (x, y), 1-based
    amplitude: np.ndarray
    converged: list | None  # per-column fit convergence; None when refine off
    lattice: LatticeVectors
    sublattice: np.ndarray | None  # labels; None when sublattices == 1
    strain: PairStrain | None  # None when strain not requested


def atom_column_report(
    raster: np.ndarray,
    *,
    sigma: float = 2.0,
    threshold: float = 0.2,
    min_separation: float = 8.0,
    polarity: str = "bright",
    refine: bool = True,
    win_radius: int = 6,
    strain: bool = False,
    sublattices: int = 1,
) -> AtomColumnReport:
    """Detect atom columns, optionally Gaussian-refine, then derive the
    lattice basis and (on request) sublattice labels and PPA strain."""
    det = detect_columns(
        raster,
        sigma=sigma,
        threshold=threshold,
        min_separation=min_separation,
        polarity=polarity,
    )
    positions, amplitude, converged = det.positions, det.intensities, None
    if refine and positions.shape[0] > 0:
        fit = fit_gaussian_2d(raster, positions, win_radius=win_radius, polarity=polarity)
        positions, amplitude, converged = fit.positions, fit.amplitude, fit.converged.tolist()

    lattice = find_lattice_vectors(positions)
    sublattice = (
        assign_sublattice(np.asarray(amplitude), sublattices)
        if sublattices > 1 and positions.shape[0] > 0
        else None
    )
    pair_strain = peak_pair_strain(positions) if strain else None
    return AtomColumnReport(
        n_columns=int(positions.shape[0]),
        positions=positions,
        amplitude=np.asarray(amplitude),
        converged=converged,
        lattice=lattice,
        sublattice=sublattice,
        strain=pair_strain,
    )
