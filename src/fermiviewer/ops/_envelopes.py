"""ADR 0004 §3 output-envelope builders shared by the wave catalogues.

Every value op registered from wave 3B onward returns
``value = {"outputs": [...]}`` where each entry is ``{kind, name, data}``
(ADR 0005 §5) — this module keeps the envelope spelling in ONE place so
the wave catalogues cannot drift on it. The op layer is pure and has no
project file, so arrays inline as lists inside ``data``; the 1C result
API turns an envelope list into a persisted record with members.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["nan_none", "output", "scalar"]

#: the ADR 0004 closed kind set, for reference and tests
OUTPUT_KINDS = ("scalar", "table", "curve", "fit", "map", "overlay", "figure")


def nan_none(v: float) -> float | None:
    """NaN/inf -> None so inline envelope data survives JSON (one home —
    wave A carried per-catalogue copies)."""
    return None if not math.isfinite(v) else float(v)


def output(kind: str, name: str, data: dict[str, Any]) -> dict[str, Any]:
    """One ADR 0004 output envelope with inline ``data``."""
    if kind not in OUTPUT_KINDS:
        raise ValueError(f"unknown output kind {kind!r} (have: {OUTPUT_KINDS})")
    return {"kind": kind, "name": name, "data": data}


def scalar(
    name: str, value: float | int, unit: str = "", sigma: float | None = None
) -> dict[str, Any]:
    """A scalar envelope; ``sigma`` absent — not zero/None — when no honest
    uncertainty exists (ADR 0004 §3)."""
    data: dict[str, Any] = {"value": value, "unit": unit}
    if sigma is not None:
        data["sigma"] = sigma
    return output("scalar", name, data)
