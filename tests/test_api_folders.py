"""Folder-open endpoint tests (PROJECT_WORKFLOW_PLAN.md item 1, gate G3).

Synthetic tmp trees exercise every rule from the plan's G3 resolution:
first-level subfolders become named groups, deeper files flatten into
them, loose images in the selected folder form their own group,
unsupported files are counted (never silently dropped), and the combined
import is capped at 500 files. A realdata test opens a real vendor
folder so the endpoint is checked against the actual loader, not a mock.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fermiviewer.io.folder_scan import FolderGroupScan, scan_folders
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _write_png(path: Path, value: int = 7) -> Path:
    """A tiny, genuinely-parsable 2x2 grayscale PNG."""
    arr = np.full((2, 2), value, dtype=np.uint8)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, mode="L").save(path, format="PNG")
    return path


# ── pure io.folder_scan tests ───────────────────────────────────────────


def test_flat_folder(tmp_path: Path) -> None:
    _write_png(tmp_path / "a.png")
    _write_png(tmp_path / "b.png")
    result = scan_folders([tmp_path])
    assert result.skipped == 0
    assert not result.truncated
    assert len(result.groups) == 1
    g = result.groups[0]
    assert g.name == tmp_path.name
    assert [p.name for p in g.paths] == ["a.png", "b.png"]


def test_folder_of_subfolders(tmp_path: Path) -> None:
    _write_png(tmp_path / "sub1" / "img1.png")
    _write_png(tmp_path / "sub2" / "img2.png")
    result = scan_folders([tmp_path])
    assert result.skipped == 0
    assert [g.name for g in result.groups] == ["sub1", "sub2"]
    assert [p.name for p in result.groups[0].paths] == ["img1.png"]
    assert [p.name for p in result.groups[1].paths] == ["img2.png"]


def test_nested_deeper_files_flatten_into_first_level_subfolder(
    tmp_path: Path,
) -> None:
    _write_png(tmp_path / "sub1" / "shallow.png")
    _write_png(tmp_path / "sub1" / "deeper" / "deep.png")
    _write_png(tmp_path / "sub1" / "deeper" / "deeper2" / "deepest.png")
    result = scan_folders([tmp_path])
    assert len(result.groups) == 1
    g = result.groups[0]
    assert g.name == "sub1"
    assert {p.name for p in g.paths} == {"shallow.png", "deep.png", "deepest.png"}


def test_loose_images_beside_subfolders(tmp_path: Path) -> None:
    _write_png(tmp_path / "loose.png")
    _write_png(tmp_path / "sub" / "nested.png")
    result = scan_folders([tmp_path])
    names = [g.name for g in result.groups]
    # loose group (named after the selected folder) first, then subfolders
    assert names == [tmp_path.name, "sub"]
    assert [p.name for p in result.groups[0].paths] == ["loose.png"]
    assert [p.name for p in result.groups[1].paths] == ["nested.png"]


def test_unsupported_files_are_counted_not_dropped(tmp_path: Path) -> None:
    _write_png(tmp_path / "img.png")
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / "sub").mkdir()
    _write_png(tmp_path / "sub" / "img2.png")
    (tmp_path / "sub" / "readme.md").write_text("also not an image")
    result = scan_folders([tmp_path])
    assert result.skipped == 2
    total_images = sum(len(g.paths) for g in result.groups)
    assert total_images == 2


def test_empty_folder(tmp_path: Path) -> None:
    result = scan_folders([tmp_path])
    assert result.groups == ()
    assert result.skipped == 0
    assert not result.truncated


def test_nonexistent_path_raises() -> None:
    with pytest.raises(FileNotFoundError):
        scan_folders(["/does/not/exist/anywhere"])


def test_file_passed_where_directory_expected(tmp_path: Path) -> None:
    f = _write_png(tmp_path / "img.png")
    with pytest.raises(NotADirectoryError):
        scan_folders([f])


def test_cap_truncates_at_500_and_flags_it(tmp_path: Path) -> None:
    # scan_folders only checks suffix + is_file(); content need not parse
    # for the pure-layer cap test, so plain touched files are enough here.
    for i in range(510):
        (tmp_path / f"img_{i:04d}.png").write_bytes(b"")
    result = scan_folders([tmp_path])
    assert result.truncated
    total = sum(len(g.paths) for g in result.groups)
    assert total == 500


def test_custom_extensions_argument(tmp_path: Path) -> None:
    (tmp_path / "a.xyz").write_bytes(b"")
    (tmp_path / "b.png").write_bytes(b"")
    result = scan_folders([tmp_path], extensions={".xyz"})
    assert result.skipped == 1  # b.png is now the "unsupported" one
    assert len(result.groups) == 1
    assert [p.name for p in result.groups[0].paths] == ["a.xyz"]


def test_groups_are_frozen_dataclasses(tmp_path: Path) -> None:
    _write_png(tmp_path / "a.png")
    result = scan_folders([tmp_path])
    g = result.groups[0]
    assert isinstance(g, FolderGroupScan)
    with pytest.raises(FrozenInstanceError):
        g.name = "renamed"  # type: ignore[misc]


# ── root group-count tracking (item 27: import seeds projects) ─────────


def test_root_group_count_flat_folder(tmp_path: Path) -> None:
    """A flat folder (loose images only) is ONE group from ONE root —
    the simple case item 27 says must stay unchanged (no parent project)."""
    _write_png(tmp_path / "a.png")
    result = scan_folders([tmp_path])
    assert [r.name for r in result.roots] == [tmp_path.name]
    assert [r.group_count for r in result.roots] == [1]


def test_root_group_count_folder_of_subfolders(tmp_path: Path) -> None:
    """A folder of folders is MULTIPLE groups from ONE root — the signal
    the frontend uses to create a parent project."""
    _write_png(tmp_path / "sub1" / "img1.png")
    _write_png(tmp_path / "sub2" / "img2.png")
    result = scan_folders([tmp_path])
    assert [r.name for r in result.roots] == [tmp_path.name]
    assert [r.group_count for r in result.roots] == [2]


def test_root_group_count_loose_plus_subfolders(tmp_path: Path) -> None:
    """Loose images beside subfolders: the root's own loose-image group
    counts alongside its subfolders' groups."""
    _write_png(tmp_path / "loose.png")
    _write_png(tmp_path / "sub" / "nested.png")
    result = scan_folders([tmp_path])
    assert result.roots[0].group_count == 2  # loose group + "sub" group


