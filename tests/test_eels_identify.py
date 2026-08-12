"""calc.eels_identify: edge-jump auto-identification (SPECTRAL_WORKSPACE_PLAN
#22) — pure calc layer.

Onset energies come from the app's own ``calc.eels.EELS_EDGES`` table, never
a transcribed copy, so a planted edge cannot silently drift away from the
table the identifier itself consults (fixtures-derive-from-production-tables).
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.eels import EELS_EDGES
from fermiviewer.calc.eels_identify import (
    EDGE_FIT_GAP_EV,
    EDGE_FIT_WIDTH_EV,
    EDGE_SIGNAL_WIDTH_EV,
    confidence_of,
    identify_edges,
)

pytestmark = pytest.mark.eels


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


def _spectrum_with_edges(
    edges: list[tuple[float, float]], scale: float = 2.0, offset: float = 300.0,
    n: int = 400,
) -> tuple[np.ndarray, np.ndarray]:
    """(energy, spectrum): power-law background + step jumps of the given
    (onset_ev, amplitude) pairs, deterministic (no noise)."""
    energy = offset + scale * np.arange(n)
    spectrum = 8000.0 * (energy / energy[0]) ** -3.0
    for onset, amplitude in edges:
        spectrum = spectrum + amplitude * (energy >= onset)
    return energy, spectrum


# ── confidence banding ──────────────────────────────────────────────

@pytest.mark.parametrize(
    ("significance", "expected"),
    [(500.0, "strong"), (100.0, "strong"), (99.9, "clear"), (30.0, "clear"),
     (29.9, "weak"), (10.0, "weak"), (9.9, "trace"), (0.0, "trace"),
     (-5.0, "trace")],
)
def test_confidence_of_bands(significance: float, expected: str) -> None:
    assert confidence_of(significance) == expected


# ── identify_edges: planted vs. absent ──────────────────────────────

def test_identify_edges_recovers_planted_jumps_and_ignores_absent_ones() -> None:
    o_edge = _edge("O", "K")            # 532 eV
    fe_edge = _edge("Fe", "L23")        # 708 eV
    energy, spectrum = _spectrum_with_edges(
        [(o_edge.onset_ev, 4000.0), (fe_edge.onset_ev, 2500.0)]
    )
    results = identify_edges(energy, spectrum)
    by_symbol = {r.symbol: r for r in results}

    assert by_symbol["O-K"].confidence in ("strong", "clear")
    assert by_symbol["Fe-L23"].confidence in ("strong", "clear")
    assert by_symbol["O-K"].net > 0
    assert by_symbol["Fe-L23"].net > 0

    # candidate edges the axis supports but which carry no planted jump —
    # e.g. N K (401 eV) sits well within [300, 1098] with margin to spare —
    # must NOT read as confidently present.
    assert "N-K" in by_symbol
    assert by_symbol["N-K"].confidence in ("weak", "trace")
    assert "Ti-L23" in by_symbol
    assert by_symbol["Ti-L23"].confidence in ("weak", "trace")


def test_identify_edges_sorted_by_significance_descending() -> None:
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    energy, spectrum = _spectrum_with_edges(
        [(o_edge.onset_ev, 4000.0), (fe_edge.onset_ev, 2500.0)]
    )
    results = identify_edges(energy, spectrum)
    sigs = [r.significance for r in results]
    assert sigs == sorted(sigs, reverse=True)
    # the two planted edges should rank well above the unplanted majority —
    # not necessarily #1/#2, since a tabulated edge a few eV away from a
    # planted onset legitimately shares most of the same signal window
    # (e.g. Sb-M45 at 528 eV vs. the planted O-K jump at 532 eV) and is
    # expected to also score high. Both planted edges must clear the
    # "strong" band and sit in the top quarter of the ranked list.
    by_symbol = {r.symbol: i for i, r in enumerate(results)}
    assert results[by_symbol["O-K"]].confidence == "strong"
    assert results[by_symbol["Fe-L23"]].confidence == "strong"
    assert by_symbol["O-K"] < len(results) / 4
    assert by_symbol["Fe-L23"] < len(results) / 4


def test_identify_edges_reports_the_table_fields_verbatim() -> None:
    """symbol/element/edge/onset_ev must match EELS_EDGES exactly — this
    endpoint must never transcribe or perturb the table it consults."""
    o_edge = _edge("O", "K")
    energy, spectrum = _spectrum_with_edges([(o_edge.onset_ev, 4000.0)])
    results = identify_edges(energy, spectrum)
    row = next(r for r in results if r.symbol == "O-K")
    assert row.element == o_edge.element
    assert row.edge == o_edge.edge
    assert row.onset_ev == o_edge.onset_ev
    assert row.symbol == o_edge.symbol


# ── margins: edges too close to the axis ends are excluded ──────────

def test_identify_edges_excludes_onsets_without_margin_for_both_windows() -> None:
    """An edge whose pre-edge fit window or post-onset signal window would
    run off the axis must be skipped entirely, not truncated or reported
    with an error — this is a survey over 49 tabulated edges, not a
    per-row user request."""
    fit_span = EDGE_FIT_GAP_EV + EDGE_FIT_WIDTH_EV
    o_edge = _edge("O", "K")  # 532 eV

    # Axis starts exactly AT the onset minus the needed fit span minus a
    # hair: the fit window would run off the low end by construction.
    n = 400
    scale = 1.0
    offset = o_edge.onset_ev - fit_span + 1.0    # 1 eV short of enough margin
    energy = offset + scale * np.arange(n)
    spectrum = 8000.0 * (energy / max(energy[0], 1.0)) ** -3.0
    results = identify_edges(energy, spectrum)
    assert "O-K" not in {r.symbol for r in results}

    # Now give it exactly enough margin on both sides and it must appear.
    offset_ok = o_edge.onset_ev - fit_span - 5.0
    n_ok = int((o_edge.onset_ev + EDGE_SIGNAL_WIDTH_EV + 5.0 - offset_ok) / scale) + 1
    energy_ok = offset_ok + scale * np.arange(n_ok)
    spectrum_ok = 8000.0 * (energy_ok / max(energy_ok[0], 1.0)) ** -3.0
    results_ok = identify_edges(energy_ok, spectrum_ok)
    assert "O-K" in {r.symbol for r in results_ok}


def test_identify_edges_empty_axis_returns_empty_list() -> None:
    assert identify_edges(np.array([]), np.array([])) == []


def test_identify_edges_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="equal length"):
        identify_edges(np.arange(10, dtype=float), np.arange(5, dtype=float))


def test_identify_edges_no_edges_in_a_narrow_axis() -> None:
    """A narrow window that supports no edge's full margin is a legitimate
    empty result, not an error."""
    energy = np.linspace(1.0, 5.0, 20)  # far below any tabulated onset
    spectrum = np.full(20, 10.0)
    assert identify_edges(energy, spectrum) == []
