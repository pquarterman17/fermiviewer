"""Per-axis calibration at the edit surface (ADR 0008, roadmap 5a-A).

Every measurement reads `DataStruct.pixel_spacing`; these pin that the
EDIT paths -- manual apply, stored entries, auto-apply on import, clear --
no longer square an anisotropic image, and that everything a square-pixel
user did before still does exactly the same thing.

The fixture is an AFM scan sampled at 0.5 nm rows by 2.0 nm columns, an
ordinary `io/nanoscope` shape. Before this, correcting its magnitude
through `/calibration/apply` wrote one `AxisCal` to both axes.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io import calibration_db
from fermiviewer.io.calibration_db import entry_spacing, lookup, save_calibration
from fermiviewer.models import ImageMeta
from fermiviewer.routes.calibration import (
    auto_apply_calibration,
    recalibrate,
    recalibrate_axes,
    single_length_spacing,
)
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api

ROW_NM, COL_NM = 0.5, 2.0
KEY_META = {"Microscope": "AFM", "Magnification": 1}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_CALIB_PATH", str(tmp_path / "calib.json"))
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _image(axes: tuple[AxisCal, AxisCal], metadata: dict | None = None) -> DataStruct:
    return DataStruct(
        data=np.zeros((16, 32)), kind=DataKind.IMAGE, axes=axes,
        metadata=dict(metadata or {}),
    )


def _afm(metadata: dict | None = None) -> DataStruct:
    return _image((AxisCal(ROW_NM, 0.0, "nm"), AxisCal(COL_NM, 0.0, "nm")), metadata)


def _uncal(metadata: dict | None = None) -> DataStruct:
    return _image((AxisCal(), AxisCal()), metadata)


def _scales(ds: DataStruct) -> tuple[float, float]:
    return ds.axes[0].scale, ds.axes[1].scale


def _apply(client: TestClient, image_id: str, **body) -> dict:
    r = client.post("/api/calibration/apply", json={"image_id": image_id, **body})
    assert r.status_code == 200, r.text
    return r.json()["image"]


# ── the AFM round trip ─────────────────────────────────────────────────


def test_one_length_keeps_the_anisotropic_ratio(client) -> None:
    """The defect: a magnitude correction squared the pixels.

    Typing 4.0 nm into a 0.5 x 2.0 nm scan means the COLUMNS are 4.0 nm
    (pixel_size is the column scale everywhere); the rows follow the
    image's own 1:4 ratio to 1.0 nm rather than jumping to 4.0.
    """
    image_id = store.add_parsed(_afm(), "afm.spm")
    meta = _apply(client, image_id, pixel_size=4.0, unit="nm")
    assert meta["pixel_spacing"] == pytest.approx([1.0, 4.0])
    assert meta["pixel_size"] == pytest.approx(4.0)
    assert _scales(store.get(image_id)) == pytest.approx((1.0, 4.0))


def test_explicit_pair_round_trips_and_saves_per_axis(client) -> None:
    image_id = store.add_parsed(_afm(), "afm.spm")
    _apply(client, image_id, pixel_size=4.0, unit="nm")
    meta = _apply(
        client, image_id, pixel_spacing=[ROW_NM, COL_NM], unit="nm",
        save_as_key="AFM|1",
    )
    assert meta["pixel_spacing"] == pytest.approx([ROW_NM, COL_NM])
    assert meta["pixel_size"] == pytest.approx(COL_NM)
    assert _scales(store.get(image_id)) == pytest.approx((ROW_NM, COL_NM))

    # the offer-save stored what was applied, per axis, column as pixel_size
    entry = client.get("/api/calibration").json()["entries"]["AFM|1"]
    assert entry["pixel_size"] == pytest.approx(COL_NM)
    assert entry["pixel_spacing"] == pytest.approx([ROW_NM, COL_NM])
    assert entry["unit"] == "nm"

    # ... and applying that key to a fresh uncalibrated image reproduces it
    other = store.add_parsed(_uncal(), "other.spm")
    meta = _apply(client, other, key="AFM|1")
    assert meta["pixel_spacing"] == pytest.approx([ROW_NM, COL_NM])
    # a profile down 8 rows is 8 x 0.5 nm, not 8 x 2.0
    prof = client.post(
        "/api/measure/profile", json={"image_id": other, "a": [1, 1], "b": [9, 1]}
    ).json()
    assert prof["unit"] == "nm"
    assert prof["length"] == pytest.approx(8 * ROW_NM)


def test_clear_resets_both_axes(client) -> None:
    image_id = store.add_parsed(_afm(), "afm.spm")
    meta = client.post("/api/calibration/clear", json={"image_id": image_id}).json()["image"]
    assert meta["pixel_size"] is None and meta["pixel_spacing"] is None
    ds = store.get(image_id)
    assert not ds.axes[0].calibrated and not ds.axes[1].calibrated


# ── square pixels are unchanged ────────────────────────────────────────


def test_single_length_on_square_or_uncalibrated_pixels_stays_square(client) -> None:
    uncal = store.add_parsed(_uncal(), "u.dm4")
    meta = _apply(client, uncal, pixel_size=0.31, unit="nm")
    assert meta["pixel_spacing"] == pytest.approx([0.31, 0.31])
    assert _scales(store.get(uncal)) == (0.31, 0.31)

    square = store.add_parsed(
        _image((AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm"))), "sq.dm4"
    )
    meta = _apply(client, square, pixel_size=0.7, unit="um")
    assert meta["pixel_spacing"] == pytest.approx([0.7, 0.7])
    assert meta["pixel_unit"] == "um"


def test_mixed_unit_axes_have_no_ratio_to_keep(client) -> None:
    """nm rows against um columns is not a usable pair (ADR 0004), so one
    length has no ratio to follow and the result is square, as before."""
    mixed = store.add_parsed(
        _image((AxisCal(0.5, 0.0, "nm"), AxisCal(2.0, 0.0, "um"))), "mixed.dm4"
    )
    assert ImageMeta.from_datastruct(mixed, "mixed", store.get(mixed)).pixel_spacing is None
    meta = _apply(client, mixed, pixel_size=3.0, unit="nm")
    assert meta["pixel_spacing"] == pytest.approx([3.0, 3.0])


def test_single_length_spacing_rule() -> None:
    assert single_length_spacing(_afm(), 4.0) == pytest.approx((1.0, 4.0))
    assert single_length_spacing(_uncal(), 0.31) == (0.31, 0.31)
    # the column extent itself is returned bit for bit
    assert single_length_spacing(_afm(), COL_NM) == (ROW_NM, COL_NM)
    spectrum = DataStruct(
        data=np.arange(4), kind=DataKind.SPECTRUM, axes=(AxisCal(1, 0, "eV"),)
    )
    assert single_length_spacing(spectrum, 1.0) == (1.0, 1.0)


# ── stored entries, old and new ────────────────────────────────────────


def test_legacy_entry_without_pixel_spacing_still_applies(client) -> None:
    """A per-user file written before per-axis entries existed."""
    p = calibration_db.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"Old|1": {"pixel_size": 0.75, "unit": "um", "note": "", "saved": "x"}}),
        encoding="utf-8",
    )
    assert entry_spacing(lookup("Old|1")) == (0.75, 0.75)

    image_id = store.add_parsed(_uncal(), "u.dm4")
    meta = _apply(client, image_id, key="Old|1")
    assert meta["pixel_spacing"] == pytest.approx([0.75, 0.75])
    assert meta["pixel_unit"] == "um"

    # and through the import path
    fresh = store.add_parsed(_uncal({"Microscope": "Old", "Magnification": 1}), "o.dm4")
    assert auto_apply_calibration(fresh, store.get(fresh)) is True
    assert _scales(store.get(fresh)) == (0.75, 0.75)
    assert store.get(fresh).metadata["calibration_source"] == "db:Old|1"


def test_auto_apply_honours_a_per_axis_entry() -> None:
    save_calibration("AFM|1", None, "nm", pixel_spacing=(ROW_NM, COL_NM))
    image_id = store.add_parsed(_uncal(KEY_META), "afm.spm")
    assert auto_apply_calibration(image_id, store.get(image_id)) is True
    after = store.get(image_id)
    assert _scales(after) == (ROW_NM, COL_NM)
    assert after.axes[0].units == after.axes[1].units == "nm"
    assert after.metadata["calibration_source"] == "db:AFM|1"


def test_save_calibration_entry_shapes() -> None:
    # square pixels: pixel_size only, even when given as a pair
    save_calibration("Sq|1", 0.3, "nm")
    save_calibration("Sq|2", None, "nm", pixel_spacing=(0.3, 0.3))
    for key in ("Sq|1", "Sq|2"):
        entry = lookup(key)
        assert entry["pixel_size"] == pytest.approx(0.3)
        assert "pixel_spacing" not in entry
        assert entry_spacing(entry) == (0.3, 0.3)
    # anisotropic: both, with pixel_size the column extent
    save_calibration("An|1", None, "nm", pixel_spacing=(ROW_NM, COL_NM))
    entry = lookup("An|1")
    assert entry["pixel_size"] == pytest.approx(COL_NM)
    assert entry_spacing(entry) == (ROW_NM, COL_NM)
    # a pixel_size that disagrees with the pair's column extent is refused
    with pytest.raises(ValueError, match="column extent"):
        save_calibration("Bad|1", 1.0, "nm", pixel_spacing=(ROW_NM, COL_NM))
    with pytest.raises(ValueError, match="positive"):
        save_calibration("Bad|2", None, "nm", pixel_spacing=(0.0, 1.0))
    with pytest.raises(ValueError, match="positive"):
        save_calibration("Bad|3", None, "nm")
    with pytest.raises(ValueError, match="positive"):
        entry_spacing({"pixel_size": 1.0, "pixel_spacing": [1.0, -1.0]})


def test_save_route_accepts_a_pair_and_refuses_ambiguity(client) -> None:
    ok = client.post(
        "/api/calibration",
        json={"key": "AFM|1", "pixel_spacing": [ROW_NM, COL_NM], "unit": "nm"},
    )
    assert ok.status_code == 200, ok.text
    entry = client.get("/api/calibration").json()["entries"]["AFM|1"]
    assert entry["pixel_spacing"] == pytest.approx([ROW_NM, COL_NM])
    assert entry["pixel_size"] == pytest.approx(COL_NM)

    both = client.post(
        "/api/calibration",
        json={"key": "k", "pixel_size": 1.0, "pixel_spacing": [1.0, 2.0], "unit": "nm"},
    )
    assert both.status_code == 422
    neither = client.post("/api/calibration", json={"key": "k", "unit": "nm"})
    assert neither.status_code == 422
    bad = client.post(
        "/api/calibration", json={"key": "k", "pixel_spacing": [0.0, 2.0], "unit": "nm"}
    )
    assert bad.status_code == 422


def test_apply_route_refuses_two_manual_forms_and_bad_pairs(client) -> None:
    image_id = store.add_parsed(_uncal(), "u.dm4")
    both = client.post(
        "/api/calibration/apply",
        json={"image_id": image_id, "pixel_size": 1.0, "pixel_spacing": [1.0, 2.0]},
    )
    assert both.status_code == 422
    bad = client.post(
        "/api/calibration/apply",
        json={"image_id": image_id, "pixel_spacing": [1.0, -2.0]},
    )
    assert bad.status_code == 422
    # the unchanged shape of the old error
    nothing = client.post("/api/calibration/apply", json={"image_id": image_id})
    assert nothing.status_code == 422


# ── the primitives ─────────────────────────────────────────────────────


def test_recalibrate_axes_keeps_the_energy_axis_and_rejects_spectra() -> None:
    cube = DataStruct(
        data=np.zeros((2, 3, 4)),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(2.0, 1.0, "eV")),
    )
    out = recalibrate_axes(cube, (ROW_NM, COL_NM), "nm")
    assert out.axes[0] == AxisCal(ROW_NM, 0.0, "nm")
    assert out.axes[1] == AxisCal(COL_NM, 0.0, "nm")
    assert out.axes[2] == cube.axes[2]
    # the isotropic form is the pair form with equal extents
    assert recalibrate(cube, 0.25, "nm").axes == recalibrate_axes(cube, (0.25, 0.25), "nm").axes

    spectrum = DataStruct(
        data=np.arange(4), kind=DataKind.SPECTRUM, axes=(AxisCal(1, 0, "eV"),)
    )
    with pytest.raises(HTTPException, match="no spatial calibration"):
        recalibrate_axes(spectrum, (1.0, 1.0), "nm")


def test_image_meta_pixel_size_is_the_column_extent() -> None:
    """ADR 0008 §2: `pixel_size` equals `pixel_spacing[1]` whenever the
    pair exists, so the two names cannot drift apart on the wire."""
    meta = ImageMeta.from_datastruct("a", "afm", _afm())
    assert meta.pixel_spacing == pytest.approx((ROW_NM, COL_NM))
    assert meta.pixel_size == meta.pixel_spacing[1]

    # only the columns calibrated: no pair, but the column scale is still
    # reported as pixel_size
    half = _image((AxisCal(), AxisCal(COL_NM, 0.0, "nm")))
    meta = ImageMeta.from_datastruct("b", "half", half)
    assert meta.pixel_spacing is None
    assert meta.pixel_size == pytest.approx(COL_NM)
