"""Layer-report composition — the roughness metrology + JSON shaping behind
POST /analyze/layers (and /layers/edit), lifted out of `routes/layers.py`
(wave A, ADR 0005 §1) so the registered `layers` / `layers_edit` ops and
the HTTP routes run the SAME per-interface `analyze_trace` → `sigma_chem`
→ `conformality` composition instead of the ops re-wiring it.

Lives in its own module because `calc/layers.py` already sits at the
500-line module ceiling. Pure: numpy/math + calc only — the dict this
builds is plain JSON-shaped data (floats/lists/None), which both the
route response and the op envelope builder consume as-is.
"""

from __future__ import annotations

import math

import numpy as np

from fermiviewer.calc.layers import LayerResult
from fermiviewer.calc.trace_roughness import analyze_trace, conformality, sigma_chem

__all__ = ["interface_layer_blocks", "layer_result_to_dict", "roughness_blocks"]


def _nan_none(x: float) -> float | None:
    return None if not math.isfinite(x) else float(x)


def roughness_blocks(
    res: LayerResult,
) -> tuple[list[dict | None], list[float | None]]:
    """Per-interface roughness reports + per-layer conformality (items #9-12).

    Runs the full trace metrology (detrend/robust/noise-corrected sigma with a
    block-bootstrap CI, PSD, self-affine xi/H, quality) on every traced
    interface, plus the sigma_chem quadrature decomposition and the adjacent-
    trace conformality r for each layer. Interfaces without a trace (waviness
    off) report None.
    """
    reports: list[dict | None] = []
    resids: list[np.ndarray | None] = []
    for i in res.interfaces:
        if i.trace is None:
            reports.append(None)
            resids.append(None)
            continue
        # heights scale by the depth extent, lateral positions by the other
        r = analyze_trace(
            i.trace,
            res.pixel_size,
            lateral_size=res.lateral_size if math.isfinite(res.lateral_size) else None,
        )
        resids.append(r.detrended)
        lo, hi = r.sigma_ci
        reports.append(
            {
                "sigma_ci": [lo, hi] if math.isfinite(lo) and math.isfinite(hi) else None,
                "sigma_raw": _nan_none(r.sigma_raw),
                "noise_floor": _nan_none(r.noise_floor),
                "quality": r.quality,
                "xi": _nan_none(r.xi),
                "hurst": _nan_none(r.hurst),
                "sigma_chem": _nan_none(sigma_chem(i.sigma_erf, r.sigma_w)),
                "psd_wavelength": r.psd_wavelength.tolist(),
                "psd_power": r.psd_power.tolist(),
            }
        )
    conf: list[float | None] = []
    for k in range(max(0, len(res.interfaces) - 1)):
        a, b = resids[k], resids[k + 1]
        conf.append(_nan_none(conformality(a, b)) if a is not None and b is not None else None)
    return reports, conf


def interface_layer_blocks(res: LayerResult) -> dict[str, list[dict]]:
    """The comparison-sized slice of a `LayerResult`: sharpness + thickness.

    What a cross-map comparison (POST /analyze/layers/multi) needs per map —
    per interface ``position`` (profile pixels) with ``sigma_erf``/``sigma_w``,
    per layer ``index`` with ``thickness``/``thickness_std`` (all calibrated
    units) — and nothing else: no depth profile, no traces, no PSD. One row
    per map times a handful of maps, so the full `layer_result_to_dict`
    payload would be mostly per-map bulk nobody plots.

    Non-finite values become None (JSON has no NaN); ``thickness`` cannot be
    NaN — it is a difference of two refined positions — so it passes through.
    """
    return {
        "interfaces": [
            {
                "position": i.position,
                "sigma_erf": _nan_none(i.sigma_erf),
                "sigma_w": _nan_none(i.sigma_w),
            }
            for i in res.interfaces
        ],
        "layers": [
            {
                "index": lyr.index,
                "thickness": lyr.thickness,
                "thickness_std": _nan_none(lyr.thickness_std),
            }
            for lyr in res.layers
        ],
    }


def layer_result_to_dict(res: LayerResult) -> dict:
    """A `LayerResult` as the JSON-shaped analysis report (route payload)."""
    rough, conf = roughness_blocks(res)
    return {
        "axis": res.axis,
        "layers_horizontal": res.layers_horizontal,
        "tilt_deg": _nan_none(res.tilt_deg),
        "coherence": _nan_none(res.coherence),
        "pixel_size": res.pixel_size,
        "unit": res.unit,
        "depth_pos": res.depth_pos.tolist(),
        "depth_profile": res.depth_profile.tolist(),
        "interfaces": [
            {
                "position": i.position,
                "sigma_erf": _nan_none(i.sigma_erf),
                "r_squared": i.r_squared,
                "sigma_w": _nan_none(i.sigma_w),
                "trace": i.trace.tolist() if i.trace is not None else None,
                "roughness": rough[k],
            }
            for k, i in enumerate(res.interfaces)
        ],
        "layers": [
            {
                "index": lyr.index,
                "top": lyr.top,
                "bottom": lyr.bottom,
                "thickness": lyr.thickness,
                "thickness_std": _nan_none(lyr.thickness_std),
                "conformality": conf[lyr.index] if lyr.index < len(conf) else None,
            }
            for lyr in res.layers
        ],
    }
