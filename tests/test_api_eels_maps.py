"""Batch /eels/maps endpoint (SPECTRAL_WORKSPACE_PLAN #14).

The cube is built with SPATIAL structure — an O K edge on the top rows, an
Fe L23 edge on the bottom rows — because a spatially-uniform cube cannot
distinguish "resolved the correct window per species" from "applied one
window to every species and returned N copies of the same raster", which is
the failure a batch endpoint is actually prone to (mirrors
tests/test_api_eds_element_maps.py's two-element-cube approach).

Onset energies come from ``calc.eels.EELS_EDGES``, never a transcribed
number, so the planted jumps cannot drift from the table the frontend's
species list would snap to.
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

NY, NX, NE = 6, 4, 400
SPLIT = 3                        # rows [0, SPLIT) are O K, [SPLIT, NY) are Fe L23
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


@pytest.fixture()
def two_edge_cube(client, tmp_path) -> str:
    """6x4 px x 400 ch EELS SI: O K edge on top rows, Fe L23 on bottom rows,
    over a shared power-law background."""
    energy = OFFSET + SCALE * np.arange(NE)
    background = 8000.0 * (energy / energy[0]) ** -3.0
    o_jump = 4000.0 * (energy >= O_EDGE.onset_ev)
    fe_jump = 2500.0 * (energy >= FE_EDGE.onset_ev)

    cube = np.empty((NY, NX, NE), dtype=np.float32)
    cube[:SPLIT] = (background + o_jump).astype(np.float32)
    cube[SPLIT:] = (background + fe_jump).astype(np.float32)

    # file order is d0 (x) fastest, E slowest
    flat = np.transpose(cube, (2, 0, 1)).ravel()
    f = write_mini_dm4(
        tmp_path / "eels2.dm4", dims=[NX, NY, NE], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": -OFFSET / SCALE, "units": "eV"},
        ],
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def _post(client: TestClient, **kw) -> dict:
    r = client.post("/api/eels/maps", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_batch_returns_one_localized_map_per_species(client, two_edge_cube):
    """The deliverable: N species in, N distinct rasters out, each bright
    where its edge's jump actually is — with no quantification involved."""
    body = _post(
        client, image_id=two_edge_cube,
        species=[
            {"label": "O-K", "signal": {"lo": 532, "hi": 572},
             "background": {"lo": 462, "hi": 512}},
            {"label": "Fe-L23", "signal": {"lo": 708, "hi": 748},
             "background": {"lo": 638, "hi": 688}},
        ],
    )
    assert body["shape"] == [NY, NX]
    assert [m["label"] for m in body["maps"]] == ["O-K", "Fe-L23"]

    o_map = np.array(body["maps"][0]["map"])
    fe_map = np.array(body["maps"][1]["map"])
    assert o_map.shape == (NY, NX) and fe_map.shape == (NY, NX)
    # Each map localizes on its own rows — a shared window would make the
    # two rasters identical (the mutation this endpoint must not exhibit).
    assert o_map[:SPLIT].mean() > 10 * max(o_map[SPLIT:].mean(), 1e-9)
    assert fe_map[SPLIT:].mean() > 10 * max(fe_map[:SPLIT].mean(), 1e-9)
    assert not np.allclose(o_map, fe_map)
    for m in body["maps"]:
        assert m["error"] is None
        assert m["total_counts"] > 0


def test_species_without_background_is_a_direct_window_sum(client, two_edge_cube):
    body = _post(
        client, image_id=two_edge_cube,
        species=[{"label": "O-K", "signal": {"lo": 532, "hi": 572}}],
    )
    row = body["maps"][0]
    assert row["error"] is None
    assert row["background_window"] is None
    assert np.array(row["map"]).sum() > 0


