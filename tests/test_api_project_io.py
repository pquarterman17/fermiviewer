"""API tests for the `.fvp` project surface (plan items 32–35).

Replaces the v1 `/session/{save,load}` tests: those endpoints went with the v1
write path. What is exercised here is what a user can actually do —

* **Save Project** / **Export Project Bundle**, the two payload modes;
* **Open Project…**, on a `.fvp` and on a legacy v1 pair (migrated in memory);
* **Locate folder…**, re-pointing whatever is still unavailable;

— plus the assertion the whole design turns on: opening a project on a machine
without its data and pressing save CANNOT destroy it (ADR 0002 §4).
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import tifffile
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4
from fixtures.v1_session import write_v1_session

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_session():
    store.clear()
    project.clear()
    yield
    store.clear()
    project.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _open_dm4(client: TestClient, path: Path) -> str:
    w, h = 8, 6
    flat = np.array([x + 10 * y for y in range(h) for x in range(w)])
    write_mini_dm4(
        path, dims=[w, h], data=flat,
        cal=[{"scale": 0.25, "origin": 0, "units": "nm"}] * 2,
    )
    return client.post("/api/session/open", json={"paths": [str(path)]}).json()[0]["id"]


def _open_tiff(client: TestClient, path: Path, *, description: str = "") -> str:
    tifffile.imwrite(path, np.full((6, 8), 11, dtype=np.uint16), description=description)
    return client.post("/api/session/open", json={"paths": [str(path)]}).json()[0]["id"]


def _manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json"))


def _client_state(img_id: str) -> dict[str, Any]:
    """A payload with content from every promoted section plus ui_state."""
    return {
        "order": [img_id],
        "activeId": img_id,
        "views": {img_id: {"z": 2, "px": 0.5, "py": 0.5}},
        "browseScale": {"locked": True, "umPerPx": 1.5},
        "imageGroups": [
            {
                "id": "g1",
                "name": "Sample A",
                "ids": [img_id],
                "parent": None,
                "params": {"anneal_T": {"value": 450.0, "unit": "degC"}},
                "color": "#ff8800",
            }
        ],
        "measures": {
            img_id: [
                {
                    "id": "m1",
                    "kind": "polygon",
                    "pts": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.2}],
                    "text": "grain 3",
                }
            ]
        },
    }


# ── save / load round trip ───────────────────────────────────────────


def test_save_writes_one_fvp_and_load_restores_everything(client, tmp_path) -> None:
    img_id = _open_dm4(client, tmp_path / "img.dm4")
    fft_id = client.post(f"/api/image/{img_id}/fft").json()["id"]
    src = np.array(store.get(img_id).data, copy=True)
    state = _client_state(img_id)

    r = client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "study"), "client_state": state, "name": "Study"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_images"] == 2
    assert body["payload_mode"] == "light"
    # ONE file, with the suffix applied, and no v1 sidecars anywhere
    assert body["path"] == str(tmp_path / "study.fvp")
    assert (tmp_path / "study.fvp").is_file()
    assert not (tmp_path / "study.json").exists()
    assert not (tmp_path / "study.npz").exists()

    store.clear()
    r2 = client.post("/api/project/load", json={"path": str(tmp_path / "study.fvp")})
    assert r2.status_code == 200, r2.text
    loaded = r2.json()
    assert loaded["unavailable"] == []
    assert loaded["project"]["name"] == "Study"
    metas = {m["id"]: m for m in loaded["images"]}
    assert set(metas) == {img_id, fft_id}  # ids preserved

    # the promoted sections come back as the one client_state the store speaks
    cs = loaded["client_state"]
    assert cs["measures"] == state["measures"]
    assert cs["imageGroups"] == state["imageGroups"]
    assert cs["views"] == state["views"]  # opaque ui_state passthrough
    assert cs["browseScale"] == state["browseScale"]

    # pixels, dtype and calibration survive; the session is usable again
    restored = store.get(img_id)
    np.testing.assert_array_equal(restored.data, src)
    assert restored.data.dtype == src.dtype
    assert metas[img_id]["pixel_size"] == pytest.approx(0.25)
    assert store.get(fft_id).metadata.get("derived_from") == img_id
    assert client.get(f"/api/image/{img_id}/render").status_code == 200


def test_promoted_sections_are_schema_validated_not_opaque(client, tmp_path) -> None:
    """The reason samples/measures were promoted out of client_state: the
    manifest now holds them where a schema can check them."""
    img_id = _open_dm4(client, tmp_path / "img.dm4")
    client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "s.fvp"), "client_state": _client_state(img_id)},
    )
    manifest = _manifest(tmp_path / "s.fvp")
    assert manifest["samples"][0]["image_ids"] == [img_id]  # `ids` renamed
    assert manifest["samples"][0]["params"]["anneal_T"] == {
        "value": 450.0, "unit": "degC"
    }
    assert manifest["measures"][img_id][0]["kind"] == "polygon"
    # and they are NOT left behind in the opaque half
    assert "imageGroups" not in manifest["ui_state"]
    assert "measures" not in manifest["ui_state"]
    assert manifest["ui_state"]["browseScale"] == {"locked": True, "umPerPx": 1.5}


def test_light_references_sources_and_bundle_embeds_them(client, tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _open_tiff(client, data_dir / "frame.tif")
    client.post(f"/api/image/{store.ids()[0]}/fft")  # a derived image too

    light = client.post(
        "/api/project/save", json={"path": str(tmp_path / "light.fvp")}
    ).json()
    bundle = client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "bundle.fvp"), "mode": "bundle"},
    ).json()
    assert (light["payload_mode"], bundle["payload_mode"]) == ("light", "bundle")

    light_images = {i["name"]: i for i in _manifest(tmp_path / "light.fvp")["images"]}
    assert light_images["frame.tif"]["embedded"] is False
    assert light_images["frame.tif"]["rel"] == "frame.tif"
    assert light_images["frame.tif"]["size_bytes"] > 0
    # derived images embed in BOTH modes — a light save that referenced them
    # would silently discard work that has no file
    derived = [i for i in light_images.values() if i["derived_from"]]
    assert derived and all(i["embedded"] for i in derived)

    bundled = {i["name"]: i for i in _manifest(tmp_path / "bundle.fvp")["images"]}
    assert all(i["embedded"] for i in bundled.values())
    assert bundled["frame.tif"]["rel"] == "frame.tif"  # references kept anyway
    assert (tmp_path / "bundle.fvp").stat().st_size > (
        tmp_path / "light.fvp"
    ).stat().st_size


# ── thumbnails (plan #37) ─────────────────────────────────────────────


def test_a_placeholders_thumbnail_is_exposed_base64_on_load(client, tmp_path) -> None:
    """The one thing a placeholder CAN still show: the preview baked in
    while its pixels still existed, so the library isn't a blank card."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _open_tiff(client, data_dir / "frame.tif")
    client.post(
        "/api/project/save", json={"path": str(project_dir / "study.fvp")}
    )
    (data_dir / "frame.tif").unlink()

    store.clear()
    opened = client.post(
        "/api/project/load", json={"path": str(project_dir / "study.fvp")}
    ).json()
    (placeholder,) = opened["unavailable"]
    assert placeholder["thumb"] is not None
    thumb = Image.open(io.BytesIO(base64.b64decode(placeholder["thumb"])))
    assert thumb.format == "PNG"
    assert max(thumb.size) <= 256


