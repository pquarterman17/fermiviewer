"""/eels/auto-assign endpoint (SPECTRAL_WORKSPACE_PLAN #22).

EDS gets its element list for free via ``/eds/auto-assign``; this is the
EELS analogue, scored server-side against ``calc.eels_identify``. The cube
plants two known edges (from ``calc.eels.EELS_EDGES``, never a transcribed
onset) and the test asserts the planted edges come back with high
confidence while an absent-but-in-range edge does not — the same
"known-answer" shape used across this repo's synthetic fixtures.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eels import EELS_EDGES
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api

NE = 400
SCALE, OFFSET = 2.0, 300.0       # eV/ch, eV — matches tests/test_ops_spectral.py


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


O_EDGE = _edge("O", "K")          # 532 eV
FE_EDGE = _edge("Fe", "L23")      # 708 eV


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def _open_spectrum(client: TestClient, tmp_path, ny: int = 1, nx: int = 1) -> str:
    """A single-pixel (or tiled) EELS SI with O K + Fe L23 edges planted
    over a power-law background, no noise."""
    energy = OFFSET + SCALE * np.arange(NE)
    background = 8000.0 * (energy / energy[0]) ** -3.0
    spectrum = (
        background
        + 4000.0 * (energy >= O_EDGE.onset_ev)
        + 2500.0 * (energy >= FE_EDGE.onset_ev)
    ).astype(np.float32)
    cube = np.tile(spectrum, (ny, nx, 1))
    flat = np.transpose(cube, (2, 0, 1)).ravel()
    f = write_mini_dm4(
        tmp_path / "eels_id.dm4", dims=[nx, ny, NE], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": -OFFSET / SCALE, "units": "eV"},
        ],
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_auto_assign_recovers_planted_edges(client, tmp_path):
    img_id = _open_spectrum(client, tmp_path, ny=3, nx=2)
    r = client.post("/api/eels/auto-assign", json={"image_id": img_id})
    assert r.status_code == 200, r.text
    body = r.json()
    by_symbol = {e["symbol"]: e for e in body["edges"]}

    assert by_symbol["O-K"]["confidence"] in ("strong", "clear")
    assert by_symbol["Fe-L23"]["confidence"] in ("strong", "clear")
    assert by_symbol["O-K"]["onset_ev"] == O_EDGE.onset_ev
    assert by_symbol["Fe-L23"]["onset_ev"] == FE_EDGE.onset_ev
    assert by_symbol["O-K"]["element"] == "O" and by_symbol["O-K"]["edge"] == "K"

    # an in-range but unplanted edge must not read as confidently present
    assert "N-K" in by_symbol
    assert by_symbol["N-K"]["confidence"] in ("weak", "trace")

    # sorted by significance, strongest first
    sigs = [e["significance"] for e in body["edges"]]
    assert sigs == sorted(sigs, reverse=True)


def test_auto_assign_response_shape(client, tmp_path):
    img_id = _open_spectrum(client, tmp_path)
    body = client.post(
        "/api/eels/auto-assign", json={"image_id": img_id}
    ).json()
    assert body["edges"], "expected at least one candidate edge"
    row = body["edges"][0]
    for key in (
        "element", "edge", "symbol", "onset_ev", "fit_window",
        "signal_window", "net", "sigma", "significance", "confidence",
    ):
        assert key in row
    assert row["confidence"] in ("strong", "clear", "weak", "trace")
    assert len(row["fit_window"]) == 2
    assert len(row["signal_window"]) == 2


def test_auto_assign_unknown_image_id(client):
    r = client.post("/api/eels/auto-assign", json={"image_id": "nope"})
    assert r.status_code == 404


def test_auto_assign_rejects_a_plain_image(client, tmp_path):
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[4, 3], data=np.zeros(12, dtype=np.uint16),
        data_type=10,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    r = client.post("/api/eels/auto-assign", json={"image_id": img_id})
    assert r.status_code == 400


def test_auto_assign_empty_result_on_a_narrow_axis(client, tmp_path):
    """A cube whose axis is too narrow to fit even one edge's fit+signal
    windows returns an empty (still 200) list, not an error."""
    ny, nx, ne = 1, 1, 20
    # axis: 1.0-4.8 eV (offset -5.0 / scale 0.2) — far below any tabulated edge
    spectrum = np.full(ne, 10.0, dtype=np.float32)
    cube = np.tile(spectrum, (ny, nx, 1))
    flat = np.transpose(cube, (2, 0, 1)).ravel()
    f = write_mini_dm4(
        tmp_path / "narrow.dm4", dims=[nx, ny, ne], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.2, "origin": -5.0, "units": "eV"},
        ],
    )
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    r = client.post("/api/eels/auto-assign", json={"image_id": img_id})
    assert r.status_code == 200
    assert r.json()["edges"] == []
