"""`.fvp` v2 project container — ADR 0002's verification list.

Covers: single-container layout, round-trip deep-equality, unknown-key
preservation, path-traversal rejection, unresolved references surviving a
save (the no-data-loss assertion), interrupted-save atomicity, a
Windows-written hint resolving on POSIX, v1 -> v2 migration (plan #32), the
client_state split that migration shares with every save, and re-pointing a
moved data root (plan #34).

The route-level surface — Save Project / Export Project Bundle / Open
Project… / Locate folder… — is in tests/test_api_project_io.py.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import tifffile

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io import project_file, project_resolve
from fermiviewer.io import project_paths as paths
from fermiviewer.io.project_file import (
    ProjectFormatError,
    ProjectImage,
    load_project,
    save_project,
)
from fermiviewer.io.project_manifest import MANIFEST_NAME, schema_bytes
from fermiviewer.io.project_sections import join_sections, split_client_state
from fixtures.v1_session import write_v1_session

ROOT = Path(__file__).resolve().parents[1]

SAMPLES: list[dict[str, Any]] = [
    {
        "id": "s1",
        "name": "Sample A",
        "image_ids": ["img1", "gone-long-ago"],
        "parent": None,
        "params": {
            "anneal_T": {"value": 450.0, "unit": "degC"},
            "atmosphere": {"value": "Ar", "unit": None},
        },
        "color": "#ff8800",
    }
]
MEASURES: dict[str, list[dict[str, Any]]] = {
    "img1": [
        {
            "id": "m1",
            "kind": "polygon",
            "pts": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.2}, {"x": 0.4, "y": 0.7}],
            "text": "grain 3",
            "color": "#00ccff",
        }
    ]
}
UI_STATE: dict[str, Any] = {
    "views": {"img1": {"zoom": 2.5}},
    "browseScale": 1.5,
    "sbsPanes": 2,
}


def _image(
    value: int = 1, name: str = "frame.tif", img_id: str = "img1"
) -> tuple[str, str, DataStruct]:
    ds = DataStruct(
        data=np.full((3, 4), value, dtype=np.uint16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"vendor": "acme", "beam_kv": 200},
    )
    return (img_id, name, ds)


def _sourced(path: Path, value: int = 7) -> tuple[str, str, DataStruct]:
    """A real on-disk TIFF plus the store triple that references it."""
    tifffile.imwrite(path, np.full((3, 4), value, dtype=np.uint16))
    ds = DataStruct(
        data=np.full((3, 4), value, dtype=np.uint16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        metadata={"parser": "tiff", "source": str(path)},
    )
    return ("img1", path.name, ds)


def _derived() -> tuple[str, str, DataStruct]:
    ds = DataStruct(
        data=np.full((3, 4), 9, dtype=np.float32),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        # what ops/catalogue.py writes: "source" is the operation, not a path
        metadata={"parser": "derived", "filter_kind": "gaussian", "source": "gaussian"},
    )
    return ("img2", "frame.tif (gaussian)", ds)


def _manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        loaded: dict[str, Any] = json.loads(zf.read(MANIFEST_NAME))
    return loaded


def _rewrite_manifest(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    """Edit manifest.json in place inside an existing container."""
    with zipfile.ZipFile(path) as zf:
        blobs = {name: zf.read(name) for name in zf.namelist()}
    manifest = json.loads(blobs[MANIFEST_NAME])
    mutate(manifest)
    blobs[MANIFEST_NAME] = json.dumps(manifest).encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in blobs.items():
            zf.writestr(name, blob)


# ── container shape ──────────────────────────────────────────────────


def test_container_is_a_single_file_with_only_known_entries(tmp_path: Path) -> None:
    """One file, so there is no commit ORDERING to get right (ADR 0002 §1).

    v1 had to write the .npz before the .json because the manifest was the
    commit marker for a pair. A single container retires that entirely.
    """
    path = save_project(tmp_path / "study.fvp", [_image()])

    assert path == tmp_path / "study.fvp"
    assert [p.name for p in tmp_path.iterdir()] == ["study.fvp"]  # no sidecar, no temp
    with zipfile.ZipFile(path) as zf:
        assert sorted(zf.namelist()) == ["manifest.json", "pixels/img1.npy"]
        assert zf.getinfo("pixels/img1.npy").compress_type == zipfile.ZIP_DEFLATED
    assert zipfile.is_zipfile(path)  # inspectable with standard tools


def test_extension_is_applied_and_manifest_is_self_describing(tmp_path: Path) -> None:
    path = save_project(tmp_path / "study", [_image()], name="Study 1")

    assert path.name == "study.fvp"
    manifest = _manifest(path)
    assert manifest["format"] == "fermiviewer-project"
    assert manifest["version"] == 2
    assert manifest["payload_mode"] == "light"
    assert manifest["name"] == "Study 1"
    assert len(manifest["generation"]) >= 8
    assert manifest["saved_at"].startswith("20")


# ── round trip ───────────────────────────────────────────────────────


def test_round_trip_is_deep_equal(tmp_path: Path) -> None:
    path = save_project(
        tmp_path / "study.fvp",
        [_image(value=5)],
        samples=SAMPLES,
        measures=MEASURES,
        ui_state=UI_STATE,
        primary_param="anneal_T",
        name="Study 1",
    )
    loaded = load_project(path)

    assert [dict(s) for s in loaded.samples] == SAMPLES
    assert loaded.measures == MEASURES
    assert loaded.ui_state == UI_STATE
    assert loaded.primary_param == "anneal_T"
    assert loaded.name == "Study 1"
    assert loaded.payload_mode == "light"

    (img,) = loaded.images
    assert (img.id, img.name, img.kind) == ("img1", "frame.tif", DataKind.IMAGE)
    assert img.axes == (AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm"))
    assert img.metadata == {"vendor": "acme", "beam_kv": 200}
    assert img.unavailable is False
    np.testing.assert_array_equal(img.data, np.full((3, 4), 5, dtype=np.uint16))

    # the shape routes/session_io.py already restores into the session store
    (entry_id, entry_name, ds) = loaded.entries[0]
    assert (entry_id, entry_name) == ("img1", "frame.tif")
    assert ds.metadata == {"vendor": "acme", "beam_kv": 200}
    np.testing.assert_array_equal(ds.data, img.data)


def test_sample_membership_of_a_missing_image_is_kept(tmp_path: Path) -> None:
    """The schema says readers prune for display but MUST keep unknown member
    ids on save — regrouping on a machine without the data must not edit it."""
    first = save_project(tmp_path / "study.fvp", [_image()], samples=SAMPLES)
    loaded = load_project(first)
    save_project(first, loaded.images, samples=loaded.samples)

    assert load_project(first).samples[0]["image_ids"] == ["img1", "gone-long-ago"]


def test_dtype_and_non_image_kinds_survive(tmp_path: Path) -> None:
    cube = DataStruct(
        data=np.arange(24, dtype=np.float32).reshape(2, 3, 4),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, units="nm"), AxisCal(1.0, units="nm"), AxisCal(10.0, 0.0, "eV")),
        metadata={},
    )
    path = save_project(tmp_path / "study.fvp", [("cube", "eds.bcf", cube)])

    (img,) = load_project(path).images
    assert img.kind is DataKind.SPECTRUM_IMAGE
    assert img.data is not None and img.data.dtype == np.float32
    assert img.axes[-1] == AxisCal(10.0, 0.0, "eV")
    np.testing.assert_array_equal(img.data, cube.data)


# ── unknown-key preservation (ADR 0002 §6) ───────────────────────────


def test_unknown_keys_round_trip_verbatim(tmp_path: Path) -> None:
    """A project written by a newer build and re-saved by this one must not
    lose what this one did not understand — at every level."""
    path = save_project(tmp_path / "study.fvp", [_image()], samples=SAMPLES)

    def inject(manifest: dict[str, Any]) -> None:
        manifest["future_section"] = {"deconvolution": [1, 2, 3]}
        manifest["notes"] = "written by a newer build"
        manifest["images"][0]["future_flag"] = True
        manifest["images"][0]["sha256"] = "a" * 64
        manifest["samples"][0]["future_field"] = {"nested": "kept"}

    _rewrite_manifest(path, inject)

    loaded = load_project(path)
    assert loaded.unknown_keys["future_section"] == {"deconvolution": [1, 2, 3]}
    assert loaded.unknown_keys["notes"] == "written by a newer build"
    assert loaded.images[0].extra == {"future_flag": True, "sha256": "a" * 64}

    save_project(
        path,
        loaded.images,
        samples=loaded.samples,
        unknown_keys=loaded.unknown_keys,
    )
    manifest = _manifest(path)
    assert manifest["future_section"] == {"deconvolution": [1, 2, 3]}
    assert manifest["notes"] == "written by a newer build"
    assert manifest["images"][0]["future_flag"] is True
    assert manifest["images"][0]["sha256"] == "a" * 64
    assert manifest["samples"][0]["future_field"] == {"nested": "kept"}


def test_carried_keys_cannot_shadow_a_modelled_key(tmp_path: Path) -> None:
    """Preservation must not become a write primitive: a stale carried `id`
    or `version` cannot overwrite what this build computed."""
    path = save_project(
        tmp_path / "study.fvp",
        [_image()],
        unknown_keys={"version": 99, "images": [], "future": "kept"},
    )

    manifest = _manifest(path)
    assert manifest["version"] == 2
    assert len(manifest["images"]) == 1
    assert manifest["future"] == "kept"


# ── path traversal (untrusted input) ─────────────────────────────────


@pytest.mark.parametrize(
    "rel",
    [
        "/etc/passwd",
        "../../../etc/passwd",
        "sub/../../escape.tif",
        "C:/Windows/win.ini",
        "..\\..\\escape.tif",
        "//host/share/secret.tif",
    ],
)
def test_unsafe_rel_is_rejected(tmp_path: Path, rel: str) -> None:
    """A .fvp is a file a stranger can send; a reference that is absolute or
    escapes the data root must never reach the filesystem."""
    path = save_project(tmp_path / "study.fvp", [_image()])

    def make_unsafe(manifest: dict[str, Any]) -> None:
        manifest["images"][0]["embedded"] = False
        manifest["images"][0]["rel"] = rel

    _rewrite_manifest(path, make_unsafe)

    with pytest.raises(ProjectFormatError) as excinfo:
        load_project(path)
    assert "images[0].rel" in str(excinfo.value)


def test_saving_an_unsafe_carried_rel_is_refused(tmp_path: Path) -> None:
    """The check guards writes too — a save must not launder a hostile
    reference back onto disk."""
    hostile = ProjectImage(
        id="img1",
        name="frame.tif",
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        rel="../../../etc/passwd",
    )
    with pytest.raises(ProjectFormatError, match=r"images\[0\].rel"):
        save_project(tmp_path / "study.fvp", [hostile])


def test_duplicate_image_ids_are_refused(tmp_path: Path) -> None:
    """The id IS the pixel entry name: a repeat would write a duplicate ZIP
    entry and the second image would read back the first one's pixels."""
    with pytest.raises(ProjectFormatError, match="duplicate image id"):
        save_project(tmp_path / "study.fvp", [_image(value=1), _image(value=2)])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("img_id", ["../escape", "sub/img", "back\\slash", "..", ""])
