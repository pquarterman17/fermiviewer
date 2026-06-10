"""Stack explode endpoint (checklist K multi-frame stacks)."""

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


def test_explode_stack(tmp_path) -> None:
    client = TestClient(create_app())
    ny, nx, nf = 4, 5, 3
    arr = np.empty((nf, ny, nx), dtype=np.float32)
    for k in range(nf):
        arr[k] = (k + 1) * 10
    f = write_mini_dm4(
        tmp_path / "stack.dm4", dims=[nx, ny, nf],
        data=arr.ravel(), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2
        + [{"scale": 1, "origin": 0, "units": "frame"}],
    )
    cid = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]
    r = client.post(f"/api/image/{cid}/explode")
    assert r.status_code == 200
    metas = r.json()
    assert len(metas) == nf
    for k, m in enumerate(metas):
        assert m["kind"] == "image"
        assert m["shape"] == [ny, nx]
        assert m["name"].endswith(f"[{k + 1}]")
        np.testing.assert_allclose(
            np.asarray(store.get(m["id"]).data), (k + 1) * 10)
        assert m["meta"]["derived_from"] == cid
    # 2D image → 400
    img2 = write_mini_dm4(
        tmp_path / "flat.dm4", dims=[6, 4],
        data=np.zeros(24, dtype=np.float32), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2,
    )
    iid = client.post(
        "/api/session/open", json={"paths": [str(img2)]}
    ).json()[0]["id"]
    assert client.post(f"/api/image/{iid}/explode").status_code == 400


def test_data16_frame_param(tmp_path) -> None:
    """Stack data16 with frame= returns the specific channel, not the sum."""
    client = TestClient(create_app())
    ny, nx, nf = 4, 5, 3
    arr = np.zeros((nf, ny, nx), dtype=np.float32)
    for k in range(nf):
        arr[k] = float(k + 1) * 100.0   # frame 0 → 100, 1 → 200, 2 → 300
    f = write_mini_dm4(
        tmp_path / "stack2.dm4", dims=[nx, ny, nf],
        data=arr.ravel(), data_type=2,
        cal=[{"scale": 1, "origin": 0, "units": "nm"}] * 2
        + [{"scale": 1, "origin": 0, "units": "frame"}],
    )
    sid = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    # without frame → energy sum; X-N-Frames header present
    r0 = client.get(f"/api/image/{sid}/data16")
    assert r0.status_code == 200
    assert r0.headers.get("X-N-Frames") == "3"

    # with frame=1 → second channel (value=200); u16 max should be 65535
    r1 = client.get(f"/api/image/{sid}/data16?frame=1")
    assert r1.status_code == 200
    import struct
    data1 = np.frombuffer(r1.content, dtype="<u2")
    # all pixels in frame 1 are uniform (200.0); normalized → all same value
    assert data1.min() == data1.max()   # uniform frame

    # out-of-range frame is clamped (not 422)
    r_clamp = client.get(f"/api/image/{sid}/data16?frame=999")
    assert r_clamp.status_code == 200
