"""Per-species EELS map composition — the window-sorting, axis-bounds
validation and per-species `extract_map` loop behind POST /eels/maps,
lifted out of `routes/eels_maps.py` (wave D, ADR 0005 §1) so the
registered op and the HTTP route compose the SAME batch of rasters.

The EELS twin of `calc/eds_maps.extract_element_maps`, with one deliberate
difference inherited from the route: there is no line-energy lookup — the
windows are taken as given — and a species that cannot be mapped is never
silently skipped. Each spec yields exactly one row, in request order; a
row whose window falls off the cube's energy axis, or whose background
fit fails (`extract_map`'s ValueError — degenerate fit window etc.),
carries its human-readable ``error`` instead of a map. Nothing here
raises for a bad species; whole-request failures (empty species list,
wrong data kind) stay with the caller.

Session-free by construction: the route keeps registering derived images
(``save_derived``) and shaping JSON; this module only turns a cube and a
spec list into rows of raw ndarrays and reasons.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from fermiviewer.calc.eels import extract_map

__all__ = ["SpeciesMapRow", "SpeciesSpec", "species_maps"]


@dataclass(frozen=True)
class SpeciesSpec:
    """One requested species — a free-text label plus its integration
    windows (eV, in either order; they are sorted before use). ``bg_window
    is None`` sums the signal window directly (no background subtraction),
    the same behaviour ``extract_map`` gives for ``background_window=None``.
    """

    label: str
    signal_window: tuple[float, float]
    bg_window: tuple[float, float] | None = None
    method: str = "powerlaw"  # "powerlaw" | "exponential"


@dataclass(frozen=True)
class SpeciesMapRow:
    """One species' outcome. Success: ``map``/``total_counts`` set and the
    windows are the sorted (lo, hi) pairs actually integrated. Failure:
    ``error`` holds the reason and map, counts and windows are None."""

    label: str
    signal_window: tuple[float, float] | None
    bg_window: tuple[float, float] | None
    method: str
    map: np.ndarray | None
    total_counts: float | None
    error: str | None


def _outside_axis_reason(
    win: tuple[float, float], e_min: float, e_max: float, kind: str
) -> str | None:
    lo, hi = sorted(win)
    if lo > e_max or hi < e_min:
        return (
            f"{kind} window [{lo:.3f}, {hi:.3f}] eV is outside the energy "
            f"axis [{e_min:.3f}, {e_max:.3f}] eV"
        )
    return None


def species_maps(
    cube: np.ndarray,
    energy: np.ndarray,
    specs: Sequence[SpeciesSpec],
) -> list[SpeciesMapRow]:
    """N species → N rows, without going through quantification.

    Every spec gets a row, in order — partly-failed and wholly-failed lists
    come back the same way, one reason per failed row.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    e_min, e_max = float(energy.min()), float(energy.max())

    rows: list[SpeciesMapRow] = []
    for spec in specs:
        label = spec.label.strip()
        reason = _outside_axis_reason(spec.signal_window, e_min, e_max, "signal")
        bg_window: tuple[float, float] | None = None
        if spec.bg_window is not None:
            b_lo, b_hi = sorted(spec.bg_window)
            bg_window = (b_lo, b_hi)
            if reason is None:
                reason = _outside_axis_reason(spec.bg_window, e_min, e_max, "background")

        m: np.ndarray | None = None
        sig_lo, sig_hi = sorted(spec.signal_window)
        if reason is None:
            try:
                m = extract_map(cube, energy, (sig_lo, sig_hi), bg_window, spec.method)
            except ValueError as e:
                reason = str(e)

        if reason is not None:
            rows.append(
                SpeciesMapRow(
                    label=label,
                    signal_window=None,
                    bg_window=None,
                    method=spec.method,
                    map=None,
                    total_counts=None,
                    error=reason,
                )
            )
            continue

        assert m is not None
        rows.append(
            SpeciesMapRow(
                label=label,
                signal_window=(sig_lo, sig_hi),
                bg_window=bg_window,
                method=spec.method,
                map=m,
                total_counts=float(m.sum()),
                error=None,
            )
        )
    return rows
