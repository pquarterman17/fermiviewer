"""Shared param-parsing helpers for the op catalogues.

``OpParam`` only carries float/int/str/bool (see ``ops/base.py``), so any op
that needs a list-shaped input (element symbols, onset energies, "lo:hi"
windows) encodes it as a delimited string and parses it here. Factored out of
``catalogue_spectral.py`` (its original home) so ``catalogue_analysis.py``
can reuse the exact same comma-list / window-string conventions instead of
carrying a second copy as the op vocabulary grows — mirrors why
``raster_of`` lives in ``calc/raster.py`` rather than in either catalogue.
"""

from __future__ import annotations

import numpy as np

__all__ = ["clean_values", "parse_windows", "split_csv"]


def split_csv(value: str) -> list[str]:
    """``"Fe, O"`` -> ``["Fe", "O"]``; blank entries dropped."""
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_windows(value: str) -> list[tuple[float, float]]:
    """``"708:758,532:582"`` -> ``[(708.0, 758.0), (532.0, 582.0)]``."""
    out: list[tuple[float, float]] = []
    for part in split_csv(value):
        lo_s, sep, hi_s = part.partition(":")
        if not sep:
            raise ValueError(
                f"window entry {part!r} must be 'lo:hi' (got no ':' separator)"
            )
        out.append((float(lo_s), float(hi_s)))
    return out


def clean_values(values: np.ndarray) -> list[float | None]:
    """NaN/inf -> None so the value survives JSON (mirrors routes/imaging_ops.py)."""
    return [None if not np.isfinite(v) else float(v) for v in values]
