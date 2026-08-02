"""Quantum Detectors Merlin .mib RAW reader (PLAN_4DSTEM #2).

See io/fourd/mib.py's module docstring for the derived descramble layout
this exercises. Synthetic tests construct raw bytes by applying the INVERSE
of the documented transform independently here (never by importing the
module's private helpers), so they validate the module's behavior rather
than its own internals.
"""

from __future__ import annotations

import gc
import os
import threading
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


# ── malformed-input hardening: bug-hunt pass ───────────────────────────
#
# These construct raw header bytes directly (not via _make_header/
# _write_mib, whose header_size must be a real positive on-disk byte
# count) so a header can claim geometry that's inconsistent with reality.


def _raw_header_text(
    header_size_field: str,
    width_field: str = "0008",
    height_field: str = "0002",
    num_chips_field: str = "01",
    chip_layout: str = "   1x1",
    dtype_tag: str = "R64",
    magic: str = "MQ1",
) -> bytes:
    fields = [
        magic, "000001", header_size_field, num_chips_field,
        width_field, height_field, dtype_tag, chip_layout, "0F",
    ]
    return (",".join(fields) + ",").encode("ascii")


def _raw_file_bytes(
    header_size_field: str,
    width_field: str = "0008",
    height_field: str = "0002",
    *,
    header_pad_to: int = 128,
    payload: bytes = b"",
    **kwargs: str,
) -> bytes:
    header = _raw_header_text(header_size_field, width_field, height_field, **kwargs)
    assert len(header) <= header_pad_to, "test header_pad_to too small"
    header = header + b" " * (header_pad_to - len(header))
    return header + payload


def test_empty_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.mib"
    path.write_bytes(b"")
    with pytest.raises(MibFormatError, match="too few comma fields"):
        load_mib(path)


def test_too_few_header_fields_raises(tmp_path: Path) -> None:
    path = tmp_path / "short.mib"
    path.write_bytes(b"MQ1,1,2")  # nowhere near 8 comma-separated fields
    with pytest.raises(MibFormatError, match="too few comma fields"):
        load_mib(path)


def test_negative_header_size_raises_cleanly_at_load_time(tmp_path: Path) -> None:
    """A corrupted numeric field like "-0001" parses fine via int() (no
    ValueError), so it isn't caught by the "unparseable field" path — left
    unvalidated, it used to silently slice with a negative byte offset and
    only blow up as an opaque numpy reshape ValueError the first time a
    pattern was decoded, well after `load_mib` had already returned a
    dataset. It must fail here, at open time, as a MibFormatError."""
    path = tmp_path / "neg_header.mib"
    path.write_bytes(_raw_file_bytes("-0001", "0008", "0002"))
    with pytest.raises(MibFormatError, match="invalid header_size"):
        load_mib(path)


@pytest.mark.parametrize(
    "width_field,height_field",
    [("0000", "0002"), ("0008", "0000"), ("0000", "0000")],
)
def test_zero_dimension_raises_cleanly_at_load_time(
    tmp_path: Path, width_field: str, height_field: str
) -> None:
    path = tmp_path / "zerodim.mib"
    path.write_bytes(_raw_file_bytes("00128", width_field, height_field))
    with pytest.raises(MibFormatError, match="invalid image dimensions"):
        load_mib(path)


def test_header_claims_dims_overrunning_the_file_raises(tmp_path: Path) -> None:
    """Header declares a 9999x9999 frame; the file holds nowhere near that
    many payload bytes — must be a clean MibFormatError, not a numpy/OS
    error from memmapping a shape that doesn't fit the file."""
    path = tmp_path / "overrun.mib"
    path.write_bytes(
        _raw_file_bytes("00128", "9999", "9999", payload=b"\x00" * 50)
    )
    with pytest.raises(MibFormatError, match="not a multiple"):
        load_mib(path)


def test_trailing_partial_frame_after_complete_frames_raises(tmp_path: Path) -> None:
    """2 complete frames plus a short, incomplete 3rd frame's worth of
    trailing bytes — the realistic "acquisition was cut off mid-write"
    shape, distinct from the single-byte-short case already covered by
    test_truncated_file_raises."""
    rng = np.random.default_rng(11)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "partial.mib", [_scramble(frame), _scramble(frame)],
        num_chips=1, chip_layout="1x1",
    )
    with open(path, "ab") as f:
        f.write(b"\x00" * 10)  # far short of one more full frame_size
    with pytest.raises(MibFormatError, match="not a multiple"):
        load_mib(path)


