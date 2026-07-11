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


def test_install_failure_rolls_back_existing_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "work.json"
    session_file.save_session(path, _entries(1))
    real_replace = os.replace
    failed = False

    def fail_manifest_install(src: str | Path, dst: str | Path) -> None:
        nonlocal failed
        src_path, dst_path = Path(src), Path(dst)
        if not failed and src_path.name.endswith(".tmp") and dst_path == path:
            failed = True
            raise OSError("simulated install failure")
        real_replace(src, dst)

    monkeypatch.setattr(session_file.os, "replace", fail_manifest_install)
    with pytest.raises(OSError, match="simulated install failure"):
        session_file.save_session(path, _entries(2))

    _assert_value(path, 1)
    assert _transaction_files(tmp_path) == []
