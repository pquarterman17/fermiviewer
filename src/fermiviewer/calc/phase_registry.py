"""Phase registry — built-in PHASES + runtime custom phases (Diffraction #2).

A single source the diffraction routes consult instead of importing the
hard-coded ``PHASES`` tuple directly, so user/CIF-imported phases participate in
the phase list, simulation, and indexing. ``crystal.py`` keeps the built-in
tuple; this module layers custom phases on top (kept out of ``crystal.py`` to
respect the 500-line ceiling).

This is the in-memory core. On-disk persistence (per-user store / ``FV_PHASE_DB``
like ``usermeta.py``) and the import/list/delete routes are follow-ups; the
registry API is stable so they can attach later.

Pure layer: stdlib only.
"""

from __future__ import annotations

from fermiviewer.calc.crystal import PHASES, Phase, find_phase

__all__ = ["PhaseRegistry", "registry"]


class PhaseRegistry:
    """Built-in phases plus any added at runtime. Custom phases shadow a
    built-in of the same (case-insensitive) name."""

    def __init__(self) -> None:
        self._custom: dict[str, Phase] = {}

    def all(self) -> tuple[Phase, ...]:
        """Built-ins first, then custom phases (deduped by name)."""
        builtin_names = {p.name.lower() for p in PHASES}
        custom_extra = tuple(
            p for k, p in self._custom.items() if k not in builtin_names
        )
        overridden = tuple(
            self._custom.get(p.name.lower(), p) for p in PHASES
        )
        return overridden + custom_extra

    def add(self, phase: Phase) -> Phase:
        """Register (or replace) a custom phase by name."""
        self._custom[phase.name.lower()] = phase
        return phase

    def remove(self, name: str) -> bool:
        """Drop a custom phase; returns True if one was removed."""
        return self._custom.pop(name.lower(), None) is not None

    def find(self, query: str) -> Phase | None:
        """Case-insensitive contains-match over the merged set (custom first
        so a user override wins)."""
        q = query.lower()
        for p in self._custom.values():
            if q in p.name.lower() or q in p.formula.lower():
                return p
        try:
            return find_phase(query)
        except KeyError:
            return None

    @property
    def custom(self) -> tuple[Phase, ...]:
        return tuple(self._custom.values())


registry = PhaseRegistry()
"""Process-wide default phase registry."""
