"""Metadata accessors — ports of getGrayscale / getStageTilt (plan B).

Small heuristics over parser metadata; pure functions, no I/O.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ["get_stage_tilt", "to_grayscale"]

# BT.601 luma weights (the MATLAB getGrayscale convention)
_LUMA = (0.299, 0.587, 0.114)

# keys searched, in priority order; (key, assume_radians_if_small)
_TILT_KEYS = (
    ("StageT", True),     # FEI/Thermo — radians or degrees, heuristic
    ("StageTa", True),
    ("Tilt", True),
    ("stageTilt_deg", False),  # Bruker Esprit — always degrees
)


def to_grayscale(pixels: np.ndarray) -> np.ndarray:
    """RGB(A) → grayscale via BT.601 luma; passthrough for 2-D input."""
    arr = np.asarray(pixels, dtype=np.float64)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3 and arr.shape[2] >= 3:
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        return _LUMA[0] * r + _LUMA[1] * g + _LUMA[2] * b
    raise ValueError(f"unsupported pixel array shape {arr.shape}")


def _search(node: Any, key: str) -> Any:
    """Depth-first search for `key` in nested dicts."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _search(v, key)
            if found is not None:
                return found
    return None


def get_stage_tilt(metadata: dict[str, Any]) -> tuple[float, str]:
    """Stage tilt in DEGREES from parser metadata, with the source key.

    FEI heuristic (ported): values with |v| < π are assumed radians and
    converted; larger values are taken as degrees. Returns (nan, "")
    when no tilt key is present.
    """
    for key, maybe_radians in _TILT_KEYS:
        val = _search(metadata, key)
        if val is None:
            continue
        try:
            tilt = float(val)
        except (TypeError, ValueError):
            continue
        if maybe_radians and abs(tilt) < np.pi:
            tilt = float(np.degrees(tilt))
        return tilt, key
    return float("nan"), ""
