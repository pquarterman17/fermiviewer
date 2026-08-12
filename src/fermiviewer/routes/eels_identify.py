"""EELS edge auto-identification endpoint (SPECTRAL_WORKSPACE_PLAN #22).

EDS gets its candidate element list for free via ``/eds/auto-assign``
(routes/analysis_wireups.py) — peak detection + line matching in
``calc/eds.py``. EELS has no analogue: nothing in the port scores "how much
signal is really under this edge" server-side (the EDS net/sigma/
significance/confidence vocabulary that answers that lives client-side in
frontend/src/lib/elemental/identify.ts, recomputed against a displayed
spectrum). Edge-jump detection needs the pre-edge power-law fit
``calc/eels.py`` already owns, so this computes the full thing server-side
instead — see calc/eels_identify.py for the edge-jump significance math.

Thin adapter: this module only converts the request/response shapes.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from fermiviewer.calc.eels_identify import (
    EDGE_FIT_GAP_EV,
    EDGE_FIT_WIDTH_EV,
    EDGE_SIGNAL_WIDTH_EV,
    identify_edges,
)
from fermiviewer.datastruct import DataKind, DataStruct
from fermiviewer.session import UnknownImageError, store

router = APIRouter(prefix="/api")


def _spectral(img_id: str) -> DataStruct:
    try:
        ds = store.get(img_id)
    except UnknownImageError:
        raise HTTPException(404, f"unknown image id: {img_id}") from None
    if ds.kind is DataKind.IMAGE:
        raise HTTPException(400, "image has no spectral axis")
    return ds


class EelsAutoAssignRequest(BaseModel):
    image_id: str
    fit_width_ev: float = EDGE_FIT_WIDTH_EV
    signal_width_ev: float = EDGE_SIGNAL_WIDTH_EV
    fit_gap_ev: float = EDGE_FIT_GAP_EV
    method: str = "powerlaw"          # "powerlaw" | "exponential"


@router.post("/eels/auto-assign")
def eels_auto_assign(req: EelsAutoAssignRequest) -> dict:
    """Edge-jump significance for every tabulated EELS_EDGES entry the
    cube's energy axis can support (#22 — the EELS analogue of
    ``/eds/auto-assign``).

    Unlike the EDS endpoint (peak detection only — a candidate LIST with no
    notion of signal strength), this scores every candidate edge directly
    against the sum spectrum, so the response already carries the
    net/sigma/significance/confidence vocabulary a caller would otherwise
    have to compute itself. Sorted by significance, strongest first, so the
    caller can pre-tick the top of the list the same way EDS auto-ID
    recommends everything but "trace".

    Response
    --------
    {
      "edges": [
        {"element": str, "edge": str, "symbol": str,   # "Fe-L23"
         "onset_ev": float,
         "fit_window": [lo, hi], "signal_window": [lo, hi],
         "net": float, "sigma": float, "significance": float,
         "confidence": "strong"|"clear"|"weak"|"trace"},
        ...
      ]
    }

    An empty list is a valid (200) answer — a narrow energy axis or a flat
    spectrum legitimately supports/shows no edges, not an error.
    """
    ds = _spectral(req.image_id)
    energy = ds.energy_axis                 # EELS axis is native eV
    spectrum = ds.sum_spectrum()
    try:
        results = identify_edges(
            energy, spectrum,
            fit_width_ev=req.fit_width_ev,
            signal_width_ev=req.signal_width_ev,
            fit_gap_ev=req.fit_gap_ev,
            method=req.method,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {
        "edges": [
            {
                "element": r.element,
                "edge": r.edge,
                "symbol": r.symbol,
                "onset_ev": r.onset_ev,
                "fit_window": list(r.fit_window),
                "signal_window": list(r.signal_window),
                "net": r.net,
                "sigma": r.sigma,
                "significance": r.significance,
                "confidence": r.confidence,
            }
            for r in results
        ]
    }
