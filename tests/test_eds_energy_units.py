"""EDS energy-axis unit normalization (eV-calibrated cubes).

Every EDS energy input is keV — the characteristic-line library, the
element-map window, the quant half-window, the recalibration anchors — but
``io/ser.py`` and ``io/dm.py`` calibrate the axis in eV. Before ``to_kev``
was applied at the route boundary, a keV window selected ~no channels on an
eV axis, so an element map came back all zeros instead of raising.

The endpoint tests are written as *equivalence* properties: the same
physical spectrum is opened twice, once calibrated in keV and once in eV,
and both must produce the same answer. That cannot be satisfied by a
hard-coded expectation, and it fails on the unconverted code.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.energy_units import kev_factor, to_kev
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.eds, pytest.mark.api]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_cube(
    client: TestClient, tmp_path, units: str, name: str,
    scale_ev: float | None = None,
) -> str:
    """4×5 px × 1024 ch EDS SI: flat bg + Fe Kα at 6.404 keV.

    By default the axis is *physically identical* in both unit systems:
    0.01 keV/ch is the same calibration as 10 eV/ch, so every derived
    quantity must match. ``scale_ev`` overrides the declared eV step to
    build a deliberately miscalibrated axis.
    """
    ny, nx, ne = 4, 5, 1024
    energy_kev = np.arange(ne) * 0.01
    spec = np.full(ne, 2.0, dtype=np.float32)
    spec += 50.0 * np.exp(
        -((energy_kev - 6.404) ** 2) / (2 * 0.03**2)
    ).astype(np.float32)
    flat = np.tile(spec, ny * nx)
    de = (
        scale_ev if scale_ev is not None
        else 0.01 / kev_factor(units)   # 0.01 keV/ch  ==  10 eV/ch
    )
    f = write_mini_dm4(
        tmp_path / name,
        dims=[nx, ny, ne],
        data=flat,
        data_type=2,
        cal=[
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": 1.0, "origin": 0, "units": "nm"},
            {"scale": de, "origin": 0, "units": units},
        ],
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


# ── pure helper ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("units", "factor"),
    [("keV", 1.0), ("kev", 1.0), ("eV", 1e-3), (" EV ", 1e-3),
     ("meV", 1e-6), ("", 1.0), ("nm", 1.0), ("counts", 1.0)],
)
def test_kev_factor_table(units: str, factor: float) -> None:
    assert kev_factor(units) == pytest.approx(factor)


def test_to_kev_scales_ev_and_passes_kev_through() -> None:
    ev = np.array([500.0, 6404.0, 10_000.0])
    assert to_kev(ev, "eV") == pytest.approx([0.5, 6.404, 10.0])
    # already-keV axes are returned untouched (no needless allocation)
    kev = np.array([0.5, 6.404])
    assert to_kev(kev, "keV") is kev


def test_to_kev_leaves_uncalibrated_axis_alone() -> None:
    """An uncalibrated AxisCal falls back to channel indices with units ""
    — scaling those by 1e-3 would invent a calibration."""
    channels = np.arange(4.0)
    assert to_kev(channels, "") is channels


# ── endpoint equivalence: eV cube must match keV cube ────────────────


def test_element_map_matches_across_axis_units(client, tmp_path) -> None:
    """The Fe Kα window is keV; on the unconverted eV axis it selected no
    channels and the map came back all zeros."""
    body = {"e_lo": 6.3, "e_hi": 6.5, "bg": "none"}
    kev_id = _open_cube(client, tmp_path, "keV", "kev.dm4")
    r_kev = client.post(
        "/api/eds/element-map", json={"image_id": kev_id, **body}
    )
    ev_id = _open_cube(client, tmp_path, "eV", "ev.dm4")
    r_ev = client.post(
        "/api/eds/element-map", json={"image_id": ev_id, **body}
    )

    assert r_kev.status_code == 200 and r_ev.status_code == 200
    kev_map = np.array(r_kev.json()["map"])
    ev_map = np.array(r_ev.json()["map"])
    # the keV cube is the control: it must actually contain the peak
    assert kev_map.sum() > 0
    assert ev_map == pytest.approx(kev_map)


def test_auto_assign_matches_across_axis_units(client, tmp_path) -> None:
    """peaks_kev is keV by contract and matched against a keV line library,
    so an eV-calibrated cube must report the same peaks as its keV twin.

    Asserted as an equivalence rather than an absolute peak position: this
    fix does not change the detector, only the unit of the axis handed to
    it, and the detector's exact picks on a synthetic spectrum are not the
    behaviour under test.
    """
    kev_id = _open_cube(client, tmp_path, "keV", "kev.dm4")
    r_kev = client.post("/api/eds/auto-assign", json={"image_id": kev_id})
    ev_id = _open_cube(client, tmp_path, "eV", "ev.dm4")
    r_ev = client.post("/api/eds/auto-assign", json={"image_id": ev_id})

    assert r_kev.status_code == 200 and r_ev.status_code == 200
    peaks_kev = r_kev.json()["peaks_kev"]
    assert peaks_kev, "control (keV) cube detected no peaks"
    assert r_ev.json()["peaks_kev"] == pytest.approx(peaks_kev)


def test_recalibrate_applies_offset_in_native_units(client, tmp_path) -> None:
    """``gain`` is a ratio and folds into ``scale`` unit-free, but ``offset``
    is additive and fitted in keV — folding it into an eV ``origin`` without
    converting is wrong by 1/kev_factor (1000x).

    Asserted as the docstring's own contract: the stored axis, re-expressed
    in keV, must equal ``gain * old_keV + offset``. The cube is deliberately
    miscalibrated (10.5 eV/ch) so the fitted offset is materially non-zero —
    on an already-perfect axis offset ~ 0 and a 1000x error is invisible.
    """
    ne, de_ev = 1024, 10.5
    ev_id = _open_cube(client, tmp_path, "eV", "mis.dm4", scale_ev=de_ev)
    r = client.post(
        "/api/eds/recalibrate",
        json={"image_id": ev_id, "elements": ["Fe"], "apply": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["units"] == "eV", "the stored axis keeps the source's unit"
    assert body["offset"] != 0.0, "offset ~ 0 would make this test vacuous"

    idx = np.arange(ne, dtype=np.float64)
    old_kev = idx * de_ev * 1e-3
    new_kev = (idx - body["origin"]) * body["scale"] * 1e-3
    assert new_kev == pytest.approx(
        body["gain"] * old_kev + body["offset"], abs=1e-7
    )
