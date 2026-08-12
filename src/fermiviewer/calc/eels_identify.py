"""EELS edge auto-identification: edge-jump significance on the sum
spectrum, for every tabulated core-loss edge the cube's energy axis can
support (SPECTRAL_WORKSPACE_PLAN #22).

EDS gets its element list for free from ``/eds/auto-assign`` (peak
detection + line matching in ``calc/eds.py``), but the "how much signal is
actually there" scoring (net / sigma / significance / confidence) for EDS
lives client-side, in ``frontend/src/lib/elemental/identify.ts``, because
its inputs (a displayed spectrum, a background model already ported to
TypeScript) are cheap to recompute in the browser. EELS has no equivalent
port, and edge-jump detection needs the SAME pre-edge power-law fit
``calc/eels.py`` already owns — so this module computes the whole thing
server-side instead: for each ``EELS_EDGES`` entry, fit a pre-edge window
with ``calc.eels.background`` and integrate a post-onset signal window on
the SUM spectrum, scored the same way (net, sigma, significance, confidence
band) so a later frontend pass can converge on one vocabulary for both
modalities.

Pure library (numpy only) — no fastapi/pydantic/route imports (enforced by
tests/test_repo_integrity.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from fermiviewer.calc.eels import EELS_EDGES, background

__all__ = [
    "EDGE_FIT_GAP_EV",
    "EDGE_FIT_WIDTH_EV",
    "EDGE_SIGNAL_WIDTH_EV",
    "Confidence",
    "EdgeIdentification",
    "confidence_of",
    "identify_edges",
]

Confidence = Literal["strong", "clear", "weak", "trace"]

# Counting-statistics confidence bands, in significance (net/sigma) units.
# Deliberately the SAME thresholds as the EDS identifier's BANDS
# (frontend/src/lib/elemental/identify.ts) — not shared by import (calc/
# cannot import from frontend/), but kept in numeric lockstep so a signal at
# a given sigma level reads the same way in both modalities.
_BANDS: tuple[tuple[float, Confidence], ...] = (
    (100.0, "strong"),
    (30.0, "clear"),
    (10.0, "weak"),
)

# Conventional post-onset integration width (eV): wide enough to capture the
# edge, narrow enough to stay clear of the next one in a crowded spectrum
# (Egerton). Numerically the same value as the frontend's default EELS
# species window (species.ts EELS_SIGNAL_WIDTH_EV) — defined independently
# here per this module's "don't import from frontend/" constraint.
EDGE_SIGNAL_WIDTH_EV = 50.0

# Pre-edge background-fit window width (eV), immediately below the onset.
EDGE_FIT_WIDTH_EV = 50.0

# Gap (eV) between the fit window's upper edge and the onset, and between
# the onset and... nothing — the signal window starts AT the onset, since
# that is where the edge jump itself begins. The gap only keeps the rising
# edge out of the pre-edge background fit; without it a fit window ending
# exactly at onset can pick up the first channel or two of the jump and
# bias the extrapolated background upward, understating every edge's net.
EDGE_FIT_GAP_EV = 2.0


def confidence_of(significance: float) -> Confidence:
    """Band a net/sigma ratio the same way the EDS identifier does."""
    for threshold, label in _BANDS:
        if significance >= threshold:
            return label
    return "trace"


@dataclass(frozen=True)
class EdgeIdentification:
    element: str
    edge: str
    symbol: str                              # "Fe-L23" (Edge.symbol)
    onset_ev: float
    fit_window: tuple[float, float]
    signal_window: tuple[float, float]
    net: float
    sigma: float
    significance: float
    confidence: Confidence


def identify_edges(
    energy: np.ndarray,
    spectrum: np.ndarray,
    fit_width_ev: float = EDGE_FIT_WIDTH_EV,
    signal_width_ev: float = EDGE_SIGNAL_WIDTH_EV,
    fit_gap_ev: float = EDGE_FIT_GAP_EV,
    method: str = "powerlaw",
) -> list[EdgeIdentification]:
    """Edge-jump significance for every ``EELS_EDGES`` entry the axis fits.

    For each tabulated edge, a pre-edge window
    ``[onset - fit_gap_ev - fit_width_ev, onset - fit_gap_ev]`` is fit with
    ``calc.eels.background`` (powerlaw by default) and a post-onset window
    ``[onset, onset + signal_width_ev]`` is measured on ``spectrum``. An
    edge is skipped entirely — not reported with an error, since this is a
    "what's plausibly here" survey over 49 tabulated edges, not a per-row
    request a user must be told about — when either window would run off
    the cube's energy axis: a truncated pre-edge fit silently biases the
    extrapolated background, and a truncated signal window undercounts the
    jump, so neither is reported rather than reported wrong.

    net = gross − extrapolated background, summed over the signal window
    (``calc.eels.background``'s per-channel ``max(spectrum - bg, 0)``);
    sigma = sqrt(gross) — the Poisson counting-statistics error on the raw
    window sum, the same leading-order approximation
    ``calc.uncertainty``'s module docstring documents for the
    window-integration regime (the background-fit extrapolation's own
    uncertainty is a second-order term, omitted here as it is there);
    significance = net / sigma. Results are sorted by significance,
    strongest first.
    """
    energy = np.asarray(energy, dtype=np.float64).ravel()
    spectrum = np.asarray(spectrum, dtype=np.float64).ravel()
    if energy.size != spectrum.size:
        raise ValueError("energy and spectrum must have equal length")
    if energy.size == 0:
        return []
    e_min, e_max = float(energy.min()), float(energy.max())

    out: list[EdgeIdentification] = []
    for edge in EELS_EDGES:
        onset = edge.onset_ev
        fit_hi = onset - fit_gap_ev
        fit_lo = fit_hi - fit_width_ev
        sig_lo, sig_hi = onset, onset + signal_width_ev
        if fit_lo < e_min or sig_hi > e_max:
            continue
        sig_mask = (energy >= sig_lo) & (energy <= sig_hi)
        if sig_mask.sum() < 2:
            continue
        try:
            signal, _bg, _params = background(
                energy, spectrum, (fit_lo, fit_hi), method
            )
        except ValueError:
            continue

        gross = float(spectrum[sig_mask].sum())
        net = float(signal[sig_mask].sum())
        sigma = float(np.sqrt(max(gross, 0.0)))
        significance = net / sigma if sigma > 0 else 0.0
        out.append(EdgeIdentification(
            element=edge.element, edge=edge.edge, symbol=edge.symbol,
            onset_ev=onset, fit_window=(fit_lo, fit_hi),
            signal_window=(sig_lo, sig_hi), net=net, sigma=sigma,
            significance=significance, confidence=confidence_of(significance),
        ))

    out.sort(key=lambda e: e.significance, reverse=True)
    return out
