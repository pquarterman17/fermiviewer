"""Cross-origin (CSRF / DNS-rebinding) guard on the /api surface."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_no_origin_allowed(client: TestClient) -> None:
    # same-origin navigations / desktop shell / curl / tests send no Origin
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8000",  # served SPA
        "http://localhost:8000",
        "http://localhost:5173",  # Vite dev server
        "tauri://localhost",  # Tauri (macOS/Linux)
        "http://tauri.localhost",  # Tauri (Windows)
    ],
)
def test_app_origins_allowed(client: TestClient, origin: str) -> None:
    assert client.get("/api/health", headers={"Origin": origin}).status_code == 200


@pytest.mark.parametrize("origin", ["https://evil.example", "http://attacker.test:8000", "null"])
def test_foreign_origin_blocked(client: TestClient, origin: str) -> None:
    # reads…
    assert client.get("/api/health", headers={"Origin": origin}).status_code == 403
    # …and mutations are both rejected before reaching the route
    r = client.post(
        "/api/session/open", json={"paths": []}, headers={"Origin": origin}
    )
    assert r.status_code == 403


def test_guard_only_covers_api(client: TestClient) -> None:
    # non-/api paths aren't origin-guarded (no 403 from the guard)
    assert (
        client.get("/", headers={"Origin": "https://evil.example"}).status_code != 403
    )
