"""HyperSpy-4D reader (PLAN_4DSTEM #2) + the registry's 4D content sniffer."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from fermiviewer.io.fourd.hspy4d import (
    Hspy4DFormatError,
    is_fourd_hdf5,
    load_hspy4d,
)
from fermiviewer.io.hspy import HspyFormatError, load_hspy
from fermiviewer.io.registry import is_fourd_path, load_auto, load_fourd_auto

pytestmark = pytest.mark.parser


def _write_hspy(path: Path, data: np.ndarray, axes: list[dict]) -> Path:
    """axes: list of dicts with scale/offset/units/name/navigate (array order).
    Mirrors test_io_hspy.py's helper so both stay obviously in sync."""
    with h5py.File(path, "w") as f:
        exp = f.create_group("Experiments/sig")
        exp.create_dataset("data", data=data)
        for i, a in enumerate(axes):
            g = exp.create_group(f"axis-{i}")
            for k, v in a.items():
                g.attrs[k] = v
    return path


def _nav_axis(name: str, scale: float = 1.0, units: str = "nm") -> dict:
    return {"scale": scale, "offset": 0.0, "units": units, "name": name, "navigate": True}


def _sig_axis(name: str, scale: float = 1.0, units: str = "mrad") -> dict:
    return {"scale": scale, "offset": 0.0, "units": units, "name": name, "navigate": False}


def test_4d_loads_with_navigate_attrs(tmp_path: Path) -> None:
    data = np.arange(2 * 3 * 4 * 5, dtype=np.float32).reshape(2, 3, 4, 5)
    fp = _write_hspy(
        tmp_path / "cube.hspy",
        data,
        [
            _nav_axis("y", scale=2.0, units="nm"),
            _nav_axis("x", scale=1.5, units="nm"),
            _sig_axis("ky", scale=0.1, units="mrad"),
            _sig_axis("kx", scale=0.2, units="mrad"),
        ],
    )
    ds = load_hspy4d(fp)
    try:
        assert ds.scan_shape == (2, 3)
        assert ds.det_shape == (4, 5)
        assert ds.dtype == np.dtype(np.float32)
        assert ds.scan_axes[0].scale == pytest.approx(2.0)
        assert ds.scan_axes[0].units == "nm"
        assert ds.scan_axes[1].scale == pytest.approx(1.5)
        # det_axes calibration (PLAN_4DSTEM #14): the aperture-radii-in-mrad
        # UI needs the SCALE, not just the units label — pin both.
        assert ds.det_axes[0].units == "mrad"
        assert ds.det_axes[0].scale == pytest.approx(0.1)
        assert ds.det_axes[1].units == "mrad"
        assert ds.det_axes[1].scale == pytest.approx(0.2)
        np.testing.assert_array_equal(ds.pattern(1, 2), data[1, 2])
        np.testing.assert_allclose(ds.nav_image, data.sum(axis=(2, 3)))
        assert ds.metadata["parser"] == "hspy4d"
    finally:
        ds.close()


def test_4d_without_navigate_attrs_falls_back_to_leading_axes(tmp_path: Path) -> None:
    data = np.arange(2 * 2 * 3 * 3, dtype=np.uint8).reshape(2, 2, 3, 3)
    fp = _write_hspy(
        tmp_path / "nonav.hspy",
        data,
        [
            {"scale": 1.0, "offset": 0.0, "units": "", "name": f"a{i}"}
            for i in range(4)
        ],
    )
    ds = load_hspy4d(fp)
    try:
        assert ds.scan_shape == (2, 2)
        assert ds.det_shape == (3, 3)
    finally:
        ds.close()


def test_4d_with_non_leading_navigate_axes_raises(tmp_path: Path) -> None:
    data = np.zeros((2, 3, 4, 5), dtype=np.float32)
    fp = _write_hspy(
        tmp_path / "reordered.hspy",
        data,
        [
            _sig_axis("ky"),
            _nav_axis("y"),
            _nav_axis("x"),
            _sig_axis("kx"),
        ],
    )
    with pytest.raises(Hspy4DFormatError, match="leading"):
        load_hspy4d(fp)


