"""EDS endpoints reading an applied calibration profile (ADR 0010).

Through the API, because the claim is about a REQUEST: what the caller
did not state, the image's profiles supply, and the response says so.
The pure-layer rules are pinned in `test_profile_consumption.py`; what
these add is that each wired route actually reaches the resolver, and
that a profile value is subject to the same bounds a typed one is.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.eds import line_energy
from fermiviewer.calc.eds_calib import fano_sigma_kev
from fermiviewer.calc.eds_continuum import kramers_continuum
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.eds]

NY, NX, NE = 2, 3, 1000
SCALE = 0.02
ENERGY = np.arange(NE) * SCALE
FE = line_energy("Fe", beam_kv=200.0)[0]
CU = line_energy("Cu", beam_kv=200.0)[0]


def _peak(area: float, center: float) -> np.ndarray:
    sigma = fano_sigma_kev(center)
    return (area / (sigma * np.sqrt(2.0 * np.pi))) * np.exp(
        -0.5 * ((ENERGY - center) / sigma) ** 2
    )


PIXEL = kramers_continuum(ENERGY, 18.0, amp=300.0) + _peak(4000.0, FE) + _peak(6000.0, CU)


@pytest.fixture(autouse=True)
def _clean(tmp_path, monkeypatch):
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
        tmp_path / "eds.dm4",
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


def _apply(client, image_id: str, kind: str, fields: dict) -> str:
    """Create a profile and apply it to the image, as the UI does."""
    r = client.post(
        "/api/profiles",
        json={"name": f"{kind} under test", "kind": kind, "fields": fields},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["profile"]["id"]
    r = client.post("/api/profiles/apply", json={"image_id": image_id, "profile_id": pid})
    assert r.status_code == 200, r.text
    return pid


# ── /eds/zeta ─────────────────────────────────────────────────────────


def _zeta(client, cube_id, **over) -> dict:
    body = {"image_id": cube_id, "elements": ["Fe", "Cu"], "zeta_si": 1000.0}
    body.update(over)
    r = client.post("/api/eds/zeta", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_zeta_falls_back_to_route_defaults_with_no_profile(client, cube_id) -> None:
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["probe_current_na"] == {"value": 1.0, "unit": "nA", "origin": "default"}
    assert cal["live_time_s"]["origin"] == "default"
    assert cal["beam_kv"]["value"] == 200.0


def test_zeta_reads_probe_current_converting_pa_to_na(client, cube_id) -> None:
    """The conversion that matters: the store keeps picoamps, the dose
    integral takes nanoamps. Reading 500 pA as 500 nA is a 1000x error in
    the dose and so in the mass-thickness."""
    _apply(client, cube_id, "acquisition", {"probe_current": {"value": 500.0, "unit": "pA"}})
    body = _zeta(client, cube_id)
    assert body["calibration"]["probe_current_na"]["value"] == pytest.approx(0.5)
    assert body["calibration"]["probe_current_na"]["origin"] == "profile"
    # and it reached the physics, not just the report
    assert body["quant"]["dose_electrons"] == pytest.approx(
        0.5e-9 * 100.0 / 1.602176634e-19, rel=1e-9
    )


def test_zeta_request_value_beats_the_profile(client, cube_id) -> None:
    _apply(client, cube_id, "acquisition", {"probe_current": {"value": 500.0, "unit": "pA"}})
    cal = _zeta(client, cube_id, probe_current_na=4.0)["calibration"]
    assert cal["probe_current_na"] == {"value": 4.0, "unit": "nA", "origin": "request"}


def test_zeta_derives_live_time_from_real_and_dead_time(client, cube_id) -> None:
    """A detector reports wall-clock time and a dead-time percentage; live
    time is what the dose needs. A profile carrying that pair is not
    missing the parameter."""
    _apply(
        client,
        cube_id,
        "acquisition",
        {
            "real_time": {"value": 50.0, "unit": "s"},
            "dead_time": {"value": 30.0, "unit": "%"},
        },
    )
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["live_time_s"]["value"] == pytest.approx(35.0)
    assert cal["live_time_s"]["field"] == "acquisition.real_time x (1 - acquisition.dead_time)"


def test_zeta_prefers_a_stated_live_time_over_the_derivation(client, cube_id) -> None:
    _apply(
        client,
        cube_id,
        "acquisition",
        {
            "live_time_s": {"value": 1.0, "unit": "s"},  # unknown field, ignored
            "live_time": {"value": 12.0, "unit": "s"},
            "real_time": {"value": 50.0, "unit": "s"},
            "dead_time": {"value": 30.0, "unit": "%"},
        },
    )
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["live_time_s"]["value"] == pytest.approx(12.0)
    assert cal["live_time_s"]["field"] == "acquisition.live_time"


def test_zeta_reads_beam_energy_as_kv(client, cube_id) -> None:
    """keV -> kV by the electron equivalence, named at the call site."""
    _apply(client, cube_id, "acquisition", {"beam_energy": {"value": 80.0, "unit": "keV"}})
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["beam_kv"]["value"] == pytest.approx(80.0)
    assert cal["beam_kv"]["field"] == "acquisition.beam_energy"


def test_acquisition_beam_energy_wins_over_the_microscope(client, cube_id) -> None:
    """The microscope profile describes an instrument that runs at several
    voltages; the acquisition profile describes this session."""
    _apply(client, cube_id, "microscope", {"accelerating_voltage": {"value": 300.0, "unit": "kV"}})
    _apply(client, cube_id, "acquisition", {"beam_energy": {"value": 80.0, "unit": "keV"}})
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["beam_kv"]["field"] == "acquisition.beam_energy"
    assert cal["beam_kv"]["value"] == pytest.approx(80.0)


def test_microscope_voltage_used_when_no_acquisition_profile(client, cube_id) -> None:
    _apply(client, cube_id, "microscope", {"accelerating_voltage": {"value": 300.0, "unit": "kV"}})
    cal = _zeta(client, cube_id)["calibration"]
    assert cal["beam_kv"]["field"] == "microscope.accelerating_voltage"
    assert cal["beam_kv"]["value"] == pytest.approx(300.0)


# ── the bounds a profile would otherwise bypass ───────────────────────


def test_a_typed_takeoff_angle_out_of_range_is_refused(client, cube_id) -> None:
    """Pydantic's own guard — the baseline the profile path must match."""
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": cube_id, "elements": ["Fe", "Cu"], "take_off_angle_deg": 120.0},
    )
    assert r.status_code == 422


