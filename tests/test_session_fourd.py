"""FourDStore — 4D-STEM session store with its own id namespace."""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.fourd.dataset import FourDDataset
from fermiviewer.datastruct import AxisCal
from fermiviewer.session_fourd import FourDStore, UnknownFourDError

pytestmark = pytest.mark.api


def _dataset(rows=2, cols=2, det_h=3, det_w=3) -> FourDDataset:
    cube = np.zeros((rows, cols, det_h, det_w), dtype=np.float64)
    return FourDDataset(
        handle=cube,
        scan_shape=(rows, cols),
        det_shape=(det_h, det_w),
        scan_axes=(AxisCal(), AxisCal()),
        det_axes=(AxisCal(), AxisCal()),
        dtype=cube.dtype,
    )


def test_add_returns_namespaced_id() -> None:
    store = FourDStore()
    fourd_id = store.add(_dataset(), "sample")
    assert fourd_id.startswith("4d-")


def test_id_namespace_never_collides_with_hex_image_ids() -> None:
    """A 2D-image route given a fourd id must fail cleanly — the id shapes
    are disjoint by construction (4d-N vs 12-char hex)."""
    store = FourDStore()
    fourd_id = store.add(_dataset(), "sample")
    assert not all(c in "0123456789abcdef" for c in fourd_id)


def test_get_unknown_id_raises() -> None:
    store = FourDStore()
    with pytest.raises(UnknownFourDError):
        store.get("4d-999")


def test_name_and_source_path_roundtrip() -> None:
    store = FourDStore()
    fourd_id = store.add(_dataset(), "sample.mib", source_path="/data/sample.mib")
    assert store.name(fourd_id) == "sample.mib"
    assert store.source_path(fourd_id) == "/data/sample.mib"


def test_source_path_defaults_to_none() -> None:
    store = FourDStore()
    fourd_id = store.add(_dataset(), "sample")
    assert store.source_path(fourd_id) is None


def test_ids_lists_every_registered_dataset() -> None:
    store = FourDStore()
    a = store.add(_dataset(), "a")
    b = store.add(_dataset(), "b")
    assert sorted(store.ids()) == sorted([a, b])


def test_nav_image_id_roundtrip() -> None:
    store = FourDStore()
    fourd_id = store.add(_dataset(), "a")
    assert store.nav_image_id(fourd_id) is None
    store.set_nav_image_id(fourd_id, "abc123")
    assert store.nav_image_id(fourd_id) == "abc123"


def test_close_calls_dataset_close_and_forgets_it() -> None:
    store = FourDStore()
    closed = []
    ds = _dataset()
    ds.close = lambda: closed.append(True)  # type: ignore[method-assign]
    fourd_id = store.add(ds, "a")
    store.close(fourd_id)
    assert closed == [True]
    with pytest.raises(UnknownFourDError):
        store.get(fourd_id)


def test_close_unknown_id_is_a_noop() -> None:
    store = FourDStore()
    store.close("4d-nope")  # must not raise


def test_clear_closes_every_dataset() -> None:
    store = FourDStore()
    closed = []
    for name in ("a", "b", "c"):
        ds = _dataset()
        ds.close = lambda closed=closed: closed.append(True)  # type: ignore[method-assign]
        store.add(ds, name)
    store.clear()
    assert closed == [True, True, True]
    assert store.ids() == []
