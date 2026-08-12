"""Scan-shape candidates and the /fourd/{id}/reshape route (PLAN_4DSTEM #14).

A Merlin acquisition arrives as N frames and nothing else, so until the user
says otherwise the viewer shows a 1xN strip. These cover the two halves of
letting them say otherwise: which shapes to offer, and re-opening under one.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.fourd.scanshape import scan_shape_candidates
from fermiviewer.io.fourd.mib import load_mib
from fermiviewer.server import create_app
from fermiviewer.session import store as image_store
from fermiviewer.session_fourd import fourd_store

pytestmark = pytest.mark.api

_RAW_WORD = 8


# ── the pure half ─────────────────────────────────────────────────────

def test_candidates_are_all_exact_factorisations() -> None:
    for n in (1, 2, 12, 132, 256, 1024, 16384, 9973):
        for rows, cols in scan_shape_candidates(n):
            assert rows * cols == n, (n, rows, cols)
            assert rows > 0 and cols > 0


def test_the_squarest_shape_is_offered_first() -> None:
    """A STEM raster is square far more often than not, so 128x128 must be
    the first thing a 16384-frame file suggests — not 1x16384, which is what
    the parser already defaulted to and what the user is here to change."""
    assert scan_shape_candidates(16384)[0] == (128, 128)
    assert scan_shape_candidates(256)[0] == (16, 16)
    assert scan_shape_candidates(12)[0] == (4, 3)


def test_both_orientations_are_offered() -> None:
    """Nothing in the file distinguishes a 64-row scan from a 64-column one,
    so offering only one would silently pick for the user."""
    got = scan_shape_candidates(8192)
    assert (128, 64) in got and (64, 128) in got


def test_the_line_scan_survives_the_limit() -> None:
    """1xN is a real acquisition mode AND the parser's own default, so it has
    to stay reachable even when a highly composite frame count has more
    near-square factorisations than the list shows."""
    n = 720  # 30 divisors — comfortably more than the default limit
    got = scan_shape_candidates(n)
    assert len(got) <= 12
    assert (1, n) in got


def test_a_prime_frame_count_offers_only_the_line_scan() -> None:
    got = scan_shape_candidates(9973)  # prime
    assert set(got) == {(1, 9973), (9973, 1)}


def test_degenerate_frame_counts_do_not_raise() -> None:
    assert scan_shape_candidates(0) == []
    assert scan_shape_candidates(-4) == []
    assert scan_shape_candidates(1) == [(1, 1)]


# ── the route ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_stores():
    image_store.clear()
    fourd_store.clear()
    yield
    image_store.clear()
    fourd_store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _write_mib(path: Path, n_frames: int, height: int = 4, width: int = 16) -> Path:
    """A single-chip RAW .mib of `n_frames` distinguishable frames.

    The payload is written pre-scrambled (each group of 8 columns reversed),
    the inverse of the descramble the reader applies, so a decoded frame k is
    exactly `k` everywhere — which makes "did the re-raster put frame k at the
    right probe position?" a value check rather than a shape check.
    """
    fields = ["MQ1", "000001", "00128", "01", f"{width:04d}", f"{height:04d}",
              "R64", "   1x1", "0F"]
    header = (",".join(fields) + ",").encode("ascii")
    header += b" " * (128 - len(header))
    with open(path, "wb") as f:
        for k in range(n_frames):
            frame = np.full((height, width), k, dtype=np.uint8)
            grouped = frame.reshape(height, width // _RAW_WORD, _RAW_WORD)
            f.write(header)
            f.write(np.ascontiguousarray(grouped[:, :, ::-1].reshape(height, width)))
    return path


@pytest.fixture()
def merlin(tmp_path: Path) -> str:
    """A 12-frame headerless Merlin file, registered as it would be on open."""
    path = _write_mib(tmp_path / "scan.mib", 12)
    ds = load_mib(path)
    return fourd_store.add(ds, path.name, source_path=path)


def _meta(client: TestClient, fourd_id: str) -> dict:
    r = client.get(f"/api/fourd/{fourd_id}/meta")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_headerless_file_advertises_that_its_shape_is_a_guess(client, merlin):
    """The GUI can only offer the control if the metadata admits the problem:
    the default 1x12 strip is the parser's fallback, not the acquisition."""
    meta = _meta(client, merlin)
    assert meta["scan_shape"] == [1, 12]
    assert meta["n_frames"] == 12
    assert meta["scan_shape_from_file"] is False
    assert [4, 3] in meta["scan_shape_options"]
    assert meta["scan_shape_options"][0] == [4, 3]  # squarest first


