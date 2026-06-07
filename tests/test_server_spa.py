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


def test_lifecycle_ws_safe_without_arming() -> None:
    # connect/disconnect must NOT shut anything down outside main():
    # auto-shutdown arms only in the fv entry point, never under tests
    import fermiviewer.server as srv

    client = TestClient(create_app())
    assert srv._auto_shutdown is False
    with client.websocket_connect("/api/ws"):
        pass  # presence registered then dropped
    # still serving after the socket closed
    assert client.get("/api/health").status_code == 200


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
