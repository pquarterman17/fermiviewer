"""AFM/SPM levelling kinds for POST /filter (calc/afm_level.py).

Kept out of routes/filter.py so the generic filter table stays small; each
entry reads and range-checks its params with the same `_num` helper, so a
bad value is a 422 with a readable message, never a numpy error.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from fermiviewer.calc import afm_level

__all__ = ["AFM_FILTERS"]

Num = Callable[..., float]


def _pct(p: dict[str, Any], num: Num) -> float:
    return num(p, "fit_percentile", 100.0, "fit percentile", lo=1.0, hi=100.0)


def _choice(p: dict[str, Any], key: str, default: str, options: tuple[str, ...]) -> str:
    v = str(p.get(key, default))
    if v not in options:
        raise ValueError(f"{key.replace('_', ' ')} must be one of {', '.join(options)}")
    return v


def build(num: Num) -> dict[str, Callable[[np.ndarray, dict[str, Any]], np.ndarray]]:
    """Filter-table entries, given the route's param reader."""

    def plane(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
        order = int(num(p, "order", 1, "order", integer=True, lo=1, hi=3))
        return afm_level.level_plane(d, order=order, fit_percentile=_pct(p, num))

    def rows(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
        return afm_level.level_rows(
            d,
            method=_choice(p, "method", "median", afm_level.ROW_METHODS),
            order=int(num(p, "order", 1, "order", integer=True, lo=1, hi=3)),
            fit_percentile=_pct(p, num),
        )

    def scars(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
        return afm_level.remove_scars(
            d,
            threshold=num(p, "threshold", 3.0, "threshold (σ)", positive=True, hi=100.0),
            max_width=int(num(p, "max_width", 2, "max width (lines)", integer=True, lo=1, hi=16)),
            min_length=int(num(p, "min_length", 8, "min length (px)", integer=True, lo=1,
                               hi=float(d.shape[1]))),
        ).corrected

    def three_point(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
        pts = p.get("points")
        if not isinstance(pts, (list, tuple)) or len(pts) != 3:
            raise ValueError("three-point levelling needs exactly 3 points [row, col]")
        parsed = []
        for i, pt in enumerate(pts):
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError(f"point {i + 1} must be [row, col]")
            parsed.append((num({"v": pt[0]}, "v", 0, f"point {i + 1} row"),
                           num({"v": pt[1]}, "v", 0, f"point {i + 1} column")))
        return afm_level.level_three_point(d, parsed)

    def zero(d: np.ndarray, p: dict[str, Any]) -> np.ndarray:
        return afm_level.zero_level(d, _choice(p, "mode", "min", afm_level.ZERO_MODES))

    return {
        "plane_level": plane,
        "row_level": rows,
        "scar_removal": scars,
        "three_point_level": three_point,
        "zero_level": zero,
    }


AFM_FILTERS = build