def test_unsafe_image_ids_are_refused_on_save_and_load(
    tmp_path: Path, img_id: str
) -> None:
    """`unzip project.fvp` is an advertised way to inspect a project, so an id
    that is not a single path component must never reach a ZIP entry name."""
    with pytest.raises(ProjectFormatError, match=r"images\[0\].id"):
        save_project(tmp_path / "study.fvp", [_image(img_id=img_id)])

    path = save_project(tmp_path / "study.fvp", [_image()])
    _rewrite_manifest(path, lambda m: m["images"][0].__setitem__("id", img_id))
    with pytest.raises(ProjectFormatError, match=r"images\[0\].id"):
        load_project(path)


def test_embedded_payload_is_never_unpickled(tmp_path: Path) -> None:
    """An object-array .npy in a file a stranger sent is arbitrary code
    execution, not an image."""
    path = save_project(tmp_path / "study.fvp", [_image()])
    with zipfile.ZipFile(path) as zf:
        blobs = {name: zf.read(name) for name in zf.namelist()}
    pickled = io.BytesIO()
    np.save(pickled, np.array([{"exec": "me"}], dtype=object), allow_pickle=True)
    blobs["pixels/img1.npy"] = pickled.getvalue()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in blobs.items():
            zf.writestr(name, blob)

    with pytest.raises(ProjectFormatError, match="unreadable pixel payload"):
        load_project(path)


