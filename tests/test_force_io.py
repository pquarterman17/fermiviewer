"""AFM force-curve readers (io/force*.py), the force store and routes."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import EXAMPLE_DATA_ROOT
from fermiviewer.io.force import force_kind, load_force
from fermiviewer.io.force_common import ForceCurve, ForceError, ForceSegment
from fermiviewer.io.nid import load_nid_all
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store
from fermiviewer.session_force import force_store
from fixtures.miniforce import write_bruker_force, write_ibw_force, write_nid_force

ALLOWED_HOSTS.add("testserver")


def _hertz_like(n: int = 400, zc: float = 150.0, top: float = 200.0):
    """Approach Z (nm) and a deflection rising past the contact."""
    z = np.linspace(0.0, top, n)
    d = 0.02 * np.clip(z - zc, 0, None) ** 1.5
    return z, d


@pytest.fixture()
def client():
    store.clear()
    force_store.clear()
    yield TestClient(create_app())
    store.clear()
    force_store.clear()


# ── model ──────────────────────────────────────────────────────────────

def test_z_is_oriented_toward_the_sample() -> None:
    z, d = _hertz_like()
    c = ForceCurve([ForceSegment("approach", -z, d), ForceSegment("retract", -z[::-1], d[::-1])])
    assert c.metadata["z_flipped"] and c.approach.z[-1] > c.approach.z[0]
    assert c.retract.z[0] > c.retract.z[-1]


def test_a_curve_needs_an_approach() -> None:
    z, d = _hertz_like()
    with pytest.raises(ForceError):
        ForceCurve([ForceSegment("retract", z, d)])


# ── readers ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sensor", [True, False])
def test_bruker_force(tmp_path: Path, sensor: bool) -> None:
    z, d = _hertz_like()
    f = write_bruker_force(tmp_path / "c.001", z, d, z[::-1], d[::-1], k=0.4, sensor=sensor)
    assert force_kind(f) == "only"
    ff = load_force(f)
    a = ff.curves[0].approach
    assert ff.parser == "nanoscope" and ff.spring_constant == 0.4 and ff.invols == 50.0
    assert ff.z_source == ("Z sensor" if sensor else "piezo ramp")
    np.testing.assert_allclose(a.deflection, d, atol=0.02)
    np.testing.assert_allclose(a.z - a.z[0], z, atol=0.2)
    assert ff.curves[0].retract.z[0] == pytest.approx(a.z[-1], abs=0.2)


def test_ibw_force_segments_and_calibration(tmp_path: Path) -> None:
    z, d = _hertz_like()
    f = write_ibw_force(tmp_path / "f.ibw", [(1, z, d), (-1, z[::-1], d[::-1]),
                                             (0, np.full(10, z[0]), np.zeros(10))],
                        k=0.07, invols_m=4e-8)
    assert force_kind(f) == "only"
    ff = load_force(f)
    c = ff.curves[0]
    assert [s.kind for s in c.segments] == ["approach", "retract", "dwell"]
    assert ff.spring_constant == pytest.approx(0.07) and ff.invols == pytest.approx(40.0)
    np.testing.assert_allclose(c.approach.deflection, d, atol=1e-3)
    assert c.approach.z.size == z.size


def test_ibw_images_are_not_force_curves(tmp_path: Path) -> None:
    from fixtures.minispm import write_ibw

    f = write_ibw(tmp_path / "img.ibw", {"HeightTrace": np.zeros((4, 4))}, 1e-8)
    assert force_kind(f) is None


def test_nid_force_map_order_and_images(tmp_path: Path) -> None:
    z, d = _hertz_like(200)
    # recorded serpentine on a 2 × 3 grid; the contact point marks the curve
    curves = [(z, 0.02 * np.clip(z - (100 + 10 * i), 0, None) ** 1.5) for i in range(6)]
    topo = np.arange(12.0).reshape(3, 4) * 1e-9
    f = write_nid_force(tmp_path / "m.nid", curves, k=2.0, grid=(2, 3), image=topo)
    assert force_kind(f) == "mixed"
    ff = load_force(f)
    assert ff.grid == (2, 3) and ff.map_pitch_nm == pytest.approx((100.0, 100.0))
    assert ff.spring_constant == 2.0 and ff.deflection_unit == "nm"
    # image row 0 is recorded line 1, right to left: curves 6, 5, 4
    assert [c.label for c in ff.curves] == [f"curve {i}" for i in (6, 5, 4, 1, 2, 3)]
    c = ff.curves[0]
    np.testing.assert_allclose(c.approach.deflection, curves[5][1], atol=1e-3)
    assert c.retract.z[0] == pytest.approx(c.approach.z[-1], abs=1e-3)
    # the image reader keeps the topography and skips the spectroscopy blocks
    (img,) = load_nid_all(f)
    np.testing.assert_allclose(img.data * 1e-9, topo, atol=1e-15)


def test_nid_without_spectroscopy_is_not_force(tmp_path: Path) -> None:
    from fixtures.minispm import write_nid

    f = write_nid(tmp_path / "i.nid", [("Z-Axis", "m", np.zeros((4, 4), np.int32))],
                  1e-6, 0.0, 1e-6)
    assert force_kind(f) is None and force_kind(tmp_path / "missing.nid") is None


# ── corpus ─────────────────────────────────────────────────────────────

_CORPUS = {
    "bruker/afm/pycroscopy_BrukerReader_ForceCurve_Sapphire_TAP525.001": ("nanoscope", 1),
    "asylum/afm/pycroscopy_IgorIBWReader_ForceCurve.ibw": ("asylum", 1),
    "nanosurf/afm/nsfopen_spectroscopy.nid": ("nanosurf", 100),
}


@pytest.mark.parametrize("rel", list(_CORPUS))
def test_corpus_force_files(rel: str) -> None:
    path = EXAMPLE_DATA_ROOT / rel
    if not path.exists():
        pytest.skip("force-curve corpus not present")
    ff = load_force(path)
    parser, n = _CORPUS[rel]
    assert ff.parser == parser and len(ff.curves) == n and ff.spring_constant > 0
    for c in ff.curves[:3]:
        a = c.approach
        assert a.z[-1] > a.z[0] and c.retract is not None
    if parser == "nanosurf":
        assert ff.grid == (10, 10) and ff.map_pitch_nm == pytest.approx((500.0, 500.0))
    if parser == "nanoscope":
        # the Height Sensor spans the 600 nm ramp (16.72 V × 35.88 nm/V)
        assert np.ptp(ff.curves[0].approach.z) == pytest.approx(592.3, abs=0.5)


# ── routes ─────────────────────────────────────────────────────────────

def _open(client: TestClient, path: Path) -> list[dict]:
    r = client.post("/api/session/open", json={"paths": [str(path)]})
    assert r.status_code == 200, r.text
    return r.json()


def test_open_analyze_and_close(client, tmp_path: Path) -> None:
    z, d = _hertz_like()
    f = write_ibw_force(tmp_path / "f.ibw", [(1, z, d), (-1, z[::-1], d[::-1])], k=0.1)
    (meta,) = _open(client, f)
    assert meta["is_force"] and meta["n_curves"] == 1 and meta["invols"] == pytest.approx(50)
    fid = meta["id"]
    assert [m["id"] for m in client.get("/api/afm/force").json()] == [fid]
    raw = client.get(f"/api/afm/force/{fid}/curve/0").json()
    assert [s["kind"] for s in raw["segments"]] == ["approach", "retract"]
    r = client.post(f"/api/afm/force/{fid}/curve/0/analyze",
                    json={"tip": "sphere", "radius_nm": 20, "poisson": 0.5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["values"]["contact_z"] == pytest.approx(150.0, abs=2.0)
    assert body["units"]["youngs_modulus"] == "Pa" and body["fit"] is not None
    assert set(body["plot"]) == {"approach", "retract"}
    # a new InvOLS rescales the nm deflection by new / file
    r2 = client.post(f"/api/afm/force/{fid}/curve/0/analyze", json={"invols": 100}).json()
    assert r2["values"]["max_force"] == pytest.approx(2 * body["values"]["max_force"], rel=1e-6)
    assert client.get(f"/api/afm/force/{fid}/curve/5").status_code == 404
    assert client.delete(f"/api/afm/force/{fid}").status_code == 200
    assert client.get(f"/api/afm/force/{fid}").status_code == 404


def test_settings_are_validated(client, tmp_path: Path) -> None:
    z, d = _hertz_like()
    f = write_nid_force(tmp_path / "s.nid", [(z, d)], k=1.0)
    (meta,) = _open(client, f)
    url = f"/api/afm/force/{meta['id']}/curve/0/analyze"
    assert client.post(url, json={"poisson": 0.7}).status_code == 422
    assert client.post(url, json={"baseline_from": 0.6, "baseline_to": 0.5}).status_code == 422
    # Nanosurf gives nm without an InvOLS: a new one cannot be applied
    assert client.post(url, json={"invols": 80}).status_code == 422


def test_force_map_images(client, tmp_path: Path) -> None:
    z, _ = _hertz_like(200)
    curves = [(z, 0.02 * np.clip(z - (100 + 10 * i), 0, None) ** 1.5) for i in range(6)]
    f = write_nid_force(tmp_path / "m.nid", curves, k=2.0, grid=(2, 3),
                        image=np.zeros((3, 4)))
    metas = _open(client, f)
    force = next(m for m in metas if m.get("is_force"))
    assert any(not m.get("is_force") for m in metas)          # the topography too
    url = f"/api/afm/force/{force['id']}/maps"
    fitted = client.post(url, json={"radius_nm": 20}).json()
    assert fitted["n"] == 6 and fitted["failed"] == 0
    assert all(v is not None and v > 0 for v in fitted["table"]["youngs_modulus"])
    names = [m["name"] for m in fitted["images"]]
    assert names[0].startswith("Young's modulus") and len(names) == 3
    # without the fit the contact is the zero crossing, exact on these curves
    body = client.post(url, json={"fit": False}).json()
    height = store.get(body["images"][2]["id"])
    # contact 10 nm later per recorded curve → lower surface; image row 1 = line 0
    np.testing.assert_allclose(height.data[1], [50, 40, 30], atol=0.6)
    np.testing.assert_allclose(height.data[0], [0, 10, 20], atol=0.6)
    assert height.metadata["value_unit"] == "nm" and height.axes[1].scale == 100.0


def test_upload_routes_force_files(client, tmp_path: Path) -> None:
    z, d = _hertz_like()
    f = write_bruker_force(tmp_path / "u.001", z, d, z[::-1], d[::-1])
    with f.open("rb") as fh:
        r = client.post("/api/session/upload",
                        files=[("files", ("u.001", fh, "application/octet-stream"))])
    assert r.status_code == 200, r.text
    (meta,) = r.json()
    assert meta["is_force"] and meta["parser"] == "nanoscope"


def test_upload_of_a_force_map_returns_its_image(client, tmp_path: Path) -> None:
    z, d = _hertz_like()
    f = write_nid_force(tmp_path / "m.nid", [(z, d)] * 4, k=1.0, grid=(2, 2),
                        image=np.zeros((3, 3)))
    with f.open("rb") as fh:
        r = client.post("/api/session/upload",
                        files=[("files", ("m.nid", fh, "application/octet-stream"))])
    (meta,) = r.json()                     # one meta per uploaded file
    assert "is_force" not in meta
    (force,) = client.get("/api/afm/force").json()
    assert force["grid"] == [2, 2] and force["name"] == "m.nid"