def test_a_profile_takeoff_angle_out_of_range_is_refused_too(client, cube_id) -> None:
    """A profile value never passes through pydantic. Without the check on
    the RESOLVED value, a stored 120 deg would reach `zaf_correction`
    while a typed 120 is rejected — the guard would cover only the input
    path nobody gets wrong."""
    _apply(client, cube_id, "detector", {"takeoff_angle": {"value": 120.0, "unit": "deg"}})
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": cube_id, "elements": ["Fe", "Cu"], "method": "zaf"},
    )
    assert r.status_code == 422
    assert "detector.takeoff_angle" in r.json()["detail"]


def test_an_unreadable_unit_stops_the_request(client, cube_id) -> None:
    """Not a silent fall through to the built-in default: answering with 20
    deg because the applied profile said something unreadable hides the
    one thing the user needs to know."""
    pid = _apply(client, cube_id, "detector", {"takeoff_angle": {"value": 35.0, "unit": "deg"}})
    ds = store.get(cube_id)
    ds.metadata["profiles"]["detector"]["fields"]["takeoff_angle"] = {
        "value": 35.0,
        "unit": "furlong",
    }
    r = client.post(
        "/api/eds/quantify",
        json={"image_id": cube_id, "elements": ["Fe", "Cu"], "method": "zaf"},
    )
    assert r.status_code == 422
    assert "unknown unit" in r.json()["detail"]
    assert pid  # the profile was really applied


# ── /eds/quantify records what it used ────────────────────────────────


def test_recorded_params_carry_the_resolved_value_not_null(client, cube_id) -> None:
    """The record is a reproduction key. Recording `null` for a parameter
    the caller left unstated would make a re-run after editing the
    profile silently produce different numbers."""
    _apply(client, cube_id, "detector", {"takeoff_angle": {"value": 35.0, "unit": "deg"}})
    r = client.post(
        "/api/eds/quantify",
        json={
            "image_id": cube_id,
            "elements": ["Fe", "Cu"],
            "method": "zaf",
            "record": True,
        },
    )
    assert r.status_code == 200, r.text
    rid = r.json()["result"]["id"]
    rec = client.get(f"/api/results/{rid}").json()
    assert rec["params"]["take_off_angle_deg"] == pytest.approx(35.0)


def test_quantify_reports_the_default_it_used(client, cube_id) -> None:
    """Reported even when no profile applies, so a run on a placeholder
    angle does not look like one on a measured value."""
    r = client.post(
        "/api/eds/quantify", json={"image_id": cube_id, "elements": ["Fe", "Cu"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["calibration"]["take_off_angle_deg"]["origin"] == "default"


# ── the model-based routes ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "extra"),
    [
        ("/api/eds/peakfit", {}),
        ("/api/eds/artifacts", {}),
        ("/api/eds/recalibrate", {"apply": False}),
    ],
)
def test_model_based_routes_read_the_beam_voltage(client, cube_id, path, extra) -> None:
    _apply(client, cube_id, "acquisition", {"beam_energy": {"value": 80.0, "unit": "keV"}})
    body = {"image_id": cube_id, "elements": ["Fe", "Cu"], **extra}
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    cal = r.json()["calibration"]["beam_kv"]
    assert (cal["value"], cal["origin"]) == (80.0, "profile")