# ── payload modes ────────────────────────────────────────────────────


def test_light_mode_references_sources_and_embeds_derived(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sourced = _sourced(data_dir / "frame.tif")

    path = save_project(
        tmp_path / "study.fvp",
        [sourced, _derived()],
        mode="light",
        data_root=data_dir,
    )

    manifest = _manifest(path)
    source_entry, derived_entry = manifest["images"]
    assert source_entry["embedded"] is False
    assert source_entry["rel"] == "frame.tif"
    assert source_entry["size_bytes"] == (data_dir / "frame.tif").stat().st_size
    assert manifest["data_root_hint"] == data_dir.resolve().as_posix()
    # A derived image has no file of its own: embedded in light mode too,
    # otherwise the save would silently discard it.
    assert derived_entry["embedded"] is True
    assert derived_entry["rel"] is None
    assert derived_entry["derived_from"] is None
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["manifest.json", "pixels/img2.npy"]

    loaded = load_project(path)
    assert [img.unavailable for img in loaded.images] == [False, False]
    np.testing.assert_array_equal(loaded.images[0].data, np.full((3, 4), 7, np.uint16))
    assert loaded.images[0].resolved_path == str(data_dir / "frame.tif")


def test_bundle_mode_embeds_everything_and_keeps_references(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    sourced = _sourced(data_dir / "frame.tif")

    path = save_project(
        tmp_path / "study.fvp", [sourced], mode="bundle", data_root=data_dir
    )

    manifest = _manifest(path)
    assert manifest["payload_mode"] == "bundle"
    assert manifest["images"][0]["embedded"] is True
    # references are still recorded, so a bundle can be re-saved as light
    assert manifest["images"][0]["rel"] == "frame.tif"
    with zipfile.ZipFile(path) as zf:
        assert "pixels/img1.npy" in zf.namelist()

    # self-contained: still loads with the sources gone
    (data_dir / "frame.tif").unlink()
    (img,) = load_project(path).images
    assert img.unavailable is False
    np.testing.assert_array_equal(img.data, np.full((3, 4), 7, np.uint16))


def test_data_root_is_derived_when_not_declared(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "run1"
    data_dir.mkdir(parents=True)
    path = save_project(tmp_path / "study.fvp", [_sourced(data_dir / "frame.tif")])

    manifest = _manifest(path)
    assert manifest["data_root_hint"] == data_dir.resolve().as_posix()
    assert manifest["images"][0]["rel"] == "frame.tif"


def test_manifest_calibration_wins_over_the_referenced_file(tmp_path: Path) -> None:
    """Only pixels come from disk, so a recalibration survives a light save."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    img_id, name, ds = _sourced(data_dir / "frame.tif")
    recalibrated = DataStruct(
        data=ds.data,
        kind=ds.kind,
        axes=(AxisCal(2.5, units="um"), AxisCal(2.5, units="um")),
        metadata=dict(ds.metadata),
    )
    path = save_project(
        tmp_path / "study.fvp", [(img_id, name, recalibrated)], data_root=data_dir
    )

    (loaded_img,) = load_project(path).images
    assert loaded_img.embedded is False
    assert loaded_img.axes == (AxisCal(2.5, units="um"), AxisCal(2.5, units="um"))


# ── missing sources (ADR 0002 §4) ────────────────────────────────────


def test_unresolved_reference_loads_unavailable_and_survives_a_save(
    tmp_path: Path,
) -> None:
    """The no-data-loss assertion: opening a project without its data and
    pressing save must not be able to destroy the reference."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    sourced = _sourced(data_dir / "frame.tif")

    path = save_project(
        project_dir / "study.fvp",
        [sourced],
        data_root=data_dir,
        samples=SAMPLES,
        measures=MEASURES,
    )
    (data_dir / "frame.tif").unlink()

    loaded = load_project(path)
    (img,) = loaded.images
    assert img.unavailable is True
    assert img.data is None and img.datastruct is None
    assert loaded.unavailable_ids == ("img1",)
    assert loaded.entries == []  # nothing to push into the session store
    # everything except the pixels is intact
    assert (img.id, img.name, img.rel) == ("img1", "frame.tif", "frame.tif")
    assert img.size_bytes is not None and img.size_bytes > 0
    assert img.axes == (AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm"))
    assert loaded.measures == MEASURES
    assert loaded.samples[0]["params"]["anneal_T"] == {"value": 450.0, "unit": "degC"}

    # re-save from the placeholder, then confirm the reference is still there
    save_project(
        path,
        loaded.images,
        data_root=loaded.data_root_hint,
        samples=loaded.samples,
        measures=loaded.measures,
    )
    again = load_project(path)
    (again_img,) = again.images
    assert again_img.unavailable is True
    assert again_img.rel == "frame.tif"
    assert again_img.size_bytes == img.size_bytes
    assert again.data_root_hint == loaded.data_root_hint
    assert again.measures == MEASURES

    # and it comes back to life when the data does
    tifffile.imwrite(data_dir / "frame.tif", np.full((3, 4), 7, dtype=np.uint16))
    (revived,) = load_project(path).images
    assert revived.unavailable is False
    np.testing.assert_array_equal(revived.data, np.full((3, 4), 7, np.uint16))


def test_reference_survives_even_with_no_data_root_declared(tmp_path: Path) -> None:
    """A save that cannot derive any root at all still keeps the rel."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = save_project(
        tmp_path / "study.fvp", [_sourced(data_dir / "frame.tif")], data_root=data_dir
    )
    (data_dir / "frame.tif").unlink()

    loaded = load_project(path)
    save_project(path, loaded.images)  # no data_root: nothing exists to derive from

    manifest = _manifest(path)
    assert manifest["data_root_hint"] is None
    assert manifest["images"][0]["rel"] == "frame.tif"
    assert manifest["images"][0]["unavailable"] is True


def test_a_source_that_no_longer_matches_degrades_to_a_placeholder(
    tmp_path: Path,
) -> None:
    """A re-pointed folder holding different data must not raise — the image
    becomes a placeholder the user can re-point again."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = save_project(
        tmp_path / "study.fvp", [_sourced(data_dir / "frame.tif")], data_root=data_dir
    )
    (data_dir / "frame.tif").write_bytes(b"not a TIFF at all")

    (img,) = load_project(path).images
    assert img.unavailable is True
    assert img.rel == "frame.tif"


# ── path portability ─────────────────────────────────────────────────


def test_windows_hint_resolves_via_the_project_directory(tmp_path: Path) -> None:
    """A project written on Windows opens on POSIX: the `C:/...` hint is
    unusable here, so resolution falls through to the .fvp's own directory."""
    sourced = _sourced(tmp_path / "frame.tif")
    path = save_project(tmp_path / "study.fvp", [sourced], data_root=tmp_path)

    def windows_hint(manifest: dict[str, Any]) -> None:
        manifest["data_root_hint"] = "C:/Users/pq/OneDrive/data/study"
        manifest["images"][0]["source"] = "C:\\Users\\pq\\OneDrive\\data\\study\\frame.tif"

    _rewrite_manifest(path, windows_hint)

    loaded = load_project(path)
    (img,) = loaded.images
    assert img.unavailable is False
    assert img.resolved_path == str(tmp_path / "frame.tif")
    assert loaded.data_root_hint == "C:/Users/pq/OneDrive/data/study"


def test_backslash_reference_is_normalised_on_load(tmp_path: Path) -> None:
    nested = tmp_path / "run1"
    nested.mkdir()
    sourced = _sourced(nested / "frame.tif")
    path = save_project(tmp_path / "study.fvp", [sourced], data_root=tmp_path)
    assert _manifest(path)["images"][0]["rel"] == "run1/frame.tif"

    _rewrite_manifest(
        path, lambda m: m["images"][0].__setitem__("rel", "run1\\frame.tif")
    )

    (img,) = load_project(path).images
    assert img.rel == "run1/frame.tif"
    assert img.unavailable is False


def test_a_windows_hint_is_preserved_verbatim_on_re_save(tmp_path: Path) -> None:
    """The machine that CAN use the hint must still get it back."""
    path = save_project(
        tmp_path / "study.fvp", [_image()], data_root="C:\\data\\study"
    )
    assert _manifest(path)["data_root_hint"] == "C:/data/study"

    loaded = load_project(path)
    save_project(path, loaded.images, data_root=loaded.data_root_hint)
    assert _manifest(path)["data_root_hint"] == "C:/data/study"


# ── atomicity (ADR 0002 §1) ──────────────────────────────────────────


def test_interrupted_save_leaves_the_previous_project_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = save_project(tmp_path / "study.fvp", [_image(value=1)], name="first")
    before = path.read_bytes()

    def boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full mid-write")

    monkeypatch.setattr(project_file.np, "save", boom)
    with pytest.raises(OSError, match="disk full mid-write"):
        save_project(tmp_path / "study.fvp", [_image(value=2)], name="second")
    monkeypatch.undo()

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["study.fvp"]  # staging cleaned up
    loaded = load_project(path)
    assert loaded.name == "first"
    np.testing.assert_array_equal(loaded.images[0].data, np.full((3, 4), 1, np.uint16))


def test_a_manifest_we_could_not_read_back_is_never_committed(tmp_path: Path) -> None:
    """Save validates against the schema before committing, so an invalid
    section fails loudly instead of producing an unloadable file."""
    path = save_project(tmp_path / "study.fvp", [_image()])
    before = path.read_bytes()

    with pytest.raises(ProjectFormatError) as excinfo:
        save_project(
            tmp_path / "study.fvp",
            [_image()],
            measures={"img1": [{"id": "m1", "kind": "trapezoid", "pts": []}]},
        )
    assert "measures.img1[0].kind" in str(excinfo.value)
    assert path.read_bytes() == before


# ── schema validation (plan #31) ─────────────────────────────────────


def test_packaged_schema_is_identical_to_the_published_one() -> None:
    """The shipped contract and the enforced one cannot drift apart."""
    published = (ROOT / "docs" / "schema" / "fvp-v2.schema.json").read_bytes()
    assert schema_bytes() == published


def test_schema_error_names_the_offending_json_path(tmp_path: Path) -> None:
    path = save_project(tmp_path / "study.fvp", [_image(), _image(img_id="img2")])

    _rewrite_manifest(path, lambda m: m["images"][1].__setitem__("axes", []))

    with pytest.raises(ProjectFormatError, match=r"images\[1\].axes"):
        load_project(path)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m.pop("images"), "images"),
        (lambda m: m.__setitem__("payload_mode", "sparse"), "payload_mode"),
        (lambda m: m["images"][0].__setitem__("kind", "hologram"), "images[0].kind"),
        (lambda m: m["images"][0].__setitem__("id", ""), "images[0].id"),
        (lambda m: m["samples"].append({"name": "no id"}), "samples[0]"),
        (lambda m: m.__setitem__("ui_state", ["not", "an", "object"]), "ui_state"),
    ],
)
def test_invalid_manifests_are_refused(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], expected: str
) -> None:
    path = save_project(tmp_path / "study.fvp", [_image()], samples=[])
    _rewrite_manifest(path, mutate)

    with pytest.raises(ProjectFormatError) as excinfo:
        load_project(path)
    assert expected in str(excinfo.value)


