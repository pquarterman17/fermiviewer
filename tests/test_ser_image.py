"""Synthetic-fixture tests for the SER 0x4122 (2-D image) path's error/edge
branches. The happy path is covered by the committed `test_ser.ser` golden;
these vectors exercise guards that golden/realdata corpora don't happen to
trip (invalid dims, no valid elements, truncation)."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.datastruct import DataKind
from fermiviewer.io.ser import load_ser
from fixtures.ser import write_ser_image

pytestmark = pytest.mark.parser


def test_image_round_trip(tmp_path):
    p = tmp_path / "img.ser"
    write_ser_image(p, width=4, height=3, dtype_code=2)
    ds = load_ser(p)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (3, 4)
    assert ds.data[0, 0] == 1
    assert ds.data[2, 3] == 12  # last of 1..12


def test_1x1_image(tmp_path):
    p = tmp_path / "one.ser"
    write_ser_image(p, width=1, height=1, dtype_code=2)
    ds = load_ser(p)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (1, 1)
    assert ds.data[0, 0] == 1


def test_zero_width_raises(tmp_path):
    p = tmp_path / "zerow.ser"
    write_ser_image(p, width=0, height=4)
    with pytest.raises(ValueError, match="invalid SER dimensions"):
        load_ser(p)


def test_zero_height_raises(tmp_path):
    p = tmp_path / "zeroh.ser"
    write_ser_image(p, width=4, height=0)
    with pytest.raises(ValueError, match="invalid SER dimensions"):
        load_ser(p)


def test_no_valid_elements_raises(tmp_path):
    p = tmp_path / "novalid.ser"
    write_ser_image(p, width=4, height=4, valid_elements=0)
    with pytest.raises(ValueError, match="no valid data elements"):
        load_ser(p)


def test_truncated_image_zero_pads(tmp_path):
    p = tmp_path / "full.ser"
    write_ser_image(p, width=8, height=8, dtype_code=2)  # u2, 128-byte payload
    raw = p.read_bytes()
    short = tmp_path / "short.ser"
    short.write_bytes(raw[:-40])  # cut off the last 20 pixels
    with pytest.warns(UserWarning, match="zero-padding"):
        ds = load_ser(short)
    assert ds.kind is DataKind.IMAGE
    assert ds.data.shape == (8, 8)
    assert ds.data.flat[0] == 1     # untouched
    assert ds.data.flat[-1] == 0    # chopped off → zero-padded