def test_non_hdf5_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.hspy"
    bad.write_bytes(b"not hdf5 at all")
    with pytest.raises(Hspy4DFormatError, match="not an HDF5"):
        load_hspy4d(bad)
    assert is_fourd_hdf5(bad) is False


def test_no_experiments_group_raises(tmp_path: Path) -> None:
    fp = tmp_path / "noexp.hspy"
    with h5py.File(fp, "w") as f:
        f.create_group("NotExperiments")
    with pytest.raises(Hspy4DFormatError, match="no experiment"):
        load_hspy4d(fp)
    assert is_fourd_hdf5(fp) is False


# ── multiple experiments in one file: bug-hunt pass ────────────────────
#
# A file can hold more than one HyperSpy signal under Experiments/. Which
# one wins must be deterministic — and, critically, a non-4D experiment
# sorting before a 4D one must never make the 4D signal invisible.


def _write_multi_hspy(path: Path, experiments: dict[str, tuple[np.ndarray, list[dict]]]) -> Path:
    with h5py.File(path, "w") as f:
        for name, (data, axes) in experiments.items():
            exp = f.create_group(f"Experiments/{name}")
            exp.create_dataset("data", data=data)
            for i, a in enumerate(axes):
                g = exp.create_group(f"axis-{i}")
                for k, v in a.items():
                    g.attrs[k] = v
    return path