def test_a_container_missing_pixels_it_claims_to_embed_is_refused(
    tmp_path: Path,
) -> None:
    path = save_project(tmp_path / "study.fvp", [_image()])
    with zipfile.ZipFile(path) as zf:
        manifest = zf.read(MANIFEST_NAME)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, manifest)  # pixels/img1.npy dropped

    with pytest.raises(ProjectFormatError, match="marked embedded"):
        load_project(path)


def test_embedded_pixels_that_contradict_the_kind_are_refused(tmp_path: Path) -> None:
    path = save_project(tmp_path / "study.fvp", [_image()])
    _rewrite_manifest(path, lambda m: m["images"][0].__setitem__("kind", "spectrum"))

    with pytest.raises(ProjectFormatError, match="does not describe a spectrum"):
        load_project(path)


# ── rejecting things that are not projects ───────────────────────────


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_project(tmp_path / "absent.fvp")


def test_a_non_zip_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "study.fvp"
    path.write_text("this is not a ZIP", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="not a readable .fvp ZIP container"):
        load_project(path)


def test_a_zip_without_a_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "study.fvp"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(ProjectFormatError, match="contains no manifest.json"):
        load_project(path)


def test_an_unrelated_json_manifest_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "study.fvp"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(MANIFEST_NAME, json.dumps({"hello": "world"}))
    with pytest.raises(ProjectFormatError, match="not a FermiViewer project manifest"):
        load_project(path)