def test_reshape_rerasters_the_scan_and_keeps_the_id(client, merlin):
    r = client.post(f"/api/fourd/{merlin}/reshape", json={"rows": 3, "cols": 4})
    assert r.status_code == 200, r.text
    body = r.json()
    # Same id: the workshop's selection and probe are keyed by it, and a new
    # one would silently deselect the dataset the user is looking at.
    assert body["id"] == merlin
    assert body["scan_shape"] == [3, 4]
    assert body["n_frames"] == 12
    assert _meta(client, merlin)["scan_shape"] == [3, 4]


def test_reshape_puts_each_frame_at_the_right_probe_position(client, merlin):
    """The claim that matters: row-major frame order. Frame k must land at
    (k // cols, k % cols) — a transposed or column-major re-raster produces a
    nav image that looks plausible and is wrong."""
    assert client.post(
        f"/api/fourd/{merlin}/reshape", json={"rows": 3, "cols": 4}
    ).status_code == 200
    ds = fourd_store.get(merlin)
    for k in range(12):
        y, x = divmod(k, 4)
        assert np.all(ds.pattern(y, x) == k), (k, y, x)


def test_reshape_refuses_a_shape_that_is_not_the_frame_count(client, merlin):
    r = client.post(f"/api/fourd/{merlin}/reshape", json={"rows": 5, "cols": 3})
    assert r.status_code == 422
    assert "12 frames" in r.json()["detail"]
    # ...and leaves the dataset exactly as it was.
    assert _meta(client, merlin)["scan_shape"] == [1, 12]


def test_reshape_refuses_a_non_positive_shape(client, merlin):
    for body in ({"rows": 0, "cols": 12}, {"rows": -3, "cols": -4}):
        r = client.post(f"/api/fourd/{merlin}/reshape", json=body)
        assert r.status_code == 422, body


def test_reshape_refuses_a_format_that_records_its_own_raster(client, tmp_path):
    """Re-rastering a file whose navigation axes are IN it would be inviting
    the user to contradict the acquisition."""
    path = _write_mib(tmp_path / "declared.mib", 12)
    ds = load_mib(path, scan_shape=(3, 4))
    ds.metadata["scan_shape_from_file"] = True
    fourd_id = fourd_store.add(ds, path.name, source_path=path)
    r = client.post(f"/api/fourd/{fourd_id}/reshape", json={"rows": 4, "cols": 3})
    assert r.status_code == 422
    assert "cannot be re-rastered" in r.json()["detail"]
    assert _meta(client, fourd_id)["scan_shape_options"] == []


def test_reshape_404s_on_an_unknown_dataset(client):
    r = client.post("/api/fourd/4d-999/reshape", json={"rows": 1, "cols": 1})
    assert r.status_code == 404


def test_reshape_drops_the_stale_nav_image_association(client, merlin):
    """The nav image was rastered at the OLD shape, so it no longer describes
    this dataset. A second /nav call must register a fresh one rather than
    hand back a 1x12 strip for a 3x4 scan."""
    before = client.get(f"/api/fourd/{merlin}/nav").json()
    assert before["shape"] == [1, 12]
    assert client.post(
        f"/api/fourd/{merlin}/reshape", json={"rows": 3, "cols": 4}
    ).status_code == 200
    after = client.get(f"/api/fourd/{merlin}/nav").json()
    assert after["shape"] == [3, 4]
    assert after["id"] != before["id"]
