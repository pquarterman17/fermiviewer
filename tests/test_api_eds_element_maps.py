"""Batch /eds/element-maps endpoint (SPECTRAL_WORKSPACE_PLAN #8).

The cube is built with SPATIAL structure — Fe on the left half, Cu on the
right — because a spatially-uniform cube cannot tell "resolved the correct
window per element" apart from "applied one window to every element and
returned N copies of the same raster", which is the failure a batch endpoint
is actually prone to.

Peak positions come from `calc.eds.line_energy`, never a transcribed copy,
so the planted peaks cannot drift away from the windows the endpoint snaps
to.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api

NY, NX, NE = 4, 6, 512
SPLIT = 3                      # cols [0, SPLIT) are Fe, [SPLIT, NX) are Cu
FE_KEV, _ = line_energy("Fe")  # from the app's own table, not transcribed
CU_KEV, _ = line_energy("Cu")


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def two_element_cube(client, tmp_path) -> str:
    """4×6 px × 512 ch EDS cube: Fe peak on the left, Cu peak on the right."""
    e = np.arange(NE) * 0.02                     # 0–10.22 keV
    def gauss(centre: float) -> np.ndarray:
        return 60 * np.exp(-((e - centre) ** 2) / (2 * 0.05**2))

    cube = np.full((NY, NX, NE), 2.0, dtype=np.float32)   # flat background
    cube[:, :SPLIT, :] += gauss(FE_KEV).astype(np.float32)
    cube[:, SPLIT:, :] += gauss(CU_KEV).astype(np.float32)
    # file order is d0 (x) fastest, E slowest
    flat = np.transpose(cube, (2, 0, 1)).ravel()
    f = write_mini_dm4(
        tmp_path / "eds2.dm4", dims=[NX, NY, NE], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 0.02, "origin": 0, "units": "keV"},
        ],
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def _post(client: TestClient, **kw) -> dict:
    r = client.post("/api/eds/element-maps", json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def test_batch_returns_one_localized_map_per_element(client, two_element_cube):
    """The deliverable: N species in, N distinct rasters out, each bright
    where its element actually is — with no quantification involved."""
    body = _post(client, image_id=two_element_cube, elements=["Fe", "Cu"])
    assert body["shape"] == [NY, NX]
    assert [m["symbol"] for m in body["maps"]] == ["Fe", "Cu"]
    assert [m["line"] for m in body["maps"]] == ["K", "K"]
    assert body["maps"][0]["energy_kev"] == pytest.approx(FE_KEV)
    assert body["maps"][1]["energy_kev"] == pytest.approx(CU_KEV)

    fe = np.array(body["maps"][0]["map"])
    cu = np.array(body["maps"][1]["map"])
    assert fe.shape == (NY, NX) and cu.shape == (NY, NX)
    # Each map localizes on its own half — this is what a shared window would
    # break, by making the two rasters identical.
    assert fe[:, :SPLIT].mean() > 10 * max(fe[:, SPLIT:].mean(), 1e-9)
    assert cu[:, SPLIT:].mean() > 10 * max(cu[:, :SPLIT].mean(), 1e-9)
    assert not np.allclose(fe, cu)


def test_unmappable_species_keeps_its_row_with_a_reason(client, two_element_cube):
    """The one behaviour NOT inherited from extract_element_maps: a species
    the user picked by hand is never silently dropped."""
    body = _post(client, image_id=two_element_cube, elements=["Fe", "Xx", "Cu"])
    assert [m["symbol"] for m in body["maps"]] == ["Fe", "Xx", "Cu"]   # order held
    bad = body["maps"][1]
    assert bad["map"] is None and bad["window"] is None
    assert "no known line for 'Xx'" in bad["error"]
    # the good rows either side are unaffected
    assert body["maps"][0]["map"] is not None and body["maps"][0]["error"] is None
    assert body["maps"][2]["map"] is not None and body["maps"][2]["error"] is None


def test_beam_kv_selects_the_usable_line(client, two_element_cube):
    """Mo K (17.5 keV) is off this 0–10.2 keV axis, so it reports a reason;
    at 20 kV the overvoltage rule drops to Mo L (2.29 keV) and it maps."""
    off = _post(client, image_id=two_element_cube, elements=["Mo"])["maps"][0]
    assert off["map"] is None
    assert "outside the energy axis" in off["error"]

    on = _post(client, image_id=two_element_cube,
               elements=["Mo"], beam_kv=20)["maps"][0]
    assert on["error"] is None and on["line"] == "L"
    assert on["energy_kev"] == pytest.approx(line_energy("Mo", beam_kv=20)[0])


def test_window_override_is_honoured_not_recomputed(client, two_element_cube):
    """The whole point of the override: the species list sends the window the
    user tuned, and the endpoint integrates THAT, not the default."""
    default = _post(client, image_id=two_element_cube,
                    elements=["Fe"])["maps"][0]
    # a background-only window well away from any planted peak
    shifted = _post(client, image_id=two_element_cube,
                    elements=[{"symbol": "Fe", "e_lo": 3.0, "e_hi": 3.2}])["maps"][0]
    assert shifted["window"] == [3.0, 3.2]
    assert shifted["total_counts"] < 0.1 * default["total_counts"]
    # the label still reports the line the symbol would have used
    assert shifted["line"] == "K"


def test_half_specified_override_is_rejected_per_row(client, two_element_cube):
    body = _post(client, image_id=two_element_cube,
                 elements=[{"symbol": "Fe", "e_lo": 3.0}])
    assert body["maps"][0]["map"] is None
    assert "both e_lo and e_hi" in body["maps"][0]["error"]


def test_override_makes_an_unknown_symbol_usable(client, two_element_cube):
    """With an explicit window the line table is not consulted for the map,
    so a non-element label still integrates — energy_kev is just null."""
    body = _post(client, image_id=two_element_cube,
                 elements=[{"symbol": "Xx", "e_lo": 6.3, "e_hi": 6.5}])
    row = body["maps"][0]
    assert row["error"] is None and row["energy_kev"] is None
    assert np.array(row["map"]).shape == (NY, NX)


def test_save_derived_registers_every_requested_map(client, two_element_cube):
    body = _post(client, image_id=two_element_cube,
                 elements=["Fe", "Cu"], save_derived=True)
    metas = [m["map_meta"] for m in body["maps"]]
    assert all(m is not None for m in metas)
    ids = {m["id"] for m in metas}
    assert len(ids) == 2
    listed = {i["id"] for i in client.get("/api/session/images").json()}
    assert ids <= listed

    # default is inline-only — nothing new lands in the library
    before = len(client.get("/api/session/images").json())
    _post(client, image_id=two_element_cube, elements=["Fe"])
    assert len(client.get("/api/session/images").json()) == before


def test_empty_and_unknown_inputs(client, two_element_cube):
    assert client.post("/api/eds/element-maps", json={
        "image_id": two_element_cube, "elements": [],
    }).status_code == 422
    assert client.post("/api/eds/element-maps", json={
        "image_id": "nope", "elements": ["Fe"],
    }).status_code == 404


def test_all_species_failing_is_still_200(client, two_element_cube):
    """A wholly-failed list renders through the same path as a partly-failed
    one — the caller should not need a second branch for it."""
    body = _post(client, image_id=two_element_cube, elements=["Xx", "Zz"])
    assert len(body["maps"]) == 2
    assert all(m["map"] is None and m["error"] for m in body["maps"])
