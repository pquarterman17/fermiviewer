"""Real BCF corpus checks (../fv-example-data) — validates the EDS fixes
from the 2026-07-02 email against genuine Bruker TEM + SEM data:

  * cube loads as a SPECTRUM_IMAGE with a real keV energy axis   (Bug A data)
  * channel-0 is empty but the energy SUM carries signal          (Bug C)
  * /data16 (the endpoint the Stage calls) defaults to that sum   (Bug C)
  * Quantify keeps present elements' maps and skips absent ones    (Bug B)

Auto-skips when the sibling example-data repo isn't checked out, like the
other realdata-marked tests.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import DataKind
from fermiviewer.io.bcf import load_bcf
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = [pytest.mark.realdata, pytest.mark.api]

# relative to the bcf_examples fixture (../fv-example-data/BCF)
CUBES = {
    "TEM": "TEM/test_TEM.bcf",
    "SEM_Hitachi": "SEM/Hitachi_TM3030Plus.bcf",
    "SEM_P45": "SEM/P45_the_default_job.bcf",
}
HITACHI = "SEM/Hitachi_TM3030Plus.bcf"


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open(client: TestClient, path: Path) -> str:
    return client.post(
        "/api/session/open", json={"paths": [str(path)]}
    ).json()[0]["id"]


@pytest.mark.parametrize("rel", CUBES.values(), ids=list(CUBES))
def test_example_bcf_loads_as_cube(bcf_examples: Path, rel: str) -> None:
    ds = load_bcf(bcf_examples / rel)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.ndim == 3
    assert ds.energy_cal.units == "keV"  # real energy, not a timestamp (Bug A)
    # Bug C rationale: energy-channel 0 (~0 keV) is empty → a black stage,
    # while the energy SUM has real signal → a visible overview.
    assert int(np.ptp(ds.data[:, :, 0])) == 0          # channel 0 flat
    assert int(np.ptp(ds.data.sum(axis=2))) > 0        # energy sum has range


def test_example_bcf_stage_raster_defaults_to_sum(
    client: TestClient, bcf_examples: Path
) -> None:
    """/data16 is what the Stage fetches. No frame → the signal-bearing sum
    (the fixed default); frame=0 → the flat channel that used to black out."""
    img = _open(client, bcf_examples / HITACHI)
    summ = client.get(f"/api/image/{img}/data16")
    ch0 = client.get(f"/api/image/{img}/data16?frame=0")
    assert summ.status_code == 200 and ch0.status_code == 200
    # sum spans a real range; channel 0 is flat (vmin == vmax) → renders black
    assert float(summ.headers["X-Max"]) > float(summ.headers["X-Min"])
    assert float(ch0.headers["X-Max"]) == float(ch0.headers["X-Min"])
    assert int(summ.headers["X-N-Frames"]) > 1


def test_example_bcf_quantify_skips_absent_elements(
    client: TestClient, bcf_examples: Path
) -> None:
    """Bug B on real data: Cu/Al/O are present (maps kept); Au/Pb are not
    (maps skipped → null), with `maps` staying aligned to `elements`."""
    img = _open(client, bcf_examples / HITACHI)
    with pytest.warns(UserWarning, match="no built-in k-factor for 'Pb'"):
        r = client.post(
            "/api/eds/quantify",
            json={"image_id": img, "elements": ["Cu", "Al", "O", "Au", "Pb"]},
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["maps"]) == len(body["elements"])
    by_el = dict(zip(body["elements"], body["maps"], strict=True))
    for present in ("Cu", "Al", "O"):
        assert by_el.get(present) is not None, f"{present} should be kept"
    for absent in ("Au", "Pb"):
        assert by_el.get(absent) is None, f"{absent} should be skipped as blank"