def test_a_v1_version_number_is_refused_with_a_pointer_to_the_legacy_reader(
    tmp_path: Path,
) -> None:
    path = save_project(tmp_path / "study.fvp", [_image()])
    _rewrite_manifest(path, lambda m: m.__setitem__("version", 1))

    with pytest.raises(ProjectFormatError, match="session_file"):
        load_project(path)


def test_corrupt_manifest_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "study.fvp"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(MANIFEST_NAME, "{not json")
    with pytest.raises(ProjectFormatError, match="not valid JSON"):
        load_project(path)


# ── v1 -> v2 migration (plan #32) ────────────────────────────────────
# v1 is read-only legacy, so pairs come from the test-only writer in
# fixtures/v1_session.py — which takes its constants from the v1 reader.


V1_CLIENT_STATE: dict[str, Any] = {
    "order": ["v1-a", "v1-b"],
    "activeId": "v1-a",
    "views": {"v1-a": {"z": 3.0}},
    "display": {"v1-a": {"cmap": "viridis", "invert": False}},
    "overlay": {"color": "#ffcc00", "size": "M"},
    "savedRois": {"v1-a": [{"id": "r1", "name": "grain", "kind": "roi", "pts": []}]},
    "sbsPanes": [{"imageId": "v1-a", "groupId": "g1"}],
    "sbsRows": 1,
    "sbsCols": 2,
    "imageGroups": [
        {
            "id": "g1",
            "name": "Sample A",
            "ids": ["v1-a", "v1-b"],
            "parent": None,
            "params": {"anneal_T": {"value": 450.0, "unit": "degC"}},
            "color": "#ff8800",
        },
        {"id": "g0", "name": "Study", "ids": [], "parent": None, "params": {},
         "color": None},
    ],
    "measures": {
        "v1-a": [
            {
                "id": "m1",
                "kind": "lasso",
                "pts": [{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}],
                "text": "grain 3",
                "labelDx": 4,
            }
        ]
    },
}