def test_only_first_frames_header_governs_every_frames_geometry(
    tmp_path: Path,
) -> None:
    """Documents/pins a deliberate simplification: this reader parses ONLY
    the first frame's header and applies its geometry to every frame in the
    file (real Merlin acquisitions never vary frame-to-frame, per the
    module docstring). A later frame's header bytes are never independently
    re-validated — corrupting the SECOND frame's header here is silently
    ignored, and that frame still decodes using the FIRST frame's geometry."""
    rng = np.random.default_rng(12)
    frame0 = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    frame1 = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "twoframes.mib", [_scramble(frame0), _scramble(frame1)],
        num_chips=1, chip_layout="1x1", header_size=128,
    )
    frame_size = 128 + 2 * 8
    bogus_header = _make_header(
        width=16, height=4, num_chips=1, chip_layout="1x1", header_size=128
    )
    data = bytearray(path.read_bytes())
    data[frame_size : frame_size + 128] = bogus_header
    path.write_bytes(bytes(data))

    ds = load_mib(path)
    np.testing.assert_array_equal(ds.pattern(0, 0), frame0)
    np.testing.assert_array_equal(ds.pattern(0, 1), frame1)


# ── lifecycle: close(), held references, Windows file-handle release ──


def test_pattern_returns_an_owned_copy_not_a_memmap_view(tmp_path: Path) -> None:
    """width==8 is exactly one raw-word group — the specific case where
    `_undo_raw_word_order`'s reshape used to be able to degrade to a VIEW
    still backed by the memmap instead of an owned copy (see
    test_pattern_reference_does_not_block_file_deletion_after_close for why
    that matters)."""
    rng = np.random.default_rng(13)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(tmp_path / "owned.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    ds = load_mib(path)
    try:
        pattern = ds.pattern(0, 0)
        assert pattern.base is None
        assert pattern.flags["OWNDATA"]
    finally:
        ds.close()


def test_pattern_reference_does_not_block_file_deletion_after_close(
    tmp_path: Path,
) -> None:
    """CRITICAL on Windows: a memmap-backed view surviving `close()` keeps
    the OS file handle open, so a file a caller read a pattern from (and is
    still holding onto) could never be deleted or replaced even after the
    dataset was explicitly closed."""
    rng = np.random.default_rng(14)
    frame = rng.integers(0, 255, size=(2, 8), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "delete_me.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1"
    )
    ds = load_mib(path)
    held_pattern = ds.pattern(0, 0)  # held across close() on purpose
    ds.close()
    gc.collect()
    os.remove(path)  # must not raise PermissionError ([WinError 32])
    np.testing.assert_array_equal(held_pattern, frame)  # still valid to read


def test_closed_dataset_pattern_and_iter_scan_rows_raise_clear_errors(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(15)
    frame = rng.integers(0, 255, size=(2, 16), dtype=np.uint8)
    path = _write_mib(tmp_path / "closed.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    ds = load_mib(path)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        ds.pattern(0, 0)
    with pytest.raises(RuntimeError, match="closed"):
        next(ds.iter_scan_rows())


def test_double_close_is_a_noop(tmp_path: Path) -> None:
    rng = np.random.default_rng(16)
    frame = rng.integers(0, 255, size=(2, 16), dtype=np.uint8)
    path = _write_mib(
        tmp_path / "doubleclose.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1"
    )
    ds = load_mib(path)
    ds.close()
    ds.close()  # must not raise


def test_opening_the_same_file_twice_gives_independent_usable_datasets(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(17)
    frame = rng.integers(0, 255, size=(2, 16), dtype=np.uint8)
    path = _write_mib(tmp_path / "dual.mib", [_scramble(frame)], num_chips=1, chip_layout="1x1")
    ds_a = load_mib(path)
    ds_b = load_mib(path)
    np.testing.assert_array_equal(ds_a.pattern(0, 0), frame)
    np.testing.assert_array_equal(ds_b.pattern(0, 0), frame)
    ds_a.close()
    # closing the first must not break the second
    np.testing.assert_array_equal(ds_b.pattern(0, 0), frame)
    ds_b.close()


def test_concurrent_pattern_reads_do_not_crash(tmp_path: Path) -> None:
    """Multiple threads reading different patterns from the same memmap
    concurrently (as FastAPI's threadpool-per-request model does) must not
    crash or corrupt results."""
    rng = np.random.default_rng(18)
    chip_h, chip_w = 2, 16
    n_frames = 20
    frames = [rng.integers(0, 255, size=(chip_h, chip_w), dtype=np.uint8) for _ in range(n_frames)]
    path = _write_mib(
        tmp_path / "conc.mib", [_scramble(f) for f in frames],
        num_chips=1, chip_layout="1x1",
    )
    ds = load_mib(path)
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            for k in range(n_frames):
                got = ds.pattern(0, k)
                np.testing.assert_array_equal(got, frames[k])
        except BaseException as e:  # noqa: BLE001 - want to see any failure
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ds.close()
    assert not errors, errors


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
