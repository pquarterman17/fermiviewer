"""The built SPA is served from / when frontend/dist exists."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import _frontend_dist, create_app

pytestmark = pytest.mark.api


def test_health_always_available() -> None:
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.skipif(
    _frontend_dist() is None,
    reason="frontend/dist not built (run `npm run build` in frontend/)",
)
def test_spa_served_at_root() -> None:
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<div id=\"root\">" in r.text
    # API routes take precedence over the static mount
    assert client.get("/api/health").status_code == 200