def _v1_pair(tmp_path: Path, source: str = "/nowhere/frame.tif") -> Path:
    image = DataStruct(
        data=np.arange(12, dtype=np.uint16).reshape(3, 4),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, units="nm"), AxisCal(0.25, units="nm")),
        metadata={"vendor": "acme", "source": source},
    )
    derived = DataStruct(
        data=np.full(5, 2.5, dtype=np.float32),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, units="eV"),),
        metadata={"derived_from": "v1-a", "parser": "derived"},
    )
    json_path, _ = write_v1_session(
        tmp_path / "legacy.json",
        [("v1-a", "frame.tif", image), ("v1-b", "frame sum", derived)],
        V1_CLIENT_STATE,
    )
    return json_path


def test_load_project_accepts_a_v1_pair_and_loses_nothing(tmp_path: Path) -> None:
    loaded = load_project(_v1_pair(tmp_path))

    assert [img.id for img in loaded.images] == ["v1-a", "v1-b"]
    assert loaded.payload_mode == "bundle"  # v1 embedded everything
    assert loaded.name == "legacy"  # v1 had no project name; the file's stem
    image, derived = loaded.images
    np.testing.assert_array_equal(image.data, np.arange(12).reshape(3, 4))
    assert image.data is not None and image.data.dtype == np.uint16
    assert image.axes == (AxisCal(0.5, units="nm"), AxisCal(0.25, units="nm"))
    assert image.metadata["vendor"] == "acme"
    # the import path becomes the v2 `source`, so the FIRST light save can
    # reference this image instead of embedding it forever
    assert image.source == "/nowhere/frame.tif"
    assert image.derived is False
    # a derived image keeps its lineage, which is what makes it embed in both
    # payload modes rather than being referenced into nothing
    assert derived.derived_from == "v1-a" and derived.derived is True
    assert derived.kind is DataKind.SPECTRUM

    # the opaque blob's scientific half is now validated sections...
    assert loaded.samples[0]["image_ids"] == ["v1-a", "v1-b"]
    assert loaded.samples[0]["params"] == {"anneal_T": {"value": 450.0, "unit": "degC"}}
    assert loaded.samples[0]["color"] == "#ff8800"
    assert loaded.samples[1]["id"] == "g0"  # an image-less project group survives
    assert loaded.measures["v1-a"][0]["kind"] == "lasso"
    assert loaded.measures["v1-a"][0]["labelDx"] == 4  # unmodelled field carried
    # ...and its presentational half rides ui_state untouched
    for key in ("order", "activeId", "views", "display", "overlay", "savedRois"):
        assert loaded.ui_state[key] == V1_CLIENT_STATE[key]
    assert loaded.ui_state["sbsPanes"] == V1_CLIENT_STATE["sbsPanes"]
    assert "imageGroups" not in loaded.ui_state
    assert "measures" not in loaded.ui_state


