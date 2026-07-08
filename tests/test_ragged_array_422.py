"""ValueError from malformed request/calc-layer input must surface as a
422, not an unhandled 500 — the contract every sibling analysis endpoint
already followed. Covers the 3 sites that didn't: /api/atoms/strain,
/api/analyze/ctf, /api/analyze/radial (all now go through the shared
routes._arrays.value_error_as_422 guard).
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def img_id(client, tmp_path) -> str:
    w, h = 16, 12
    flat = np.array([x + 10 * y for y in range(h) for x in range(w)])
    f = write_mini_dm4(
        tmp_path / "img.dm4", dims=[w, h], data=flat,
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]


def test_atoms_strain_ragged_positions_is_422(client: TestClient) -> None:
    """positions is a raw list[list[float]] with no shape enforcement —
    a ragged sublist reaches np.asarray directly and used to 500."""
    r = client.post("/api/atoms/strain", json={
        # second point has only 1 coordinate: inhomogeneous shape
        "positions": [[10.0, 10.0], [20.0], [10.0, 20.0], [30.0, 30.0]],
    })
    assert r.status_code == 422


def test_atoms_strain_ragged_ref_vectors_is_422(client: TestClient) -> None:
    r = client.post("/api/atoms/strain", json={
        "positions": [[10.0, 10.0], [20.0, 10.0], [10.0, 20.0], [20.0, 20.0]],
        "ref_vectors": [[1.0, 0.0], [0.0]],  # ragged
    })
    assert r.status_code == 422


def test_analyze_ctf_calc_value_error_is_422(
    client: TestClient, img_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A calc-layer ValueError (e.g. a degenerate raster) must not leak
    out as a 500 — analyze_ctf previously had no guard at all."""
    import fermiviewer.routes.imaging_ops as imaging_ops

    def boom(*a, **kw):
        raise ValueError("degenerate raster")

    monkeypatch.setattr(imaging_ops, "estimate_ctf", boom)
    r = client.post("/api/analyze/ctf", json={"image_id": img_id})
    assert r.status_code == 422
    assert "degenerate raster" in r.json()["detail"]


def test_analyze_radial_calc_value_error_is_422(
    client: TestClient, img_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same gap on analyze_radial: no try/except around the calc call,
    unlike every sibling analyze/* endpoint (gpa/vdf/fft-mask/etc)."""
    import fermiviewer.routes.imaging_ops as imaging_ops

    def boom(*a, **kw):
        raise ValueError("degenerate raster")

    monkeypatch.setattr(imaging_ops, "radial_profile", boom)
    r = client.post("/api/analyze/radial", json={"image_id": img_id})
    assert r.status_code == 422
    assert "degenerate raster" in r.json()["detail"]

    monkeypatch.setattr(imaging_ops, "azimuthal_integrate", boom)
    r2 = client.post(
        "/api/analyze/radial", json={"image_id": img_id, "azimuthal": True}
    )
    assert r2.status_code == 422