def test_out_of_axis_window_keeps_its_row_with_a_reason(client, two_edge_cube):
    """The one behaviour this endpoint must not do: silently drop a species
    the user asked for by name."""
    body = _post(
        client, image_id=two_edge_cube,
        species=[
            {"label": "O-K", "signal": {"lo": 532, "hi": 572}},
            {"label": "way-off", "signal": {"lo": 5000, "hi": 5100}},
            {"label": "Fe-L23", "signal": {"lo": 708, "hi": 748}},
        ],
    )
    assert [m["label"] for m in body["maps"]] == ["O-K", "way-off", "Fe-L23"]
    bad = body["maps"][1]
    assert bad["map"] is None and bad["signal_window"] is None
    assert "outside the energy axis" in bad["error"]
    # the good rows either side are unaffected
    assert body["maps"][0]["map"] is not None and body["maps"][0]["error"] is None
    assert body["maps"][2]["map"] is not None and body["maps"][2]["error"] is None


def test_out_of_axis_background_window_keeps_its_row_with_a_reason(
    client, two_edge_cube
):
    body = _post(
        client, image_id=two_edge_cube,
        species=[{"label": "O-K", "signal": {"lo": 532, "hi": 572},
                 "background": {"lo": -500, "hi": -400}}],
    )
    row = body["maps"][0]
    assert row["map"] is None
    assert "background window" in row["error"]
    assert "outside the energy axis" in row["error"]


def test_degenerate_background_fit_window_keeps_its_row_with_a_reason(
    client, two_edge_cube
):
    """A background window narrower than 2 channels is a calc-layer
    ValueError (< 2 channels for the fit) — must land in the row's error,
    not bubble up as a 422 for the whole batch."""
    body = _post(
        client, image_id=two_edge_cube,
        species=[{"label": "O-K", "signal": {"lo": 532, "hi": 572},
                 "background": {"lo": 461.0, "hi": 461.5}}],
    )
    row = body["maps"][0]
    assert row["map"] is None
    assert row["error"] is not None


def test_save_derived_registers_every_requested_map(client, two_edge_cube):
    body = _post(
        client, image_id=two_edge_cube,
        species=[
            {"label": "O-K", "signal": {"lo": 532, "hi": 572}},
            {"label": "Fe-L23", "signal": {"lo": 708, "hi": 748}},
        ],
        save_derived=True,
    )
    metas = [m["map_meta"] for m in body["maps"]]
    assert all(m is not None for m in metas)
    ids = {m["id"] for m in metas}
    assert len(ids) == 2
    listed = {i["id"] for i in client.get("/api/session/images").json()}
    assert ids <= listed

    # default is inline-only — nothing new lands in the library
    before = len(client.get("/api/session/images").json())
    _post(client, image_id=two_edge_cube,
         species=[{"label": "O-K", "signal": {"lo": 532, "hi": 572}}])
    assert len(client.get("/api/session/images").json()) == before


def test_empty_and_unknown_inputs(client, two_edge_cube):
    assert client.post("/api/eels/maps", json={
        "image_id": two_edge_cube, "species": [],
    }).status_code == 422
    assert client.post("/api/eels/maps", json={
        "image_id": "nope", "species": [{"label": "x", "signal": {"lo": 0, "hi": 1}}],
    }).status_code == 404


def test_all_species_failing_is_still_200(client, two_edge_cube):
    body = _post(
        client, image_id=two_edge_cube,
        species=[
            {"label": "way-off-1", "signal": {"lo": 5000, "hi": 5100}},
            {"label": "way-off-2", "signal": {"lo": 6000, "hi": 6100}},
        ],
    )
    assert len(body["maps"]) == 2
    assert all(m["map"] is None and m["error"] for m in body["maps"])


def test_rejects_a_plain_image(client, tmp_path):
    """A 2D image (no spectral axis) is not a valid /eels/maps target."""
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[4, 3], data=np.zeros(12, dtype=np.uint16),
        data_type=10,
        cal=[{"scale": 1, "origin": 0, "units": "nm"},
             {"scale": 1, "origin": 0, "units": "nm"}],
    )
    client_ = TestClient(create_app(), base_url="http://127.0.0.1")
    img_id = client_.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    r = client_.post("/api/eels/maps", json={
        "image_id": img_id, "species": [{"label": "x", "signal": {"lo": 0, "hi": 1}}],
    })
    assert r.status_code == 400
