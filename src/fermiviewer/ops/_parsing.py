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

from fermiviewer.calc.eels_quant import ElementEdge
from fermiviewer.calc.roi import RectRoi, parse_rect_roi
from fermiviewer.datastruct import DataStruct

__all__ = [
    "clean_values",
    "edges_from_params",
    "int_group",
    "parse_roi_param",
    "parse_windows",
    "pixel_cal",
    "pixel_cal_or_default",
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


def pixel_cal_or_default(ds: DataStruct) -> tuple[float, str]:
    """(pixel_size or 1.0, unit) — the OTHER calibration idiom: fall back
    to 1.0/px when uncalibrated, for calcs that always need a number
    (defects, GPA-adjacent routes). Three pre-wave catalogues still carry
    local spellings of this; migrate them when their code is next
    touched, and never mint a new copy."""
    if np.isfinite(ds.pixel_size) and ds.pixel_size > 0:
        return ds.pixel_size, ds.pixel_unit or "px"
    return 1.0, ds.pixel_unit or "px"


def int_group(values: tuple[float, ...], what: str) -> tuple[int, ...]:
    """NaN-sentinel groups ride float params; when the underlying
    quantities are integers a fractional value is rejected — `int()`
    truncation would silently compute a DIFFERENT reflection/region than
    requested, where the routes' pydantic int fields reject the same
    input. Wave C's `_int_group`, promoted here on its second consumer."""
    if any(v != int(v) for v in values):
        raise ValueError(f"{what} must be whole numbers, got {list(values)}")
    return tuple(int(v) for v in values)


def edges_from_params(params: dict, opname: str) -> list[ElementEdge]:
    """The six-CSV EELS edge schema (elements/shells/z/onset_ev/
    signal_windows/bg_windows) as `ElementEdge`s, with the shared
    same-length validation. Existed as per-catalogue copies in
    `catalogue_spectral` and `catalogue_analysis`; promoted here when
    wave D's map ops became the third and fourth consumers."""
    elements = split_csv(params["elements"])
    shells = split_csv(params["shells"])
    z_list = [int(v) for v in split_csv(params["z"])]
    onsets = [float(v) for v in split_csv(params["onset_ev"])]
    sig_windows = parse_windows(params["signal_windows"])
    bg_windows = parse_windows(params["bg_windows"])
    lengths = {len(elements), len(shells), len(z_list), len(onsets),
               len(sig_windows), len(bg_windows)}
    if len(lengths) != 1 or not elements:
        raise ValueError(
            f"{opname}: elements/shells/z/onset_ev/signal_windows/bg_windows "
            f"must all list the same non-zero number of edges "
            f"(got lengths {sorted(lengths)})"
        )
    return [
        ElementEdge(elements[i], shells[i], z_list[i], onsets[i],
                    sig_windows[i], bg_windows[i])
        for i in range(len(elements))
    ]