# ── v1 migration (item 32) ───────────────────────────────────────────


def _v1_entries() -> list[tuple[str, str, DataStruct]]:
    image = DataStruct(
        data=np.arange(12, dtype=np.uint16).reshape(3, 4),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"vendor": "acme", "source": "/nowhere/frame.tif"},
    )
    derived = DataStruct(
        data=np.arange(12, dtype=np.float32).reshape(3, 4),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"derived_from": "v1-a", "parser": "derived"},
    )
    return [("v1-a", "frame.tif", image), ("v1-b", "frame fft", derived)]


V1_STATE: dict[str, Any] = {
    "order": ["v1-a", "v1-b"],
    "activeId": "v1-b",
    "views": {"v1-a": {"z": 3}},
    "display": {"v1-a": {"cmap": "viridis"}},
    "savedRois": {"v1-a": [{"id": "r1", "name": "roi", "kind": "roi", "pts": []}]},
    "sbsRows": 1,
    "sbsCols": 2,
    "imageGroups": [
        {
            "id": "g1",
            "name": "Sample A",
            "ids": ["v1-a", "v1-b"],
            "params": {"dose": {"value": 12.5, "unit": "pA"}},
        }
    ],
    "measures": {
        "v1-a": [{"id": "m1", "kind": "distance", "pts": [{"x": 0.0, "y": 0.0}]}]
    },
}


