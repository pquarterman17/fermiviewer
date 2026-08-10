"""v1 workspace READER tests — the format FermiViewer no longer writes.

`save_session` was deleted with plan item 32 (ADR 0002 supersedes v1), so the
transactional-save tests that used to live here went with it: v2's single
container is atomic by construction, and `tests/test_project_format.py` owns
that assertion now. What still matters is that an existing v1 pair on a user's
disk keeps opening, which is what this file covers.

Pairs are written by `fixtures.v1_session.write_v1_session`, a test-only writer
that takes its version and pairing key from `session_file`'s own constants.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io import session_file
from fixtures.v1_session import write_v1_session


def _entries(value: int = 1) -> list[tuple[str, str, DataStruct]]:
    ds = DataStruct(
        data=np.full((2, 3), value, dtype=np.int16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"value": value},
    )
    return [("image-1", "sample.dm4", ds)]


def test_round_trips_pixels_dtype_calibration_and_client_state(tmp_path: Path) -> None:
    path, _ = write_v1_session(tmp_path / "work.json", _entries(3), {"theme": "dark"})

    entries, state = session_file.load_session(path)
    assert state == {"theme": "dark"}
    (img_id, name, ds) = entries[0]
    assert (img_id, name) == ("image-1", "sample.dm4")
    np.testing.assert_array_equal(ds.data, np.full((2, 3), 3))
    assert ds.data.dtype == np.int16  # original dtype, not upcast
    assert ds.kind is DataKind.IMAGE
    assert ds.axes == (AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm"))
    assert ds.metadata["value"] == 3


def test_either_half_of_the_pair_names_it(tmp_path: Path) -> None:
    """A user who picks the .npz in a file dialog gets their project, not an
    error about a file that is right there."""
    write_v1_session(tmp_path / "work.json", _entries(1))
    for named in (tmp_path / "work.json", tmp_path / "work.npz", tmp_path / "work"):
        entries, _ = session_file.load_session(named)
        assert entries[0][0] == "image-1"


def test_load_accepts_legacy_pair_without_generation(tmp_path: Path) -> None:
    """Pairs written before the generation tag existed still load."""
    path, _ = write_v1_session(tmp_path / "work.json", _entries(1), generation=None)
    assert "generation" in json.loads(path.read_text(encoding="utf-8"))
    entries, state = session_file.load_session(path)
    assert entries[0][1] == "sample.dm4"
    assert state is None


def test_load_rejects_mismatched_pair(tmp_path: Path) -> None:
    """The one v1 integrity check worth keeping: two files that were
    separated in transfer and re-paired with a stranger."""
    path, _ = write_v1_session(tmp_path / "work.json", _entries())
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["generation"] = "adifferentgeneration"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="do not match"):
        session_file.load_session(path)


def test_load_rejects_sidecar_missing_pixels(tmp_path: Path) -> None:
    path, _ = write_v1_session(tmp_path / "work.json", _entries(1))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["images"].append(
        {"id": "phantom", "name": "ghost.dm4", "kind": "image",
         "axes": [], "metadata": {}}
    )
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="missing pixels"):
        session_file.load_session(path)


def test_load_rejects_an_unsupported_version(tmp_path: Path) -> None:
    path, _ = write_v1_session(tmp_path / "work.json", _entries(1))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = 99
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported session version"):
        session_file.load_session(path)


@pytest.mark.parametrize("orphan", [".json", ".npz"])
def test_a_half_pair_names_the_missing_half(tmp_path: Path, orphan: str) -> None:
    """v1's structural weakness, stated as a test: half a pair is unloadable.
    This is the failure the single-file `.fvp` container exists to retire."""
    write_v1_session(tmp_path / "work.json", _entries(1))
    (tmp_path / f"work{orphan}").unlink()
    with pytest.raises(FileNotFoundError, match="manifest|sidecar"):
        session_file.load_session(tmp_path / "work.json")


def test_the_writer_is_gone(tmp_path: Path) -> None:
    """v1 is read-only legacy (plan #32). A save path that still existed would
    be a second format anything could accidentally keep writing."""
    assert not hasattr(session_file, "save_session")
    assert session_file.__all__ == ["GENERATION_KEY", "V1_VERSION", "load_session"]
