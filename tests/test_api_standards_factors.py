"""Standards, derivation and comparison through the API (roadmap 5b).

The fixture is a synthetic SI cube whose Fe and Cr peak areas are in a
known ratio, so a factor derived from it has a value that can be checked
rather than merely observed to exist.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eds]

NY, NX, NE = 2, 2, 1200
SCALE = 0.02
ENERGY = np.arange(NE) * SCALE
FE = line_energy("Fe", beam_kv=200.0)[0]
CR = line_energy("Cr", beam_kv=200.0)[0]
#: per-pixel areas; the field total is NY*NX times these
FE_AREA, CR_AREA = 21000.0, 6000.0


def _peak(area: float, center: float) -> np.ndarray:
    sigma = fano_sigma_kev(center)
    return (area / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(
        -0.5 * ((ENERGY - center) / sigma) ** 2
    )


PIXEL = _peak(FE_AREA, FE) + _peak(CR_AREA, CR)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_STANDARDS_PATH", str(tmp_path / "standards.json"))
    monkeypatch.setenv("FV_FACTORS_PATH", str(tmp_path / "factors.json"))
    monkeypatch.setenv("FV_PROFILES_PATH", str(tmp_path / "profiles.json"))
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture()
def cube_id(client, tmp_path) -> str:
    arr = np.empty((NE, NY, NX))
    for y in range(NY):
        for x in range(NX):
            arr[:, y, x] = PIXEL
    f = write_mini_dm4(
        tmp_path / "std.dm4",
        dims=[NX, NY, NE],
        data=arr.ravel().astype(np.float32),
        data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": 0, "units": "keV"},
        ],
    )
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


def _standard(client, **over) -> dict:
    body = {
        "name": "FeCr 70/30",
        "basis": "wt",
        "composition": {"Fe": {"value": 70.0, "unit": "%", "sigma": 0.5}, "Cr": 30.0},
    }
    body.update(over)
    r = client.post("/api/standards", json=body)
    assert r.status_code == 200, r.text
    return r.json()["standard"]


# ── the standards store ───────────────────────────────────────────────


def test_create_and_list_a_standard(client) -> None:
    std = _standard(client)
    assert std["version"] == 1
    assert std["normalized_fractions"]["Fe"] == pytest.approx(0.7)
    listed = client.get("/api/standards").json()["standards"]
    assert [s["id"] for s in listed] == [std["id"]]


def test_a_basis_is_required(client) -> None:
    r = client.post(
        "/api/standards", json={"name": "x", "composition": {"Fe": 100.0}}
    )
    assert r.status_code == 422


def test_editing_a_standard_makes_a_new_version_and_keeps_the_old(client) -> None:
    """A factor set names the version it used, so a certificate correction
    must never rewrite what a published derivation was based on."""
    std = _standard(client)
    r = client.post(
        f"/api/standards/{std['id']}",
        json={"composition": {"Fe": 68.0, "Cr": 32.0}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["standard"]["version"] == 2
    history = client.get(f"/api/standards/{std['id']}/history").json()["versions"]
    assert [h["version"] for h in history] == [1, 2]
    assert history[0]["composition"]["Fe"]["value"] == 70.0


def test_reference_regions_replace_by_label(client, cube_id) -> None:
    std = _standard(client)
    for roi in ("1,1,2,2", "1,1,1,1"):
        r = client.post(
            f"/api/standards/{std['id']}/regions",
            json={"label": "matrix", "image_id": cube_id, "roi": roi},
        )
        assert r.status_code == 200, r.text
    regions = r.json()["standard"]["regions"]
    assert len(regions) == 1
    assert regions[0]["roi"] == "1,1,1,1"


def test_a_reference_region_survives_a_closed_session(client) -> None:
    """A standard outlives the session that measured it, so an image id is
    not checked at storage time — it is resolved when a derivation reads
    it, where the user can act on a stale one."""
    std = _standard(client)
    r = client.post(
        f"/api/standards/{std['id']}/regions",
        json={"label": "matrix", "image_id": "no-such-image", "roi": "1,1,2,2"},
    )
    assert r.status_code == 200, r.text


def test_removing_an_absent_region_is_a_404(client) -> None:
    std = _standard(client)
    r = client.delete(f"/api/standards/{std['id']}/regions/ghost")
    assert r.status_code == 404


# ── derivation ────────────────────────────────────────────────────────


def _derive(client, std_id, cube_id, **over) -> dict:
    body = {"standard_id": std_id, "image_id": cube_id, "elements": ["Fe", "Cr"]}
    body.update(over)
    r = client.post("/api/factors/derive", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_derived_k_matches_the_measured_ratio(client, cube_id) -> None:
    """``k_i = (w_i/I_i) / (w_ref/I_ref)``, worked through by hand.

    The weights are 70/30 and the intensities 21000/6000, which are NOT
    the same ratio (2.33 against 3.50) — so the factors are not both 1,
    and the difference is exactly what a derived factor absorbs::

        k_Fe = 1                       (the reference, by definition)
        k_Cr = (0.30/6000)/(0.70/21000) = 1.5
    """
    std = _standard(client)
    body = _derive(client, std["id"], cube_id)
    assert body["reference_element"] == "Fe"
    assert body["factors"]["Fe"]["value"] == pytest.approx(1.0)
    assert body["factors"]["Cr"]["value"] == pytest.approx(1.5, rel=0.02)


def test_derived_k_reflects_a_composition_that_disagrees_with_the_counts(
    client, cube_id
) -> None:
    """The whole point: when the true composition is NOT in the intensity
    ratio, the factor is what absorbs the difference."""
    std = _standard(client, composition={"Fe": 50.0, "Cr": 50.0})
    body = _derive(client, std["id"], cube_id)
    # w equal, I 3.5:1 -> k_Cr/k_Fe = (1/1)*(21000/6000) = 3.5
    assert body["factors"]["Cr"]["value"] == pytest.approx(3.5, rel=0.02)


def test_zeta_needs_a_certified_mass_thickness(client, cube_id) -> None:
    std = _standard(client)
    r = client.post(
        "/api/factors/derive",
        json={
            "standard_id": std["id"],
            "image_id": cube_id,
            "elements": ["Fe", "Cr"],
            "kind": "zeta",
        },
    )
    assert r.status_code == 422
    assert "mass-thickness" in r.json()["detail"]


def test_zeta_derivation_stores_its_conditions(client, cube_id) -> None:
    std = _standard(
        client, mass_thickness={"value": 3e-5, "unit": "kg/m2"}
    )
    body = _derive(
        client,
        std["id"],
        cube_id,
        kind="zeta",
        probe_current_na=1.0,
        live_time_s=100.0,
        store=True,
    )
    assert body["reference_element"] == ""
    fs = body["factor_set"]
    assert fs["kind"] == "zeta"
    assert fs["conditions"]["beam_kv"] == 200.0
    assert fs["derived_from"]["standard_id"] == std["id"]
    assert fs["derived_from"]["standard_version"] == 1


def test_a_stored_reference_region_can_be_named_instead_of_an_image(
    client, cube_id
) -> None:
    std = _standard(client)
    client.post(
        f"/api/standards/{std['id']}/regions",
        json={"label": "matrix", "image_id": cube_id},
    )
    r = client.post(
        "/api/factors/derive",
        json={
            "standard_id": std["id"],
            "region_label": "matrix",
            "elements": ["Fe", "Cr"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["factors"]["Fe"]["value"] == pytest.approx(1.0)


def test_a_stale_reference_region_fails_at_derivation(client) -> None:
    std = _standard(client)
    client.post(
        f"/api/standards/{std['id']}/regions",
        json={"label": "matrix", "image_id": "gone"},
    )
    r = client.post(
        "/api/factors/derive",
        json={"standard_id": std["id"], "region_label": "matrix", "elements": ["Fe"]},
    )
    assert r.status_code == 404


def test_deriving_for_an_element_the_standard_does_not_state(client, cube_id) -> None:
    std = _standard(client)
    r = client.post(
        "/api/factors/derive",
        json={"standard_id": std["id"], "image_id": cube_id, "elements": ["Fe", "Ni"]},
    )
    assert r.status_code == 422
    assert "Ni" in r.json()["detail"]


# ── comparison, replacing neither ─────────────────────────────────────


def test_compare_reports_both_and_replaces_neither(client, cube_id) -> None:
    std = _standard(client, composition={"Si": 50.0, "Fe": 50.0})
    # measured on the Fe/Cr cube, so the numbers are arbitrary; what is
    # under test is that BOTH sides come back with their own voltage.
    r = client.post(
        "/api/factors/derive",
        json={
            "standard_id": std["id"],
            "image_id": cube_id,
            "elements": ["Si", "Fe"],
            "store": True,
        },
    )
    assert r.status_code == 200, r.text
    fid = r.json()["factor_set"]["id"]
    cmp = client.get(f"/api/factors/{fid}/compare").json()
    assert cmp["comparable"] is True
    assert cmp["reference_element"] == "Si"
    assert cmp["builtin_kv"] == 200.0
    rows = {row["element"]: row for row in cmp["rows"]}
    assert rows["Fe"]["builtin_200kv"] == 1.21
    assert rows["Fe"]["measured"] is not None
    # the stored set is untouched by the comparison
    assert client.get(f"/api/factors/{fid}").json()["factor_set"]["factors"]["Fe"][
        "value"
    ] == pytest.approx(rows["Fe"]["measured"])


def test_zeta_has_no_builtin_to_compare_against(client, cube_id) -> None:
    std = _standard(client, mass_thickness={"value": 3e-5, "unit": "kg/m2"})
    body = _derive(client, std["id"], cube_id, kind="zeta", store=True)
    cmp = client.get(f"/api/factors/{body['factor_set']['id']}/compare").json()
    assert cmp["comparable"] is False
    assert "no ζ table" in cmp["reason"]


def test_transferring_a_zeta_set_scales_by_the_collected_signal(
    client, cube_id
) -> None:
    std = _standard(client, mass_thickness={"value": 3e-5, "unit": "kg/m2"})
    body = _derive(client, std["id"], cube_id, kind="zeta", store=True)
    fid = body["factor_set"]["id"]
    before = body["factor_set"]["factors"]["Fe"]["value"]
    r = client.post(
        f"/api/factors/{fid}/transfer",
        json={"from_solid_angle_sr": 0.2, "to_solid_angle_sr": 0.1},
    )
    assert r.status_code == 200, r.text
    assert r.json()["factors"]["Fe"]["value"] == pytest.approx(2.0 * before)


def test_a_k_set_has_no_geometry_to_transfer(client, cube_id) -> None:
    std = _standard(client)
    body = _derive(client, std["id"], cube_id, store=True)
    r = client.post(
        f"/api/factors/{body['factor_set']['id']}/transfer",
        json={"from_solid_angle_sr": 0.2, "to_solid_angle_sr": 0.1},
    )
    assert r.status_code == 422


# ── QC beside the composition ─────────────────────────────────────────


def test_quantify_reports_the_extrapolation_when_the_beam_is_not_200kv(
    client, cube_id
) -> None:
    """/eds/quantify always uses the built-in 200 kV table. At 80 kV that
    is an extrapolation the answer alone does not show."""
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": cube_id, "elements": ["Fe", "Cr"], "beam_kv": 80.0},
    )
    assert r.status_code == 200, r.text
    codes = {f["code"] for f in r.json()["qc"]}
    assert "factors_extrapolated" in codes


def test_quantify_is_quiet_about_extrapolation_at_200kv(client, cube_id) -> None:
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": cube_id, "elements": ["Fe", "Cr"], "beam_kv": 200.0},
    )
    assert "factors_extrapolated" not in {f["code"] for f in r.json()["qc"]}


def test_quantify_reports_a_defaulted_takeoff_angle(client, cube_id) -> None:
    r = client.post(
        "/api/eds/quantify", json={"image_id": cube_id, "elements": ["Fe", "Cr"]}
    )
    findings = {f["code"]: f for f in r.json()["qc"]}
    assert "parameters_defaulted" in findings
    assert "take_off_angle_deg" in findings["parameters_defaulted"]["message"]


def test_derivation_carries_its_own_qc(client, cube_id) -> None:
    std = _standard(client)
    body = _derive(client, std["id"], cube_id)
    assert isinstance(body["qc"], list)
    assert {"code", "severity", "message"} <= set(body["qc"][0]) if body["qc"] else True
