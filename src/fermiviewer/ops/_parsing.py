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

from fermiviewer.calc.roi import RectRoi, parse_rect_roi
from fermiviewer.datastruct import DataStruct

__all__ = [
    "clean_values",
    "parse_roi_param",
    "parse_windows",
    "pixel_cal",
    "sentinel_group",
    "split_csv",
]


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


def parse_roi_param(value: str) -> RectRoi | None:
    """``"r1,c1,r2,c2"`` -> RectRoi; ``""`` -> None (whole image); anything
    else is an error — `calc.roi.parse_rect_roi`'s silent-None fallback (fine
    for provenance metadata) would silently analyze the whole image on a
    typo'd op param."""
    if not value:
        return None
    roi = parse_rect_roi(value)
    if roi is None:
        raise ValueError(f"roi must be 'r1,c1,r2,c2' (1-based, inclusive), got {value!r}")
    return roi


def clean_values(values: np.ndarray) -> list[float | None]:
    """NaN/inf -> None so the value survives JSON (mirrors routes/imaging_ops.py)."""
    return [None if not np.isfinite(v) else float(v) for v in values]


def sentinel_group(params: dict, names: tuple[str, ...]) -> tuple[float, ...] | None:
    """NaN-sentinel param group: all-finite -> tuple, all-NaN -> None,
    mixed -> error (a half-given seed/rect must not silently fall back).
    Wave A's `_pair`, promoted here for the later waves."""
    values = [params[n] for n in names]
    finite = [np.isfinite(v) for v in values]
    if all(finite):
        return tuple(float(v) for v in values)
    if not any(finite):
        return None
    raise ValueError(f"{', '.join(names)} must be given together")


def pixel_cal(ds: DataStruct) -> tuple[float, str]:
    """(pixel_size or NaN, unit) — the route modules' calibration idiom.
    Wave A's `_px_cal`, promoted here for the later waves."""
    px = ds.pixel_size if np.isfinite(ds.pixel_size) else float("nan")
    return px, ds.pixel_unit or "px"
