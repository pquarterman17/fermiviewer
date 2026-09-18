"""A layers analysis as a persisted result record (ADR 0004).

Until now a cross-section analysis lived only in the browser: no
`capture_result` call anywhere in `routes/layers.py`, so the numbers never
reached the Results panel, never saved into the project file, and were
gone when the tab closed. The only durable trace was a client-side
download the user had to remember to take.

**Why detected and edited runs are both captured, and stay distinct.**
Interface positions are a judgement. The detector proposes them; an
operator drags them when it is wrong; and the difference between the two
is itself a finding — it says where the automatic method could not be
trusted on this specimen. So `/analyze/layers` records `origin:
"detected"` and `/analyze/layers/edit` records `origin: "edited"` along
with the positions it was GIVEN, and neither overwrites the other: they
are separate records, and a reader can see both and how far apart they
were. Collapsing them to "the current answer" would throw away the one
piece of information a reviewer most wants.

App layer (needs the session store), so it sits beside the route rather
than in `calc/` — the same placement rule `result_capture.py` states.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from fermiviewer.calc.layers import LayerResult
from fermiviewer.io.results_model import ResultOutput
from fermiviewer.result_capture import capture_result
from fermiviewer.session import store

__all__ = ["capture_layers"]

_LAYER_COLUMNS = ("layer", "top", "bottom", "thickness", "thickness_std")
_INTERFACE_COLUMNS = ("interface", "position", "sigma_erf", "sigma_w", "r_squared")


def _f(value: float | None) -> float:
    """None -> NaN for a numeric table cell.

    NaN, not 0: an interface with no waviness trace has no σ_w, and a zero
    there would read as a perfectly flat interface (ADR 0004 §3 — an absent
    uncertainty is absent).
    """
    return float("nan") if value is None else float(value)


def _regions(roi: tuple[int, int, int, int] | None) -> list[dict[str, Any]]:
    """The ROI this run measured, snapshotted so the record reopens after
    the live region is edited or deleted (ADR 0004 §6)."""
    if roi is None:
        return []
    return [{
        "kind": "rect",
        "convention": "(row1, col1, row2, col2), 1-based inclusive",
        "rect": list(roi),
    }]


def _outputs(res: LayerResult) -> list[ResultOutput]:
    layer_rows = np.array(
        [[float(layer.index), float(layer.top), float(layer.bottom),
          float(layer.thickness), _f(layer.thickness_std)]
         for layer in res.layers],
        dtype=np.float64,
    ).reshape(-1, len(_LAYER_COLUMNS))
    iface_rows = np.array(
        [[float(k), float(i.position), _f(i.sigma_erf), _f(i.sigma_w),
          float(i.r_squared)]
         for k, i in enumerate(res.interfaces)],
        dtype=np.float64,
    ).reshape(-1, len(_INTERFACE_COLUMNS))
    profile = np.column_stack([
        np.asarray(res.depth_pos, dtype=np.float64),
        np.asarray(res.depth_profile, dtype=np.float64),
    ])
    return [
        ResultOutput(
            kind="table",
            name="layers",
            data={
                "columns": list(_LAYER_COLUMNS),
                "units": ["", "px", "px", res.unit, res.unit],
            },
            array=layer_rows,
        ),
        ResultOutput(
            kind="table",
            name="interfaces",
            data={
                "columns": list(_INTERFACE_COLUMNS),
                # position is a depth in PROFILE pixels while the widths are
                # calibrated: the detector works on the profile index and the
                # refinement converts, so saying so beats one blanket unit.
                "units": ["", "px", res.unit, res.unit, ""],
            },
            array=iface_rows,
        ),
        # The measurement, not just the conclusion. Without it a reader
        # cannot check where an interface was placed against the data that
        # placed it.
        ResultOutput(
            kind="curve",
            name="depth_profile",
            data={
                "x_name": "depth",
                "x_unit": "px",
                "y_name": "intensity",
                # raster values carry no calibrated intensity unit here
                "y_unit": "",
            },
            array=profile,
        ),
        ResultOutput(
            kind="scalar",
            name="n_layers",
            data={"value": len(res.layers), "unit": ""},
        ),
        ResultOutput(
            kind="scalar",
            name="tilt_deg",
            data={"value": float(res.tilt_deg), "unit": "deg"},
        ),
        ResultOutput(
            kind="scalar",
            name="orientation_coherence",
            data={"value": float(res.coherence), "unit": ""},
        ),
    ]


def capture_layers(
    res: LayerResult,
    *,
    image_id: str,
    params: dict[str, Any],
    origin: str,
    calibrated: bool,
    given_positions: list[float] | None = None,
) -> dict[str, Any]:
    """Persist `res` and return the record as the route's `result` block."""
    warnings: list[str] = []
    if not calibrated:
        warnings.append(
            "image has no finite pixel size — thicknesses are in pixels, "
            "not calibrated units"
        )
    if not res.interfaces:
        warnings.append("no interfaces were found, so no layer was measured")
    weak = [k for k, i in enumerate(res.interfaces) if i.r_squared < 0.5]
    if weak:
        warnings.append(
            f"interfaces {weak} have an erf fit R² below 0.5 — their positions "
            "and widths are poorly constrained"
        )
    record = capture_result(
        analysis="analyze.layers",
        label=f"Cross-section layers of {store.name(image_id)}",
        source_ids=[image_id],
        params={
            **params,
            # What made these positions: the detector, or a person. Kept as a
            # parameter because it changes what the record MEANS, not merely
            # how it was produced.
            "interface_origin": origin,
            **({"given_positions": list(given_positions)}
               if given_positions is not None else {}),
        },
        regions=_regions(params.get("roi")),
        outputs=_outputs(res),
        warnings=warnings,
    )
    return {"id": record.id, "analysis": record.analysis, "label": record.label}
