"""Quantum Detectors Merlin .mib RAW reader (PLAN_4DSTEM #2).

See io/fourd/mib.py's module docstring for the derived descramble layout
this exercises. Synthetic tests construct raw bytes by applying the INVERSE
of the documented transform independently here (never by importing the
module's private helpers), so they validate the module's behavior rather
than its own internals.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from fermiviewer.io.fourd.mib import MibFormatError, load_mib
from fermiviewer.io.registry import (
    UnsupportedFormatError,
    is_fourd_path,
    load_auto,
    load_fourd_auto,
)

pytestmark = pytest.mark.parser

_RAW_WORD = 8


def _scramble(frame: np.ndarray) -> np.ndarray:
    """Reverse each consecutive group of 8 columns — self-inverse, used
    here to build a synthetic RAW payload whose decoded answer is known."""
    h, w = frame.shape
    assert w % _RAW_WORD == 0
    grouped = frame.reshape(h, w // _RAW_WORD, _RAW_WORD)
    return grouped[:, :, ::-1].reshape(h, w)


def _make_header(
    *,
    width: int,
    height: int,
    num_chips: int,
    chip_layout: str,
    header_size: int = 128,
    dtype_tag: str = "R64",
    magic: str = "MQ1",
) -> bytes:
    fields = [
        magic,
        "000001",
        f"{header_size:05d}",
        f"{num_chips:02d}",
        f"{width:04d}",
        f"{height:04d}",
        dtype_tag,
        f"   {chip_layout}",
        "0F",
    ]
    text = ",".join(fields) + ","
    data = text.encode("ascii")
    assert len(data) <= header_size, "test header_size too small"
    return data + b" " * (header_size - len(data))


def _write_mib(
    path: Path,
    frames: list[np.ndarray],
    *,
    num_chips: int,
    chip_layout: str,
    header_size: int = 128,
    dtype_tag: str = "R64",
    magic: str = "MQ1",
) -> Path:
    height, width = frames[0].shape
    header = _make_header(
        width=width,
        height=height,
        num_chips=num_chips,
        chip_layout=chip_layout,
        header_size=header_size,
        dtype_tag=dtype_tag,
        magic=magic,
    )
    with open(path, "wb") as f:
        for frame in frames:
            f.write(header)
            f.write(np.ascontiguousarray(frame, dtype=np.uint8).tobytes())
    return path


# ── single-chip (num_chips=1): only the raw-word-order fix applies ────────


def test_single_chip_passthrough(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    height, width = 3, 16
    frames = [
        rng.integers(0, 255, size=(height, width), dtype=np.uint8) for _ in range(2)
    ]
    raw_frames = [_scramble(f) for f in frames]
    path = _write_mib(
        tmp_path / "single.mib", raw_frames, num_chips=1, chip_layout="1x1"
    )
    ds = load_mib(path)
    assert ds.det_shape == (height, width)
    assert ds.scan_shape == (1, 2)
    for k, expected in enumerate(frames):
        np.testing.assert_array_equal(ds.pattern(0, k), expected)


# ── 2x2 quad (num_chips=4): word-order fix + bottom-row 180 rotation ─────


def _quad_frame(rng: np.random.Generator, chip_h: int, chip_w: int) -> np.ndarray:
    tl = rng.integers(0, 255, size=(chip_h, chip_w), dtype=np.uint8)
    tr = rng.integers(0, 255, size=(chip_h, chip_w), dtype=np.uint8)
    bl = rng.integers(0, 255, size=(chip_h, chip_w), dtype=np.uint8)
    br = rng.integers(0, 255, size=(chip_h, chip_w), dtype=np.uint8)
    return np.block([[tl, tr], [bl, br]])


def _quad_raw_from_expected(expected: np.ndarray, chip_h: int, chip_w: int) -> np.ndarray:
    tl = expected[:chip_h, :chip_w]
    tr = expected[:chip_h, chip_w:]
    bl = expected[chip_h:, :chip_w]
    br = expected[chip_h:, chip_w:]
    chip0, chip1 = tl, tr
    chip2 = np.rot90(bl, 2)
    chip3 = np.rot90(br, 2)
    fixed = np.concatenate([chip0, chip1, chip2, chip3], axis=1)
    return _scramble(fixed)


def test_quad_descramble_synthetic(tmp_path: Path) -> None:
    rng = np.random.default_rng(42)
    chip_h, chip_w = 2, 8
    n_frames = 3
    expecteds = [_quad_frame(rng, chip_h, chip_w) for _ in range(n_frames)]
    raw_frames = [_quad_raw_from_expected(e, chip_h, chip_w) for e in expecteds]
    path = _write_mib(tmp_path / "quad.mib", raw_frames, num_chips=4, chip_layout="2x2")

    ds = load_mib(path)
    assert ds.det_shape == (2 * chip_h, 2 * chip_w)
    assert ds.scan_shape == (1, n_frames)
    for k, expected in enumerate(expecteds):
        np.testing.assert_array_equal(ds.pattern(0, k), expected)

    # a block read must agree with per-pattern reads
    row0, block = next(ds.iter_scan_rows())
    assert row0 == 0
    for k in range(n_frames):
        np.testing.assert_array_equal(block[0, k], expecteds[k])


def test_explicit_scan_shape_reshapes_the_scan(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    chip_h, chip_w = 2, 8
    frames = [_quad_frame(rng, chip_h, chip_w) for _ in range(6)]
    raw_frames = [_quad_raw_from_expected(f, chip_h, chip_w) for f in frames]
    path = _write_mib(tmp_path / "scan.mib", raw_frames, num_chips=4, chip_layout="2x2")

    ds = load_mib(path, scan_shape=(2, 3))
    assert ds.scan_shape == (2, 3)
    # raster order: frame index = y*cols + x
    for y in range(2):
        for x in range(3):
            np.testing.assert_array_equal(ds.pattern(y, x), frames[y * 3 + x])


def test_scan_shape_mismatch_raises(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    chip_h, chip_w = 2, 8
    frames = [_quad_frame(rng, chip_h, chip_w) for _ in range(4)]
    raw_frames = [_quad_raw_from_expected(f, chip_h, chip_w) for f in frames]
    path = _write_mib(tmp_path / "bad_scan.mib", raw_frames, num_chips=4, chip_layout="2x2")
    with pytest.raises(MibFormatError, match="scan_shape"):
        load_mib(path, scan_shape=(2, 3))


# ── format errors ──────────────────────────────────────────────────────


def test_bad_magic_raises(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "badmagic.mib", [_scramble(frame)], num_chips=1,
        chip_layout="1x1", magic="XYZ",
    )
    with pytest.raises(MibFormatError, match="MQ1"):
        load_mib(path)


def test_unsupported_dtype_tag_raises(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "u08.mib", [_scramble(frame)], num_chips=1,
        chip_layout="1x1", dtype_tag="U08",
    )
    with pytest.raises(MibFormatError, match="dtype tag"):
        load_mib(path)


def test_unsupported_chip_layout_raises(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 24), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "triple.mib", [_scramble(frame)], num_chips=3,
        chip_layout="1x3",
    )
    with pytest.raises(MibFormatError, match="unsupported chip layout"):
        load_mib(path)


def test_truncated_file_raises(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(tmp_path / "trunc.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    path.write_bytes(path.read_bytes()[:-1])  # lop off the last byte
    with pytest.raises(MibFormatError, match="not a multiple"):
        load_mib(path)


def test_width_not_multiple_of_8_raises_lazily(tmp_path: Path) -> None:
    # header_size + payload must still be internally consistent; the width%8
    # check only fires when a frame is actually decoded (lazy), not at open.
    height, width = 2, 10
    payload = np.zeros((height, width), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "oddwidth.mib", [payload], num_chips=1, chip_layout="1x1"
    )
    ds = load_mib(path)  # opens fine — no frame decoded yet
    with pytest.raises(MibFormatError, match="multiple of 8"):
        ds.pattern(0, 0)


# ── registry wiring ────────────────────────────────────────────────────


def test_mib_is_fourd_path(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(tmp_path / "a.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    assert is_fourd_path(path) is True


def test_mib_routes_through_load_fourd_auto(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(tmp_path / "b.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    ds = load_fourd_auto(path)
    np.testing.assert_array_equal(ds.pattern(0, 0), frame)


def test_mib_is_rejected_by_load_auto(tmp_path: Path) -> None:
    """load_auto stays DataStruct-only — a 4D-only extension must raise,
    never silently return something that isn't a DataStruct."""
    rng = np.random.default_rng(9)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(tmp_path / "c.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    with pytest.raises(UnsupportedFormatError):
        load_auto(path)


# ── realdata: real Merlin acquisition, validated byte-for-byte against the
# decoded h5 ground truth (CC BY 4.0, Zenodo 10.5281/zenodo.15490547). ────


@pytest.mark.realdata
def test_real_mib_matches_h5_ground_truth_all_frames(fourd_corpus: Path) -> None:
    import h5py

    mib_path = fourd_corpus / "test_data.mib"
    h5_path = fourd_corpus / "test_data.h5"
    ds = load_mib(mib_path)
    assert ds.det_shape == (512, 512)
    assert ds.scan_shape == (1, 132)
    try:
        with h5py.File(h5_path, "r") as f:
            truth = np.asarray(f["data_stack"][:])
        assert truth.shape == (132, 512, 512)
        for k in range(132):
            np.testing.assert_array_equal(ds.pattern(0, k), truth[k])
    finally:
        ds.close()


@pytest.mark.realdata
def test_real_mib_block_read_matches_pattern_reads(fourd_corpus: Path) -> None:
    ds = load_mib(fourd_corpus / "test_data.mib")
    try:
        row0, block = next(ds.iter_scan_rows())
        assert row0 == 0
        assert block.shape == (1, 132, 512, 512)
        for k in (0, 1, 65, 131):
            np.testing.assert_array_equal(block[0, k], ds.pattern(0, k))
    finally:
        ds.close()


@pytest.mark.realdata
def test_real_mib_nav_image_shape(fourd_corpus: Path) -> None:
    ds = load_mib(fourd_corpus / "test_data.mib")
    try:
        assert ds.nav_image.shape == ds.scan_shape
    finally:
        ds.close()