def test_non_4d_experiment_sorting_first_does_not_hide_a_4d_one(tmp_path: Path) -> None:
    """The bug this pins: a 3D experiment named alphabetically before a 4D
    one used to make `is_fourd_hdf5`/`load_hspy4d` pick the (wrong, non-4D)
    first experiment and report "not 4D" — silently routing the WHOLE FILE
    to the 3D loader and losing the 4D signal entirely, rather than
    resolving to whichever experiment actually is 4D."""
    data3d = np.zeros((4, 5, 6), dtype=np.float32)
    data4d = np.arange(2 * 2 * 3 * 3, dtype=np.float32).reshape(2, 2, 3, 3)
    fp = _write_multi_hspy(
        tmp_path / "mixed.hspy",
        {
            "aaa_3d": (data3d, [_nav_axis("y"), _nav_axis("x"), _sig_axis("e", units="eV")]),
            "zzz_4d": (data4d, [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")]),
        },
    )
    # sanity: h5py really does iterate "aaa_3d" before "zzz_4d" here
    with h5py.File(fp, "r") as f:
        assert list(f["Experiments"].keys()) == ["aaa_3d", "zzz_4d"]

    assert is_fourd_hdf5(fp) is True
    ds = load_hspy4d(fp)
    try:
        assert ds.scan_shape == (2, 2)
        assert ds.det_shape == (3, 3)
        np.testing.assert_array_equal(ds.pattern(0, 1), data4d[0, 1])
    finally:
        ds.close()


def test_two_4d_experiments_resolves_to_first_by_iteration_order(tmp_path: Path) -> None:
    """Deterministic, documented policy: when more than one experiment is
    4D, the first by iteration order wins (h5py's default group ordering is
    alphabetical by name)."""
    first = np.zeros((2, 2, 3, 3), dtype=np.float32)
    second = np.ones((2, 2, 3, 3), dtype=np.float32) * 99.0
    fp = _write_multi_hspy(
        tmp_path / "two4d.hspy",
        {
            "aaa": (first, [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")]),
            "zzz": (second, [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")]),
        },
    )
    ds = load_hspy4d(fp)
    try:
        np.testing.assert_array_equal(ds.pattern(0, 0), first[0, 0])
        assert ds.metadata["hspy_experiment"] == "aaa"
    finally:
        ds.close()


def test_no_4d_experiment_among_several_reports_actual_dimensionality(
    tmp_path: Path,
) -> None:
    """When NO experiment is 4D, the error message should describe an
    actual experiment's real shape (still a clear error), not a generic
    "no data array" that would be misleading for a file that does have
    signals, just none of them 4D."""
    data2d = np.zeros((4, 5), dtype=np.float32)
    data3d = np.zeros((4, 5, 6), dtype=np.float32)
    fp = _write_multi_hspy(
        tmp_path / "no4d.hspy",
        {
            "im": (data2d, [_nav_axis("y"), _nav_axis("x")]),
            "cube": (data3d, [_nav_axis("y"), _nav_axis("x"), _sig_axis("e", units="eV")]),
        },
    )
    assert is_fourd_hdf5(fp) is False
    with pytest.raises(Hspy4DFormatError, match="not 4D-STEM"):
        load_hspy4d(fp)


# ── lifecycle: close(), held references, Windows file-handle release ──


def test_closed_dataset_pattern_and_iter_scan_rows_raise_clear_errors(
    tmp_path: Path,
) -> None:
    """Before this fix, accessing a closed hspy4d dataset raised an opaque
    h5py RuntimeError ("Unable to synchronously get dataspace") instead of
    a clear "dataset is closed" error."""
    data = np.arange(2 * 3 * 4 * 5, dtype=np.float32).reshape(2, 3, 4, 5)
    fp = _write_hspy(
        tmp_path / "closeme.hspy", data,
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    ds = load_hspy4d(fp)
    ds.close()
    with pytest.raises(RuntimeError, match="closed"):
        ds.pattern(0, 0)
    with pytest.raises(RuntimeError, match="closed"):
        next(ds.iter_scan_rows())


def test_double_close_is_a_noop(tmp_path: Path) -> None:
    data = np.zeros((2, 2, 3, 3), dtype=np.float32)
    fp = _write_hspy(
        tmp_path / "doubleclose.hspy", data,
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    ds = load_hspy4d(fp)
    ds.close()
    ds.close()  # must not raise


def test_file_deletable_after_close_on_windows(tmp_path: Path) -> None:
    """CRITICAL on Windows: the h5py.File handle must be fully released by
    close() so the source file can be deleted/replaced afterward."""
    import gc
    import os

    data = np.arange(2 * 2 * 3 * 3, dtype=np.float32).reshape(2, 2, 3, 3)
    fp = _write_hspy(
        tmp_path / "deleteme.hspy", data,
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    ds = load_hspy4d(fp)
    held_pattern = ds.pattern(0, 0)
    ds.close()
    gc.collect()
    os.remove(fp)  # must not raise PermissionError ([WinError 32])
    np.testing.assert_array_equal(held_pattern, data[0, 0])


def test_opening_the_same_file_twice_gives_independent_usable_datasets(
    tmp_path: Path,
) -> None:
    data = np.arange(2 * 2 * 3 * 3, dtype=np.float32).reshape(2, 2, 3, 3)
    fp = _write_hspy(
        tmp_path / "dual.hspy", data,
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    ds_a = load_hspy4d(fp)
    ds_b = load_hspy4d(fp)
    np.testing.assert_array_equal(ds_a.pattern(0, 0), data[0, 0])
    np.testing.assert_array_equal(ds_b.pattern(0, 0), data[0, 0])
    ds_a.close()
    # closing the first must not break the second
    np.testing.assert_array_equal(ds_b.pattern(0, 1), data[0, 1])
    ds_b.close()


# ── sniffer: 2D/3D files are left to the existing loader ──────────────


def test_is_fourd_hdf5_false_for_2d(tmp_path: Path) -> None:
    fp = _write_hspy(
        tmp_path / "im.hspy",
        np.zeros((3, 4), dtype=np.float32),
        [_nav_axis("y"), _nav_axis("x")],
    )
    assert is_fourd_hdf5(fp) is False
    assert is_fourd_path(fp) is False
    # existing 3D-and-under loader still handles it, untouched
    ds = load_hspy(fp)
    assert ds.data.shape == (3, 4)


def test_is_fourd_hdf5_true_for_4d(tmp_path: Path) -> None:
    fp = _write_hspy(
        tmp_path / "cube.hspy",
        np.zeros((2, 2, 3, 3), dtype=np.float32),
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    assert is_fourd_hdf5(fp) is True
    assert is_fourd_path(fp) is True
    # the existing 3D loader must still refuse it directly (unchanged
    # behavior — test_io_hspy.py::test_hspy_4d_rejected covers this too)
    with pytest.raises(HspyFormatError, match="4D"):
        load_hspy(fp)


def test_load_fourd_auto_routes_4d_hspy(tmp_path: Path) -> None:
    data = np.arange(2 * 2 * 3 * 3, dtype=np.float32).reshape(2, 2, 3, 3)
    fp = _write_hspy(
        tmp_path / "auto.hspy",
        data,
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    ds = load_fourd_auto(fp)
    try:
        np.testing.assert_array_equal(ds.pattern(0, 1), data[0, 1])
    finally:
        ds.close()


def test_load_auto_still_rejects_4d(tmp_path: Path) -> None:
    fp = _write_hspy(
        tmp_path / "still4d.hspy",
        np.zeros((2, 2, 3, 3), dtype=np.float32),
        [_nav_axis("y"), _nav_axis("x"), _sig_axis("ky"), _sig_axis("kx")],
    )
    with pytest.raises(HspyFormatError, match="4D"):
        load_auto(fp)


# ── realdata: real 4D-STEM HyperSpy files (CC BY 4.0, Zenodo
# 10.5281/zenodo.15490547) ─────────────────────────────────────────────


@pytest.mark.realdata
def test_real_twinned_nanowire_shape_and_axes(fourd_corpus: Path) -> None:
    ds = load_hspy4d(fourd_corpus / "twinned_nanowire.hdf5")
    try:
        assert ds.scan_shape == (100, 30)
        assert ds.det_shape == (144, 144)
        assert ds.dtype == np.dtype(np.uint8)
        assert ds.scan_axes[0].units == "nm"
        assert ds.scan_axes[0].scale == pytest.approx(12.5)
        assert ds.scan_axes[1].scale == pytest.approx(10.0)
        assert ds.det_axes[0].units == "pixels"
    finally:
        ds.close()


@pytest.mark.realdata
def test_real_small_ptychography_shape(fourd_corpus: Path) -> None:
    ds = load_hspy4d(fourd_corpus / "smallPtychography.hspy")
    try:
        assert ds.scan_shape == (246, 246)
        assert ds.det_shape == (8, 8)
        assert ds.det_axes[0].units == "mrad"
    finally:
        ds.close()


@pytest.mark.realdata
def test_real_au_xgrating_is_not_4d(fourd_corpus: Path) -> None:
    """2D file — must NOT be claimed by the 4D path (brief's explicit
    non-4D regression check)."""
    fp = fourd_corpus / "au_xgrating_100kX.hspy"
    assert is_fourd_hdf5(fp) is False
    assert is_fourd_path(fp) is False
    ds = load_hspy(fp)
    assert ds.data.ndim == 2


@pytest.mark.realdata
def test_real_pattern_matches_hand_sliced_h5py(fourd_corpus: Path) -> None:
    fp = fourd_corpus / "twinned_nanowire.hdf5"
    ds = load_hspy4d(fp)
    try:
        with h5py.File(fp, "r") as f:
            expected = np.asarray(f["Experiments/__unnamed__/data"][7, 3])
        np.testing.assert_array_equal(ds.pattern(7, 3), expected)
    finally:
        ds.close()
