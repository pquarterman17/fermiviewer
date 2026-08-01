"""Lispix .rpl + .raw reader (Data-Formats #7 remainder)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.registry import load_auto
from fermiviewer.io.rpl import RplFormatError, load_rpl
from fixtures.minirpl import write_mini_rpl

pytestmark = pytest.mark.parser


def test_single_spectrum_dont_care_byte_order(tmp_path: Path) -> None:
    data = np.array([0, 1, 2, 3, 40, 500], dtype=np.uint16)
    rpl, _raw = write_mini_rpl(tmp_path, "spec", data, record_by="vector")
    ds = load_rpl(rpl)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (6,)
    np.testing.assert_array_equal(ds.data, data)
    assert ds.metadata["parser"] == "rpl"
    assert ds.metadata["record_by"] == "vector"


def test_plain_image_dont_care_record_by(tmp_path: Path) -> None:
    data = np.arange(12, dtype=np.int32).reshape(3, 4)
    rpl, _raw = write_mini_rpl(tmp_path, "img", data, record_by="dont-care")
    ds = load_rpl(rpl)
    assert ds.kind is DataKind.IMAGE
    np.testing.assert_array_equal(ds.data, data)


def test_spectrum_image_vector_record_by(tmp_path: Path) -> None:
    # (height, width, depth) — a spectrum per pixel, depth contiguous
    data = np.arange(2 * 3 * 5, dtype=np.float32).reshape(2, 3, 5)
    rpl, _raw = write_mini_rpl(tmp_path, "cube_vec", data, record_by="vector")
    ds = load_rpl(rpl)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 5)
    np.testing.assert_array_equal(ds.data, data)


def test_spectrum_image_image_record_by_reorders_depth_to_last(tmp_path: Path) -> None:
    # same logical (height, width, depth) cube, but written plane-ordered
    data = np.arange(2 * 3 * 5, dtype=np.float32).reshape(2, 3, 5)
    rpl, _raw = write_mini_rpl(tmp_path, "cube_img", data, record_by="image")
    ds = load_rpl(rpl)
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 5)
    np.testing.assert_array_equal(ds.data, data)


def test_vector_and_image_record_by_agree(tmp_path: Path) -> None:
    data = np.arange(4 * 3 * 6, dtype=np.int32).reshape(4, 3, 6)
    rpl_v, _ = write_mini_rpl(tmp_path, "v", data, record_by="vector")
    rpl_i, _ = write_mini_rpl(tmp_path, "i", data, record_by="image")
    ds_v = load_rpl(rpl_v)
    ds_i = load_rpl(rpl_i)
    np.testing.assert_array_equal(ds_v.data, ds_i.data)
    np.testing.assert_array_equal(ds_v.data, data)


@pytest.mark.parametrize("byte_order", ["little-endian", "big-endian"])
def test_explicit_byte_order_decodes_correctly(tmp_path: Path, byte_order: str) -> None:
    data = np.array([1, 300, 5000, 65000, 70000], dtype=np.uint32)
    rpl, _raw = write_mini_rpl(tmp_path, f"bo_{byte_order}", data, byte_order=byte_order)
    ds = load_rpl(rpl)
    np.testing.assert_array_equal(ds.data, data)


def test_axis_calibration_from_meta_keys(tmp_path: Path) -> None:
    data = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    rpl, _raw = write_mini_rpl(
        tmp_path,
        "cal",
        data,
        record_by="vector",
        axis_cal={
            "height": {"scale": 100.0, "origin": 0.5, "units": "m"},
            "width": {"scale": 200.0, "origin": 1.0, "units": "m"},
            "depth": {"scale": 300.0, "origin": 1.5, "units": "eV"},
        },
    )
    ds = load_rpl(rpl)
    assert ds.axes[0].scale == pytest.approx(100.0)
    assert ds.axes[0].units == "m"
    assert ds.axes[1].scale == pytest.approx(200.0)
    assert ds.axes[2].scale == pytest.approx(300.0)
    assert ds.axes[2].units == "eV"
    # value = origin + index*scale (rpl convention) → axis[0] == origin
    assert ds.energy_axis[0] == pytest.approx(1.5)
    assert ds.energy_axis[1] == pytest.approx(1.5 + 300.0)


def test_no_calibration_keys_yields_uncalibrated_axes(tmp_path: Path) -> None:
    data = np.array([1, 2, 3], dtype=np.uint8)
    rpl, _raw = write_mini_rpl(tmp_path, "nocal", data)
    ds = load_rpl(rpl)
    assert not ds.energy_cal.calibrated


def test_routes_through_load_auto(tmp_path: Path) -> None:
    data = np.array([1, 2, 3], dtype=np.uint8)
    rpl, _raw = write_mini_rpl(tmp_path, "auto", data)
    ds = load_auto(rpl)
    assert ds.kind is DataKind.SPECTRUM
    assert ds.metadata["parser"] == "rpl"


def test_missing_raw_sibling_raises(tmp_path: Path) -> None:
    rpl_path = tmp_path / "orphan.rpl"
    rpl_path.write_text("key\tvalue\nwidth\t1\nheight\t1\ndepth\t3\n")
    with pytest.raises(RplFormatError, match="no sibling .raw"):
        load_rpl(rpl_path)


def test_truncated_raw_raises(tmp_path: Path) -> None:
    data = np.arange(10, dtype=np.uint16)
    rpl, raw = write_mini_rpl(tmp_path, "short", data)
    raw.write_bytes(raw.read_bytes()[:4])  # truncate the payload
    with pytest.raises(RplFormatError, match="expected at least"):
        load_rpl(rpl)


def test_unsupported_data_type_raises(tmp_path: Path) -> None:
    data = np.array([1, 2, 3], dtype=np.uint8)
    rpl, _raw = write_mini_rpl(tmp_path, "baddtype", data)
    text = rpl.read_text().replace("data-type\tunsigned", "data-type\tweird")
    rpl.write_text(text)
    with pytest.raises(RplFormatError, match="unsupported data-type"):
        load_rpl(rpl)


# ── realdata: pinned values measured during development against the
# rosettasciio ripple test matrix (../test-data/ripple/microscopy) — auto-
# skips when the sibling repo isn't checked out. ──────────────────────────


@pytest.mark.realdata
def test_real_single_spectrum_no_meta(ripple_examples: Path) -> None:
    ds = load_rpl(ripple_examples / "test_ripple_sdim-1_ndim-0_float32.rpl")
    assert ds.kind is DataKind.SPECTRUM
    assert ds.data.shape == (3,)
    np.testing.assert_array_equal(ds.data, [0.0, 1.0, 2.0])
    assert ds.energy_cal.units == "eV"
    assert ds.energy_cal.scale == pytest.approx(100.0)


@pytest.mark.realdata
def test_real_spectrum_image_vector_meta(ripple_examples: Path) -> None:
    ds = load_rpl(ripple_examples / "test_ripple_sdim-1_ndim-2_float32_meta.rpl")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (2, 3, 4)
    assert ds.metadata["record_by"] == "vector"
    assert ds.metadata["signal"] == "EELS"
    assert ds.axes[2].units == "eV"
    assert ds.axes[2].scale == pytest.approx(300.0)
    assert np.allclose(ds.energy_axis, [1.5, 301.5, 601.5, 901.5])


@pytest.mark.realdata
def test_real_image_stack_record_by_image(ripple_examples: Path) -> None:
    ds = load_rpl(ripple_examples / "test_ripple_sdim-2_ndim-1_float32_meta.rpl")
    assert ds.kind is DataKind.SPECTRUM_IMAGE
    assert ds.data.shape == (3, 4, 2)  # (height, width, depth) — depth moved last
    assert ds.metadata["record_by"] == "image"


@pytest.mark.realdata
@pytest.mark.parametrize(
    "dtype_suffix,expected_dtype_kind",
    [
        ("uint8", "u"),
        ("uint16", "u"),
        ("int32", "i"),
        ("int64", "i"),
        ("float64", "f"),
    ],
)
def test_real_dtype_matrix_shapes(
    ripple_examples: Path, dtype_suffix: str, expected_dtype_kind: str
) -> None:
    ds = load_rpl(ripple_examples / f"test_ripple_sdim-2_ndim-0_{dtype_suffix}.rpl")
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (2, 3)


# ── oracle: cross-validated against rosettasciio's ripple reader. GPL —
# dev-only oracle group, skips when not installed (see test_oracle_rsciio.py
# conventions — import is narrow and function-scoped, never a runtime dep). ─


@pytest.mark.realdata
@pytest.mark.oracle
def test_real_corpus_matches_rsciio_oracle(ripple_examples: Path) -> None:
    file_reader = pytest.importorskip(
        "rsciio.ripple", reason="oracle group not installed"
    ).file_reader

    files = sorted(ripple_examples.glob("*.rpl"))
    assert len(files) >= 40, "expected the full rsciio ripple test matrix"
    compared = 0
    for f in files:
        ours = load_rpl(f)
        theirs = file_reader(str(f))[0]
        our_data = np.squeeze(ours.data)
        their_data = np.asarray(theirs["data"], dtype=np.float64)
        if our_data.ndim == 3 and their_data.ndim == 3 and our_data.shape != their_data.shape:
            # record-by "image": rsciio reports the file's native
            # (depth, height, width) plane order; we reorder depth last.
            their_data = np.moveaxis(their_data, 0, -1)
        assert our_data.shape == their_data.shape, f.name
        assert np.array_equal(our_data, their_data), f.name
        compared += 1
    assert compared == len(files)