def test_root_group_count_empty_folder_is_zero(tmp_path: Path) -> None:
    result = scan_folders([tmp_path])
    assert [r.name for r in result.roots] == [tmp_path.name]
    assert [r.group_count for r in result.roots] == [0]


def test_root_group_count_multiple_selected_dirs_independent(
    tmp_path: Path,
) -> None:
    """Two selected dirs: one flat, one a folder of folders — each root
    reports its own count, independent of the other."""
    flat = tmp_path / "flat"
    nested = tmp_path / "nested"
    _write_png(flat / "a.png")
    _write_png(nested / "sub1" / "b.png")
    _write_png(nested / "sub2" / "c.png")
    result = scan_folders([flat, nested])
    by_name = {r.name: r.group_count for r in result.roots}
    assert by_name == {"flat": 1, "nested": 2}


def test_root_group_counts_adjust_for_the_cap(tmp_path: Path) -> None:
    """When the combined cap truncates mid-way through a root's groups,
    that root's reported count shrinks to what actually survived, and a
    root scanned after the cap was already hit reports zero."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    for i in range(510):
        (first / f"img_{i:04d}.png").write_bytes(b"")
    _write_png(second / "only.png")
    result = scan_folders([first, second])
    assert result.truncated
    by_name = {r.name: r.group_count for r in result.roots}
    assert by_name["first"] == 1  # its one loose-image group still counts
    assert by_name["second"] == 0  # nothing left in the 500-file budget


# ── /api/session/open-folder root results ───────────────────────────────


def test_open_folder_response_includes_roots(
    client: TestClient, tmp_path: Path
) -> None:
    _write_png(tmp_path / "sampleA" / "a1.png")
    _write_png(tmp_path / "sampleB" / "b1.png")
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    body = r.json()
    assert body["roots"] == [{"name": tmp_path.name, "group_count": 2}]


def test_open_folder_response_roots_for_flat_folder(
    client: TestClient, tmp_path: Path
) -> None:
    _write_png(tmp_path / "a.png")
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    body = r.json()
    assert body["roots"] == [{"name": tmp_path.name, "group_count": 1}]


# ── /api/session/open-folder route tests ────────────────────────────────


def test_open_folder_flat(client: TestClient, tmp_path: Path) -> None:
    _write_png(tmp_path / "a.png", value=1)
    _write_png(tmp_path / "b.png", value=2)
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    body = r.json()
    assert body["skipped"] == 0
    assert body["truncated"] is False
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["name"] == tmp_path.name
    assert {img["name"] for img in group["images"]} == {"a.png", "b.png"}
    assert all(img["kind"] == "image" for img in group["images"])


def test_open_folder_subfolders_become_groups(
    client: TestClient, tmp_path: Path
) -> None:
    _write_png(tmp_path / "sampleA" / "a1.png")
    _write_png(tmp_path / "sampleA" / "deeper" / "a2.png")
    _write_png(tmp_path / "sampleB" / "b1.png")
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    body = r.json()
    names = [g["name"] for g in body["groups"]]
    assert names == ["sampleA", "sampleB"]
    sample_a = body["groups"][0]
    assert {img["name"] for img in sample_a["images"]} == {"a1.png", "a2.png"}
    assert body["skipped"] == 0


def test_open_folder_reports_skipped_unsupported(
    client: TestClient, tmp_path: Path
) -> None:
    _write_png(tmp_path / "a.png")
    (tmp_path / "readme.txt").write_text("skip me")
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    assert r.json()["skipped"] == 1


def test_open_folder_empty_directory(client: TestClient, tmp_path: Path) -> None:
    r = client.post("/api/session/open-folder", json={"paths": [str(tmp_path)]})
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == []
    assert body["skipped"] == 0
    assert body["truncated"] is False


def test_open_folder_nonexistent_path_is_404(client: TestClient) -> None:
    r = client.post(
        "/api/session/open-folder", json={"paths": ["/does/not/exist/anywhere"]}
    )
    assert r.status_code == 404


def test_open_folder_file_not_directory_is_422(
    client: TestClient, tmp_path: Path
) -> None:
    f = _write_png(tmp_path / "img.png")
    r = client.post("/api/session/open-folder", json={"paths": [str(f)]})
    assert r.status_code == 422


def test_open_folder_multiple_selected_dirs(
    client: TestClient, tmp_path: Path
) -> None:
    dir_a = tmp_path / "dirA"
    dir_b = tmp_path / "dirB"
    _write_png(dir_a / "x.png")
    _write_png(dir_b / "y.png")
    r = client.post(
        "/api/session/open-folder",
        json={"paths": [str(dir_a), str(dir_b)]},
    )
    assert r.status_code == 200
    body = r.json()
    assert {g["name"] for g in body["groups"]} == {"dirA", "dirB"}


# ── realdata: a real vendor folder, opened through the real loaders ────


@pytest.mark.realdata
def test_open_folder_real_gatan_eels_corpus(
    client: TestClient, rsciio_examples: Path
) -> None:
    """gatan/eels is a flat vendor folder with six genuine DM3/DM4 files,
    none of which hit the known packed-complex-FFT parser limitation (that
    file lives in gatan/microscopy, deliberately excluded here) — so this
    exercises a real folder import end to end against the production
    loaders, not a synthetic fixture."""
    folder = rsciio_examples / "gatan" / "eels"
    r = client.post("/api/session/open-folder", json={"paths": [str(folder)]})
    assert r.status_code == 200
    body = r.json()
    assert body["skipped"] == 0
    assert body["truncated"] is False
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["name"] == "eels"
    names = {img["name"] for img in group["images"]}
    assert names == {
        "rosettasciio_EELS_SI.dm4",
        "rosettasciio_test-EELS_spectrum.dm3",
        "zenodo8403583_apatite_F_Fe_SI.dm4",
        "zenodo8403583_apatite_OKedge_SI.dm4",
        "zenodo8403583_apatite_ZLP_SI.dm4",
        "zenodo8403583_apatite_lowloss_SI.dm4",
    }