def test_a_v1_workspace_opens_with_nothing_lost(client, tmp_path) -> None:
    json_path, npz_path = write_v1_session(
        tmp_path / "legacy.json", _v1_entries(), V1_STATE
    )
    r = client.post("/api/project/load", json={"path": str(json_path)})
    assert r.status_code == 200, r.text
    body = r.json()

    assert [m["id"] for m in body["images"]] == ["v1-a", "v1-b"]
    assert body["unavailable"] == []  # v1 embedded everything
    assert body["project"]["name"] == "legacy"
    np.testing.assert_array_equal(
        store.get("v1-a").data, np.arange(12, dtype=np.uint16).reshape(3, 4)
    )
    assert store.get("v1-a").metadata["vendor"] == "acme"

    cs = body["client_state"]
    # the opaque blob's presentational half rides through untouched
    for key in ("order", "activeId", "views", "display", "savedRois", "sbsRows"):
        assert cs[key] == V1_STATE[key]
    # ...and its scientific half is now the validated sections, normalised
    assert cs["measures"] == V1_STATE["measures"]
    assert cs["imageGroups"][0]["ids"] == ["v1-a", "v1-b"]
    assert cs["imageGroups"][0]["params"]["dose"] == {"value": 12.5, "unit": "pA"}
    assert cs["imageGroups"][0]["parent"] is None
    assert npz_path.is_file()  # migration is in memory; v1 is left alone


def test_the_save_after_a_v1_load_writes_a_fvp(client, tmp_path) -> None:
    json_path, _ = write_v1_session(tmp_path / "legacy.json", _v1_entries(), V1_STATE)
    loaded = client.post("/api/project/load", json={"path": str(json_path)}).json()

    saved = client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "legacy"), "client_state": loaded["client_state"]},
    ).json()
    assert saved["path"] == str(tmp_path / "legacy.fvp")

    store.clear()
    again = client.post(
        "/api/project/load", json={"path": str(tmp_path / "legacy.fvp")}
    ).json()
    assert [m["id"] for m in again["images"]] == ["v1-a", "v1-b"]
    assert again["client_state"]["measures"] == V1_STATE["measures"]
    assert again["client_state"]["imageGroups"][0]["params"]["dose"] == {
        "value": 12.5,
        "unit": "pA",
    }
    assert again["client_state"]["views"] == V1_STATE["views"]
    # the v1 source no longer exists, so nothing could be referenced: the
    # pixels had to be embedded rather than dropped
    assert all(i["embedded"] for i in _manifest(tmp_path / "legacy.fvp")["images"])
    np.testing.assert_array_equal(
        store.get("v1-a").data, np.arange(12, dtype=np.uint16).reshape(3, 4)
    )


# ── the no-data-loss assertion (items 34/35) ─────────────────────────


