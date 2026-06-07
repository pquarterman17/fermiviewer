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
