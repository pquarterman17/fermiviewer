"""API smoke tests."""

import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app

pytestmark = pytest.mark.api


def test_health() -> None:
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_debug_report() -> None:
    from fastapi.testclient import TestClient

    from fermiviewer.server import create_app

    client = TestClient(create_app())
    r = client.get("/api/debug/report")
    assert r.status_code == 200
    body = r.json()
    assert "version" in body and "platform" in body
    assert isinstance(body["server_log"], list)
    assert isinstance(body["open_images"], list)