def test_saving_a_project_whose_data_is_missing_preserves_its_reference(
    client, tmp_path
) -> None:
    """THE assertion. Open a project on a machine without its data, press
    save, and the reference must still be there afterwards."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    img_id = _open_tiff(client, data_dir / "frame.tif")
    state = _client_state(img_id)
    client.post(
        "/api/project/save",
        json={"path": str(project_dir / "study.fvp"), "client_state": state},
    )
    (data_dir / "frame.tif").unlink()  # the data is now missing

    store.clear()
    opened = client.post(
        "/api/project/load", json={"path": str(project_dir / "study.fvp")}
    ).json()
    # the image is a placeholder: named, referenced, and NOT in the store
    assert opened["images"] == []
    assert store.ids() == []
    (placeholder,) = opened["unavailable"]
    assert placeholder["id"] == img_id
    assert placeholder["name"] == "frame.tif"
    assert placeholder["rel"] == "frame.tif"
    assert placeholder["size_bytes"] > 0
    # sample membership, parameters and measures came back regardless
    assert opened["client_state"]["imageGroups"][0]["ids"] == [img_id]
    assert opened["client_state"]["measures"][img_id][0]["text"] == "grain 3"

    # a save with an EMPTY session store must succeed, not 422
    saved = client.post(
        "/api/project/save",
        json={
            "path": str(project_dir / "study.fvp"),
            "client_state": opened["client_state"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["n_unavailable"] == 1

    manifest = _manifest(project_dir / "study.fvp")
    (entry,) = manifest["images"]
    assert entry["id"] == img_id
    assert entry["rel"] == "frame.tif"  # the reference survived the save
    assert entry["size_bytes"] == placeholder["size_bytes"]
    assert entry["unavailable"] is True
    assert manifest["samples"][0]["image_ids"] == [img_id]
    assert manifest["measures"][img_id][0]["text"] == "grain 3"

    # and the project comes back to life when the data does
    tifffile.imwrite(data_dir / "frame.tif", np.full((6, 8), 11, dtype=np.uint16))
    revived = client.post(
        "/api/project/load", json={"path": str(project_dir / "study.fvp")}
    ).json()
    assert revived["unavailable"] == []
    assert [m["id"] for m in revived["images"]] == [img_id]
    np.testing.assert_array_equal(store.get(img_id).data, np.full((6, 8), 11))


def test_an_append_load_cannot_drop_the_open_project_s_missing_images(
    client, tmp_path
) -> None:
    """`replace: false` merges a second project in. The first project's
    unresolved references must survive that, or its next save destroys them."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    a_id = _open_tiff(client, data_dir / "a.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "one.fvp")})
    (data_dir / "a.tif").unlink()
    store.clear()
    opened = client.post(
        "/api/project/load", json={"path": str(tmp_path / "one.fvp")}
    ).json()
    assert [u["id"] for u in opened["unavailable"]] == [a_id]

    # a second project, whose data IS present, appended rather than replacing
    b_id = _open_tiff(client, data_dir / "b.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "two.fvp")})
    store.clear()
    client.post("/api/project/load", json={"path": str(tmp_path / "one.fvp")})
    merged = client.post(
        "/api/project/load",
        json={"path": str(tmp_path / "two.fvp"), "replace": False},
    ).json()

    assert [m["id"] for m in merged["images"]] == [b_id]
    # BOTH the merged file's placeholders and the ones already tracked
    assert [u["id"] for u in merged["unavailable"]] == [a_id]
    assert merged["project"]["path"] == str(tmp_path / "one.fvp")

    saved = client.post(
        "/api/project/save", json={"path": str(tmp_path / "one.fvp")}
    ).json()
    assert saved["n_unavailable"] == 1
    entries = {i["id"]: i for i in _manifest(tmp_path / "one.fvp")["images"]}
    assert entries[a_id]["rel"] == "a.tif"  # the reference is still there
    assert entries[a_id]["unavailable"] is True


def test_locate_folder_resolves_a_moved_sample_and_can_be_repeated(
    client, tmp_path
) -> None:
    """Two samples that moved to two different folders each get their own
    pick — which is why the action is repeatable rather than one-shot."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    a_id = _open_tiff(client, data_dir / "a.tif")
    b_id = _open_tiff(client, data_dir / "b.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "s.fvp")})

    moved_a = tmp_path / "moved_a"
    moved_b = tmp_path / "moved_b"
    moved_a.mkdir()
    moved_b.mkdir()
    (data_dir / "a.tif").rename(moved_a / "a.tif")
    (data_dir / "b.tif").rename(moved_b / "b.tif")

    store.clear()
    opened = client.post(
        "/api/project/load", json={"path": str(tmp_path / "s.fvp")}
    ).json()
    assert {u["id"] for u in opened["unavailable"]} == {a_id, b_id}

    first = client.post("/api/project/relocate", json={"root": str(moved_a)})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [m["id"] for m in body["resolved"]] == [a_id]
    assert [u["id"] for u in body["still_unavailable"]] == [b_id]
    assert body["mismatches"] == []
    assert store.ids() == [a_id]
    assert client.get(f"/api/image/{a_id}/render").status_code == 200

    second = client.post("/api/project/relocate", json={"root": str(moved_b)}).json()
    assert [m["id"] for m in second["resolved"]] == [b_id]
    assert second["still_unavailable"] == []

    # a third call is harmless, and the re-pointed roots persist for the save
    assert client.post(
        "/api/project/relocate", json={"root": str(tmp_path)}
    ).json()["resolved"] == []
    resaved = client.post(
        "/api/project/save", json={"path": str(tmp_path / "s.fvp")}
    ).json()
    assert resaved["n_unavailable"] == 0


def test_locate_folder_reports_a_size_mismatch_instead_of_accepting_it(
    client, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    img_id = _open_tiff(client, data_dir / "frame.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "s.fvp")})
    recorded = _manifest(tmp_path / "s.fvp")["images"][0]["size_bytes"]

    # same shape and dtype (so it parses and fits), different byte count
    moved = tmp_path / "moved"
    moved.mkdir()
    (data_dir / "frame.tif").unlink()
    tifffile.imwrite(
        moved / "frame.tif",
        np.full((6, 8), 11, dtype=np.uint16),
        description="x" * 900,
    )
    assert (moved / "frame.tif").stat().st_size != recorded

    store.clear()
    client.post("/api/project/load", json={"path": str(tmp_path / "s.fvp")})
    body = client.post("/api/project/relocate", json={"root": str(moved)}).json()

    # resolved (the pixels are right) but the discrepancy is REPORTED
    assert [m["id"] for m in body["resolved"]] == [img_id]
    (mismatch,) = body["mismatches"]
    assert mismatch["id"] == img_id
    assert mismatch["rel"] == "frame.tif"
    assert mismatch["expected_bytes"] == recorded
    assert mismatch["actual_bytes"] == (moved / "frame.tif").stat().st_size


def test_locate_folder_distinguishes_wrong_data_from_a_wrong_path(
    client, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    img_id = _open_tiff(client, data_dir / "frame.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "s.fvp")})
    (data_dir / "frame.tif").unlink()

    decoy = tmp_path / "decoy"
    decoy.mkdir()
    (decoy / "frame.tif").write_bytes(b"not a TIFF at all")

    store.clear()
    client.post("/api/project/load", json={"path": str(tmp_path / "s.fvp")})
    body = client.post("/api/project/relocate", json={"root": str(decoy)}).json()
    assert body["resolved"] == []
    assert [u["id"] for u in body["still_unavailable"]] == [img_id]
    assert [r["id"] for r in body["rejected"]] == [img_id]  # found, but wrong


# ── optional sha256 verification (plan #38) ──────────────────────────


def test_save_with_hash_sources_computes_a_real_sha256(client, tmp_path) -> None:
    import hashlib

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    frame = data_dir / "frame.tif"
    _open_tiff(client, frame)
    expected = hashlib.sha256(frame.read_bytes()).hexdigest()

    client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "s.fvp"), "hash_sources": True},
    )
    manifest = _manifest(tmp_path / "s.fvp")
    assert manifest["images"][0]["sha256"] == expected

    # off by default: a second study, no hash_sources at all
    store.clear()
    _open_tiff(client, data_dir / "b.tif")
    client.post("/api/project/save", json={"path": str(tmp_path / "no-hash.fvp")})
    assert _manifest(tmp_path / "no-hash.fvp")["images"][0]["sha256"] is None


def test_relocate_reports_a_hash_mismatch_distinctly_from_a_size_mismatch(
    client, tmp_path
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    img_id = _open_tiff(client, data_dir / "frame.tif")
    client.post(
        "/api/project/save",
        json={"path": str(tmp_path / "s.fvp"), "hash_sources": True},
    )
    recorded = _manifest(tmp_path / "s.fvp")["images"][0]
    (data_dir / "frame.tif").unlink()

    # same shape/dtype/size, different pixels — only the hash catches this
    moved = tmp_path / "moved"
    moved.mkdir()
    tifffile.imwrite(moved / "frame.tif", np.full((6, 8), 99, dtype=np.uint16))
    assert (moved / "frame.tif").stat().st_size == recorded["size_bytes"]

    store.clear()
    client.post("/api/project/load", json={"path": str(tmp_path / "s.fvp")})
    body = client.post("/api/project/relocate", json={"root": str(moved)}).json()

    assert [m["id"] for m in body["resolved"]] == [img_id]
    assert body["mismatches"] == []  # sizes match — no size mismatch
    (hash_mismatch,) = body["hash_mismatches"]
    assert hash_mismatch["id"] == img_id
    assert hash_mismatch["expected_sha256"] == recorded["sha256"]
    assert hash_mismatch["actual_sha256"] != recorded["sha256"]


def test_relocate_error_paths(client, tmp_path) -> None:
    assert client.post(
        "/api/project/relocate", json={"root": str(tmp_path / "nope")}
    ).status_code == 404
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    assert client.post(
        "/api/project/relocate", json={"root": str(a_file)}
    ).status_code == 422
    # nothing open: an empty result, not an error
    assert client.post(
        "/api/project/relocate", json={"root": str(tmp_path)}
    ).json()["resolved"] == []


# ── error paths ──────────────────────────────────────────────────────


def test_save_and_load_error_paths(client, tmp_path) -> None:
    # nothing open and no placeholders → nothing to save
    assert client.post(
        "/api/project/save", json={"path": str(tmp_path / "x.fvp")}
    ).status_code == 422
    # missing file
    assert client.post(
        "/api/project/load", json={"path": str(tmp_path / "nope.fvp")}
    ).status_code == 404
    # a file that is not a project
    junk = tmp_path / "junk.fvp"
    junk.write_text("definitely not a ZIP")
    r = client.post("/api/project/load", json={"path": str(junk)})
    assert r.status_code == 422
    assert "not a readable project" in r.json()["detail"]
    # an unknown payload mode is rejected by the schema, not silently defaulted
    _open_dm4(client, tmp_path / "img.dm4")
    assert client.post(
        "/api/project/save", json={"path": str(tmp_path / "y.fvp"), "mode": "medium"}
    ).status_code == 422
