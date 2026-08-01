"""Transactional persistence tests for the JSON + NPZ session pair."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io import session_file


def _entries(value: int = 1) -> list[tuple[str, str, DataStruct]]:
    ds = DataStruct(
        data=np.full((2, 3), value, dtype=np.int16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"value": value},
    )
    return [("image-1", "sample.dm4", ds)]


def _assert_value(path: Path, expected: int) -> None:
    entries, _ = session_file.load_session(path)
    np.testing.assert_array_equal(entries[0][2].data, expected)
    assert entries[0][2].metadata["value"] == expected


def _transaction_files(directory: Path) -> list[Path]:
    return [p for p in directory.iterdir() if p.name.startswith(".work.")]


def test_save_tags_matching_generation_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "work.json"
    session_file.save_session(path, _entries(), {"theme": "dark"})

    manifest = json.loads(path.read_text(encoding="utf-8"))
    with np.load(path.with_suffix(".npz")) as arrays:
        sidecar_generation = str(arrays["__fv_generation__"].item())

    assert manifest["generation"] == sidecar_generation
    entries, state = session_file.load_session(path)
    assert entries[0][0:2] == ("image-1", "sample.dm4")
    assert state == {"theme": "dark"}
    _assert_value(path, 1)
    assert _transaction_files(tmp_path) == []


def test_load_accepts_legacy_pair_without_generation(tmp_path: Path) -> None:
    path = tmp_path / "work.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "images": [
                    {
                        "id": "image-1",
                        "name": "legacy.dm4",
                        "kind": "image",
                        "axes": [
                            {"scale": 1.0, "origin": 0.0, "units": ""},
                            {"scale": 1.0, "origin": 0.0, "units": ""},
                        ],
                        "metadata": {},
                    }
                ],
                "client_state": None,
            }
        ),
        encoding="utf-8",
    )
    np.savez_compressed(path.with_suffix(".npz"), **{"image-1": np.ones((2, 2))})

    entries, state = session_file.load_session(path)
    assert entries[0][1] == "legacy.dm4"
    assert state is None


def test_load_rejects_mismatched_pair(tmp_path: Path) -> None:
    path = tmp_path / "work.json"
    session_file.save_session(path, _entries())
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["generation"] = "different-generation"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="do not match"):
        session_file.load_session(path)


@pytest.mark.parametrize("failed_writer", ["_write_arrays", "_write_manifest"])
def test_staging_failure_preserves_existing_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_writer: str
) -> None:
    path = tmp_path / "work.json"
    session_file.save_session(path, _entries(1))

    def fail(*_args, **_kwargs) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(session_file, failed_writer, fail)
    with pytest.raises(OSError, match="simulated write failure"):
        session_file.save_session(path, _entries(2))

    _assert_value(path, 1)
    assert _transaction_files(tmp_path) == []


@pytest.mark.parametrize("target_suffix", [".json", ".npz"])
def test_install_failure_rolls_back_existing_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_suffix: str
) -> None:
    path = tmp_path / "work.json"
    target = path.with_suffix(target_suffix)
    session_file.save_session(path, _entries(1))
    real_replace = os.replace
    failed = False

    def fail_install(src: str | Path, dst: str | Path) -> None:
        nonlocal failed
        src_path, dst_path = Path(src), Path(dst)
        if (
            not failed
            and src_path.name.endswith(".tmp")
            and dst_path == target
        ):
            failed = True
            raise OSError("simulated install failure")
        real_replace(src, dst)

    monkeypatch.setattr(session_file.os, "replace", fail_install)
    with pytest.raises(OSError, match="simulated install failure"):
        session_file.save_session(path, _entries(2))

    _assert_value(path, 1)
    assert _transaction_files(tmp_path) == []


def test_first_save_failure_leaves_no_partial_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With NO pre-existing pair there is no backup to restore: a failure
    installing the manifest must remove the already-installed NPZ, so a
    reader can never find a sidecar without its commit-marker manifest."""
    path = tmp_path / "work.json"
    real_replace = os.replace

    def fail_manifest_install(src: str | Path, dst: str | Path) -> None:
        if Path(dst) == path:
            raise OSError("simulated install failure")
        real_replace(src, dst)

    monkeypatch.setattr(session_file.os, "replace", fail_manifest_install)
    with pytest.raises(OSError, match="simulated install failure"):
        session_file.save_session(path, _entries(1))

    assert not path.exists()
    assert not path.with_suffix(".npz").exists()
    assert _transaction_files(tmp_path) == []


def test_save_normalizes_a_non_json_suffix(tmp_path: Path) -> None:
    json_path, npz_path = session_file.save_session(
        tmp_path / "work.session", _entries(1)
    )
    assert json_path == tmp_path / "work.json"
    assert npz_path == tmp_path / "work.npz"
    _assert_value(json_path, 1)


def test_load_rejects_sidecar_missing_pixels(tmp_path: Path) -> None:
    path = tmp_path / "work.json"
    session_file.save_session(path, _entries(1))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["images"].append(
        {"id": "phantom", "name": "ghost.dm4", "kind": "image",
         "axes": [], "metadata": {}}
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="missing pixels"):
        session_file.load_session(path)


def test_json_safe_metadata_conversions(tmp_path: Path) -> None:
    # numpy scalars serialize as native values; ndarray values are dropped
    # from dicts but held as None placeholders inside lists so element
    # indices stay aligned with the source list
    ds = DataStruct(
        data=np.zeros((2, 2)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(1.0, units="nm"), AxisCal(1.0, units="nm")),
        metadata={
            "count": np.int32(7),
            "exposure": np.float64(0.25),
            "matrix": np.eye(2),
            "mixed": [1, np.float32(2.5), np.zeros(3)],
        },
    )
    path = tmp_path / "meta.json"
    session_file.save_session(path, [("id-1", "m.dm4", ds)])

    meta = json.loads(path.read_text(encoding="utf-8"))["images"][0]["metadata"]
    assert meta["count"] == 7
    assert meta["exposure"] == 0.25
    assert "matrix" not in meta
    assert meta["mixed"] == [1, 2.5, None]


def test_failed_restore_keeps_backup_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A destination locked through both install and restore (e.g. an
    antivirus scan on Windows) must leave the previous NPZ recoverable
    from its backup instead of deleting the last surviving copy."""
    path = tmp_path / "work.json"
    npz_final = path.with_suffix(".npz")
    session_file.save_session(path, _entries(1))
    real_replace = os.replace

    def locked_npz_destination(src: str | Path, dst: str | Path) -> None:
        if Path(dst) == npz_final:
            raise OSError("simulated: destination locked")
        real_replace(src, dst)

    monkeypatch.setattr(session_file.os, "replace", locked_npz_destination)
    with pytest.raises(OSError, match="could not be fully restored") as exc:
        session_file.save_session(path, _entries(2))
    assert "previous data preserved at" in str(exc.value)

    backups = [
        p for p in _transaction_files(tmp_path) if p.name.endswith(".bak")
    ]
    assert len(backups) == 1
    with np.load(backups[0]) as arrays:
        np.testing.assert_array_equal(arrays["image-1"], 1)
    # The manifest itself was restored; only the locked NPZ is displaced.
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["images"][0]["name"] == "sample.dm4"
