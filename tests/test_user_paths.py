"""The API path policy (`io.user_paths`) and its route wiring.

Covers the boundary itself — canonicalisation, the `FV_DATA_ROOTS` lockdown
switch, the config-dir exclusion, and slug containment — plus the two
properties the routes are there to guarantee: a refused path is a 422 and
never a 500, and a workspace slug cannot address anything outside the
workspaces directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.io.user_paths import (
    PathPolicyError,
    data_roots,
    safe_config_path,
    safe_data_path,
    safe_data_paths,
)
from fermiviewer.project_session import project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minitiff import write_fei_tiff


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("FV_DATA_ROOTS", raising=False)
    store.clear()
    project.clear()
    yield
    store.clear()
    project.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _image(tmp_path: Path) -> Path:
    """A tiny readable TIFF, so a path that passes policy also opens."""
    return write_fei_tiff(
        tmp_path / "img.tif",
        np.arange(16, dtype=np.uint16).reshape(4, 4),
    )


# ── canonicalisation ─────────────────────────────────────────────────


def test_traversal_is_collapsed_not_followed(tmp_path: Path) -> None:
    """`..` is resolved away, so the checked path is the opened path."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    weird = str(nested / ".." / ".." / "a")
    assert safe_data_path(weird, where="p") == str(tmp_path / "a")


def test_symlink_is_resolved_to_its_target(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert safe_data_path(str(link), where="p") == str(real)


def test_empty_and_nul_paths_are_refused() -> None:
    with pytest.raises(PathPolicyError, match="must not be empty"):
        safe_data_path("   ", where="p")
    with pytest.raises(PathPolicyError, match="NUL"):
        safe_data_path("/tmp/x\x00.tif", where="p")


def test_relative_paths_still_resolve_against_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deliberate contract kept by test_watch's relative-dir test — the
    policy canonicalises such a path rather than rejecting it."""
    (tmp_path / "incoming").mkdir()
    monkeypatch.chdir(tmp_path)
    assert safe_data_path("incoming", where="p") == str(
        (tmp_path / "incoming").resolve()
    )


def test_list_form_names_the_offending_index(tmp_path: Path) -> None:
    with pytest.raises(PathPolicyError, match=r"paths\[1\]"):
        safe_data_paths([str(tmp_path), ""], where="paths")


# ── FV_DATA_ROOTS lockdown ───────────────────────────────────────────


def test_unset_roots_allow_any_volume_path(tmp_path: Path) -> None:
    assert data_roots() == ()
    assert safe_data_path(str(tmp_path), where="p") == str(tmp_path.resolve())


def test_configured_roots_confine_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "corpus"
    allowed.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setenv("FV_DATA_ROOTS", str(allowed))

    assert safe_data_path(str(allowed / "x.tif"), where="p").startswith(
        str(allowed)
    )
    with pytest.raises(PathPolicyError, match="outside the roots"):
        safe_data_path(str(outside / "x.tif"), where="p")


def test_configured_root_is_not_a_bare_string_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/data` must not claim `/database` — containment is per component."""
    allowed = tmp_path / "data"
    allowed.mkdir()
    sibling = tmp_path / "database"
    sibling.mkdir()
    monkeypatch.setenv("FV_DATA_ROOTS", str(allowed))
    with pytest.raises(PathPolicyError, match="outside the roots"):
        safe_data_path(str(sibling / "x.tif"), where="p")


def test_traversal_out_of_a_configured_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "corpus"
    allowed.mkdir()
    monkeypatch.setenv("FV_DATA_ROOTS", str(allowed))
    with pytest.raises(PathPolicyError, match="outside the roots"):
        safe_data_path(str(allowed / ".." / "secret.tif"), where="p")


def test_multiple_roots_are_each_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    monkeypatch.setenv("FV_DATA_ROOTS", os.pathsep.join([str(one), str(two)]))
    assert safe_data_path(str(one / "a.tif"), where="p")
    assert safe_data_path(str(two / "b.tif"), where="p")
    with pytest.raises(PathPolicyError):
        safe_data_path(str(tmp_path / "three" / "c.tif"), where="p")


# ── the config dir is never user data ────────────────────────────────


def test_config_dir_is_refused_as_a_data_path(tmp_path: Path) -> None:
    """Workspaces are reached through their own endpoints; the generic
    open/save surface must not be a second way in."""
    from fermiviewer.usermeta import config_dir

    target = config_dir() / "workspaces" / "secret.fvp"
    with pytest.raises(PathPolicyError, match="config directory"):
        safe_data_path(str(target), where="p")


# ── derived (slug) paths ─────────────────────────────────────────────


def test_safe_config_path_confines_a_name(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    root.mkdir()
    assert safe_config_path("ok.fvp", root, where="w") == root / "ok.fvp"


@pytest.mark.parametrize(
    "name", ["../escape.fvp", "../../etc/passwd", "sub/../../out.fvp", ""]
)
def test_safe_config_path_refuses_escapes(tmp_path: Path, name: str) -> None:
    root = tmp_path / "workspaces"
    root.mkdir()
    with pytest.raises(PathPolicyError):
        safe_config_path(name, root, where="w")


def test_workspace_slug_cannot_escape_the_workspaces_dir() -> None:
    from fermiviewer import workspaces

    with pytest.raises(PathPolicyError):
        workspaces.project_path("../../escaped")
    # stored_path reads index.json, which can be edited out-of-band: a bad
    # entry reads as gone so one row cannot break the whole listing.
    assert workspaces.stored_path("../../escaped") is None


# ── route wiring: refused paths are 4xx, never 5xx ───────────────────


@pytest.mark.api
def test_open_rejects_a_config_dir_path(client: TestClient) -> None:
    from fermiviewer.usermeta import config_dir

    r = client.post(
        "/api/session/open", json={"paths": [str(config_dir() / "x.tif")]}
    )
    assert r.status_code == 422, r.text
    assert "config directory" in r.text


@pytest.mark.api
def test_open_folder_reports_the_bad_index(client: TestClient) -> None:
    r = client.post("/api/session/open-folder", json={"paths": ["", "/tmp"]})
    assert r.status_code == 422, r.text
    assert "paths[0]" in r.text


@pytest.mark.api
def test_watch_start_rejects_a_config_dir(client: TestClient) -> None:
    from fermiviewer.usermeta import config_dir

    r = client.post(
        "/api/watch/start",
        json={
            "dir": str(config_dir()),
            "steps": [{"op": "gaussian", "params": {"sigma": 1.0}}],
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.api
def test_project_save_outside_configured_roots_is_422(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FV_DATA_ROOTS", str(tmp_path / "corpus"))
    (tmp_path / "corpus").mkdir()
    r = client.post(
        "/api/project/save", json={"path": str(tmp_path / "out.fvp")}
    )
    assert r.status_code == 422, r.text
    assert "outside the roots" in r.text


@pytest.mark.api
def test_open_still_works_within_the_policy(
    client: TestClient, tmp_path: Path
) -> None:
    """The policy must not get in the way of the product's normal path."""
    img = _image(tmp_path)
    r = client.post("/api/session/open", json={"paths": [str(img)]})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
