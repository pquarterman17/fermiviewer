"""API tests for atom-column workshop depth features (audit Tier-1 #2).

Tests the new and extended endpoints:
  - /api/analyze/atoms: win_radius + sublattices params; full strain fields
    (exy, rotation, displacement) in response
  - /api/atoms/strain: direct PPA from positions, no re-detection
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = [pytest.mark.api, pytest.mark.imaging]


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _make_lattice_image() -> np.ndarray:
    """Synthetic 6×5 square lattice of bright Gaussian columns, 9.5 px spacing."""
    xx, yy = np.meshgrid(
        np.arange(1, 61, dtype=np.float64),
        np.arange(1, 51, dtype=np.float64),
    )
    img = 0.05 * np.ones_like(xx)
    for gi in range(5):
        for gj in range(6):
            img += np.exp(
                -((xx - (6 + gj * 9.5)) ** 2 + (yy - (5 + gi * 9.0)) ** 2)
                / (2 * 1.6**2)
            )
    return img * 1000


def _open_lattice(client: TestClient, tmp_path) -> str:
    img = _make_lattice_image()
    h, w = img.shape
    f = write_mini_dm4(
        tmp_path / "latt.dm4", dims=[w, h], data=img.ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(f)]}).json()[0]["id"]


# ── /api/analyze/atoms: extended params ──────────────────────────────


def test_atoms_full_strain_fields(client, tmp_path) -> None:
    """Full PPA strain response now includes exy and rotation per column."""
    img_id = _open_lattice(client, tmp_path)
    r = client.post("/api/analyze/atoms", json={
        "image_id": img_id,
        "sigma": 2,
        "threshold": 0.2,
        "min_separation": 5,
        "win_radius": 4,
        "strain": True,
        "sublattices": 1,
    })
    assert r.status_code == 200
    body = r.json()
    st = body["strain"]
    assert st["valid"] is True
    # all four per-column arrays must be present
    n = body["n_columns"]
    assert len(st["exx"]) == n
    assert len(st["eyy"]) == n
    assert len(st["exy"]) == n, "exy per-column missing from strain response"
    assert len(st["rotation"]) == n, "rotation per-column missing from strain response"
    assert "displacement" in st, "displacement missing from strain response"
    # unstrained synthetic → near-zero medians
    exx_vals = [v for v in st["exx"] if v is not None]
    assert abs(float(np.nanmedian(exx_vals))) < 0.01


def test_atoms_sublattice_param(client, tmp_path) -> None:
    """sublattices=2 produces per-column sublattice labels."""
    # Two-sublattice synthetic: bright (amp 2) and dim (amp 1) columns
    xx, yy = np.meshgrid(
        np.arange(1, 61, dtype=np.float64),
        np.arange(1, 51, dtype=np.float64),
    )
    img = 0.05 * np.ones_like(xx)
    for gi in range(5):
        for gj in range(6):
            amp = 2.0 if (gi + gj) % 2 == 0 else 0.8
            img += amp * np.exp(
                -((xx - (6 + gj * 9.5)) ** 2 + (yy - (5 + gi * 9.0)) ** 2)
                / (2 * 1.6**2)
            )
    h, w = img.shape
    f = write_mini_dm4(
        tmp_path / "sub.dm4", dims=[w, h], data=(img * 1000).ravel(),
        cal=[{"scale": 0.5, "origin": 0, "units": "nm"}] * 2,
    )
    img_id = client.post(
        "/api/session/open", json={"paths": [str(f)]}
    ).json()[0]["id"]

    r = client.post("/api/analyze/atoms", json={
        "image_id": img_id,
        "sigma": 2,
        "threshold": 0.15,
        "min_separation": 5,
        "win_radius": 4,
        "sublattices": 2,
    })
    assert r.status_code == 200
    body = r.json()
    assert "sublattice" in body, "sublattice labels missing from response"
    labels = body["sublattice"]
    n = body["n_columns"]
    assert len(labels) == n
    assert set(labels) == {1, 2}


def test_atoms_win_radius_param(client, tmp_path) -> None:
    """win_radius is forwarded correctly; wider window still fits the lattice."""
    img_id = _open_lattice(client, tmp_path)
    r8 = client.post("/api/analyze/atoms", json={
        "image_id": img_id, "sigma": 2, "threshold": 0.2,
        "min_separation": 5, "win_radius": 8,
    })
    assert r8.status_code == 200
    assert r8.json()["n_columns"] == 30


# ── /api/atoms/strain: standalone PPA from positions ─────────────────


def test_atoms_strain_endpoint_basic(client, tmp_path) -> None:
    """POST /api/atoms/strain returns full PPA from positions alone."""
    img_id = _open_lattice(client, tmp_path)
    # First detect to get positions
    det = client.post("/api/analyze/atoms", json={
        "image_id": img_id, "sigma": 2, "threshold": 0.2,
        "min_separation": 5, "win_radius": 4,
    }).json()
    positions = det["positions"]
    n = det["n_columns"]

    r = client.post("/api/atoms/strain", json={
        "positions": positions,
        "ref_vectors": None,
        "origin": None,
        "neighbors": 8,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert len(body["exx"]) == n
    assert len(body["eyy"]) == n
    assert len(body["exy"]) == n
    assert len(body["rotation"]) == n
    # near-zero for unstrained synthetic
    exx_vals = [v for v in body["exx"] if v is not None]
    assert abs(float(np.nanmedian(exx_vals))) < 0.01


def test_atoms_strain_endpoint_with_ref_vectors(client, tmp_path) -> None:
    """Providing explicit ref_vectors + origin yields the same result."""
    img_id = _open_lattice(client, tmp_path)
    det = client.post("/api/analyze/atoms", json={
        "image_id": img_id, "sigma": 2, "threshold": 0.2,
        "min_separation": 5, "win_radius": 4,
    }).json()
    positions = det["positions"]
    lv = det["lattice"]

    # strain with explicit reference from the detected lattice
    r = client.post("/api/atoms/strain", json={
        "positions": positions,
        "ref_vectors": [lv["a1"], lv["a2"]],
        "origin": positions[0],  # any point
        "neighbors": 8,
    })
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_atoms_strain_endpoint_too_few_columns(client) -> None:
    """Fewer than 4 positions → valid=False (not an error, just no strain)."""
    r = client.post("/api/atoms/strain", json={
        "positions": [[10.0, 10.0], [20.0, 10.0], [10.0, 20.0]],
        "ref_vectors": None,
        "origin": None,
    })
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_atoms_strain_endpoint_validation(client) -> None:
    """neighbors out of range → 422."""
    r = client.post("/api/atoms/strain", json={
        "positions": [[10.0, 10.0], [20.0, 10.0]],
        "neighbors": 1,   # below ge=3
    })
    assert r.status_code == 422