def test_a_migrated_v1_project_re_saves_as_a_fvp(tmp_path: Path) -> None:
    """The next save writes v2 — nothing can keep a project on v1."""
    loaded = load_project(_v1_pair(tmp_path))
    written = save_project(
        tmp_path / "legacy",
        loaded.images,
        samples=loaded.samples,
        measures=loaded.measures,
        ui_state=loaded.ui_state,
        name=loaded.name,
    )
    assert written == tmp_path / "legacy.fvp"

    again = load_project(written)
    assert [img.id for img in again.images] == ["v1-a", "v1-b"]
    assert again.samples == loaded.samples
    assert again.measures == loaded.measures
    assert again.ui_state == loaded.ui_state
    np.testing.assert_array_equal(again.images[0].data, np.arange(12).reshape(3, 4))
    # the v1 source does not exist here, so nothing could be referenced: the
    # pixels were embedded rather than dropped
    assert all(entry["embedded"] for entry in _manifest(written)["images"])


def test_a_migrated_v1_project_references_sources_that_still_exist(
    tmp_path: Path,
) -> None:
    """The migration's payoff: a v1 workspace whose files are still on disk
    becomes a light project (megabytes) rather than staying self-contained."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    tifffile.imwrite(
        data_dir / "frame.tif", np.arange(12, dtype=np.uint16).reshape(3, 4)
    )
    loaded = load_project(_v1_pair(tmp_path, source=str(data_dir / "frame.tif")))

    written = save_project(tmp_path / "legacy.fvp", loaded.images, data_root=data_dir)
    entries = {entry["id"]: entry for entry in _manifest(written)["images"]}
    assert entries["v1-a"]["embedded"] is False
    assert entries["v1-a"]["rel"] == "frame.tif"
    assert entries["v1-b"]["embedded"] is True  # derived: no file of its own
    np.testing.assert_array_equal(
        load_project(written).images[0].data, np.arange(12).reshape(3, 4)
    )


def test_a_v1_pair_is_named_by_either_half(tmp_path: Path) -> None:
    pair = _v1_pair(tmp_path)
    assert load_project(pair.with_suffix(".npz")).images[0].id == "v1-a"


def test_a_missing_v1_pair_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_project(tmp_path / "absent.json")


# ── the client_state split, on its own (plan #32) ────────────────────


def test_a_malformed_sample_or_measure_is_dropped_not_raised() -> None:
    """A save must never fail on state the schema cannot represent: the
    manifest is validated before the container is committed, so one stray
    entry would otherwise take the whole project down with it."""
    sections = split_client_state(
        {
            "imageGroups": [
                {"id": "g1", "name": "ok", "ids": ["a"]},
                {"name": "no id"},
                "not a group",
                {"id": "", "name": "empty id"},
            ],
            "measures": {
                "a": [
                    {"id": "m1", "kind": "polygon", "pts": [{"x": 0.0, "y": 1.0}]},
                    {"id": "m2", "kind": "teleport", "pts": []},  # unknown kind
                    {"id": "m3", "kind": "roi"},  # no pts
                    {"id": "m4", "kind": "roi", "pts": [{"x": 0.0}]},  # no y
                ],
                "b": [{"kind": "roi", "pts": []}],  # no id
            },
        }
    )
    assert [s["id"] for s in sections.samples] == ["g1"]
    assert sections.dropped_samples == 3
    assert [m["id"] for m in sections.measures["a"]] == ["m1"]
    assert "b" not in sections.measures  # nothing survived; no empty row written
    assert sections.dropped_measures == 4


def test_non_finite_numbers_are_refused_by_the_split(tmp_path: Path) -> None:
    """json.dumps writes NaN happily and JSON.parse refuses it, so one bad
    float would produce a project this app can write and not read."""
    sections = split_client_state(
        {
            "imageGroups": [
                {
                    "id": "g1",
                    "name": "S",
                    "ids": [],
                    "params": {
                        "good": {"value": 1.5, "unit": "nm"},
                        "nan": {"value": float("nan")},
                        "inf": {"value": float("inf"), "unit": "nm"},
                    },
                }
            ],
            "measures": {
                "a": [
                    {"id": "m1", "kind": "roi", "pts": [{"x": float("nan"), "y": 0.0}]}
                ]
            },
        }
    )
    assert list(sections.samples[0]["params"]) == ["good"]
    assert sections.measures == {}
    # and the surviving manifest really is writable + readable back
    path = save_project(
        tmp_path / "s.fvp",
        [_image()],
        samples=sections.samples,
        measures=sections.measures,
    )
    assert json.dumps(_manifest(path))  # no NaN token anywhere
    assert load_project(path).samples[0]["params"] == {
        "good": {"value": 1.5, "unit": "nm"}
    }


def test_a_v1_file_holding_nan_migrates_into_a_strictly_valid_manifest(
    tmp_path: Path,
) -> None:
    """The reachable NaN path is a FILE, not a request: `json.loads` accepts a
    bare `NaN` token and v1's writer emitted one, whereas neither a browser
    (`JSON.stringify` writes null) nor httpx will transmit one. So a v1
    workspace is where a non-finite number actually arrives — and if it reached
    the manifest, `JSON.parse` would refuse the ENTIRE load response, not just
    the field holding it."""
    state = {
        # opaque ui_state, and carried unknown fields on a sample and a measure
        # — the three paths that pass values through verbatim
        "views": {"v1-a": {"z": float("nan"), "px": 0.5}},
        "imageGroups": [
            {
                "id": "g1",
                "name": "S",
                "ids": ["v1-a"],
                "futureField": {"bad": float("inf"), "good": 2},
                "params": {"T": {"value": float("nan"), "unit": "degC"}},
            }
        ],
        "measures": {
            "v1-a": [
                {
                    "id": "m1",
                    "kind": "roi",
                    "pts": [{"x": 0.1, "y": 0.2}],
                    "futureList": [1.0, float("nan"), 3.0],
                }
            ]
        },
    }
    json_path, _ = write_v1_session(tmp_path / "legacy.json", [_image()], state)
    assert "NaN" in json_path.read_text(encoding="utf-8")  # v1 really wrote one

    loaded = load_project(json_path)
    written = save_project(
        tmp_path / "clean.fvp",
        loaded.images,
        samples=loaded.samples,
        measures=loaded.measures,
        ui_state=loaded.ui_state,
    )
    # strict JSON: allow_nan=False would raise on a single NaN or Infinity
    assert json.dumps(_manifest(written), allow_nan=False)

    again = load_project(written)
    assert again.ui_state["views"]["v1-a"] == {"px": 0.5}  # bad key dropped
    assert again.samples[0]["futureField"] == {"good": 2}
    assert again.samples[0]["params"] == {}  # an unplottable value is no value
    # a list keeps its length, so the remaining indices still line up
    assert again.measures["v1-a"][0]["futureList"] == [1.0, None, 3.0]


def test_the_split_round_trips_through_join() -> None:
    sections = split_client_state(V1_CLIENT_STATE)
    rejoined = join_sections(sections.samples, sections.measures, sections.ui_state)
    for key, value in V1_CLIENT_STATE.items():
        assert rejoined[key] == value


def test_ui_state_cannot_shadow_a_promoted_section() -> None:
    """A hand-edited file that put `measures` in both places must not be able
    to hide the validated copy behind the opaque one."""
    rejoined = join_sections(
        [{"id": "g1", "name": "S", "image_ids": ["a"]}],
        {"a": [{"id": "m1", "kind": "roi", "pts": []}]},
        {"measures": "junk", "imageGroups": "junk", "views": {}},
    )
    assert rejoined["measures"] == {"a": [{"id": "m1", "kind": "roi", "pts": []}]}
    assert rejoined["imageGroups"] == [
        {
            "id": "g1",
            "name": "S",
            "ids": ["a"],
            "parent": None,
            "params": {},
            "color": None,
        }
    ]


# ── re-pointing a moved data root (plan #34/#35) ─────────────────────


def test_a_user_root_is_appended_to_the_search_order(tmp_path: Path) -> None:
    """ADR 0002 §3's order is preserved, not replaced: a hint that starts
    working again still wins over a manual pick made while it was broken."""
    hint = tmp_path / "hint"
    hint.mkdir()
    assert paths.search_roots(str(hint), tmp_path) == (hint, tmp_path)
    assert paths.search_roots(None, tmp_path) == (tmp_path,)


def test_resolve_skips_a_root_whose_file_holds_something_else(tmp_path: Path) -> None:
    """One stale copy early in the order must not mask the real data later in
    it — otherwise a decoy folder permanently shadows the right one."""
    decoy = tmp_path / "decoy"
    real = tmp_path / "real"
    decoy.mkdir()
    real.mkdir()
    (decoy / "frame.tif").write_bytes(b"not a TIFF at all")
    path = save_project(
        tmp_path / "s.fvp", [_sourced(real / "frame.tif")], data_root=real
    )
    (reference,) = load_project(path).images
    (real / "frame.tif").rename(tmp_path / "held.tif")
    (tmp_path / "held.tif").rename(real / "frame.tif")

    outcome = project_resolve.resolve(reference, (decoy, real))
    assert outcome.image is not None
    assert outcome.image.resolved_path == str(real / "frame.tif")


def test_a_size_change_is_reported_not_enforced(tmp_path: Path) -> None:
    """`size_bytes` is a cheap sanity check (ADR 0002 §3): a re-exported file
    can differ in bytes and still be the right image, so the mismatch is
    surfaced rather than used to reject the folder."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    path = save_project(
        tmp_path / "s.fvp", [_sourced(data_dir / "frame.tif")], data_root=data_dir
    )
    recorded = _manifest(path)["images"][0]["size_bytes"]

    moved = tmp_path / "moved"
    moved.mkdir()
    tifffile.imwrite(
        moved / "frame.tif", np.full((3, 4), 7, dtype=np.uint16), description="x" * 900
    )
    (data_dir / "frame.tif").unlink()

    (placeholder,) = load_project(path).images
    assert placeholder.unavailable is True
    outcome = project_resolve.resolve(placeholder, (moved,))
    assert outcome.image is not None  # accepted: the pixels are right
    assert outcome.mismatched is True
    assert outcome.size_bytes == (moved / "frame.tif").stat().st_size
    assert outcome.size_bytes != recorded
