"""DataStruct contract tests."""

import numpy as np
import pytest

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct


def test_axis_origin_convention() -> None:
    # DM convention: value = (index − origin) × scale
    cal = AxisCal(scale=0.05, origin=40, units="eV")
    ax = cal.axis(5)
    assert ax[0] == pytest.approx(-2.0)
    assert ax[1] - ax[0] == pytest.approx(0.05)


def test_uncalibrated_axis_falls_back_to_indices() -> None:
    assert AxisCal(scale=0.0).axis(3).tolist() == [0, 1, 2]
    assert AxisCal(scale=float("nan")).axis(3).tolist() == [0, 1, 2]
    assert not AxisCal(scale=1.0, units="").calibrated


def test_kind_dim_validation() -> None:
    with pytest.raises(ValueError, match="2D"):
        DataStruct(np.zeros(4), DataKind.IMAGE, (AxisCal(),))
    with pytest.raises(ValueError, match="axes count"):
        DataStruct(np.zeros((2, 2)), DataKind.IMAGE, (AxisCal(),))
    with pytest.raises(ValueError, match="empty"):
        DataStruct(np.zeros((0, 2)), DataKind.IMAGE, (AxisCal(), AxisCal()))


def test_data_is_immutable() -> None:
    ds = DataStruct(np.ones((2, 3)), DataKind.IMAGE, (AxisCal(), AxisCal()))
    with pytest.raises((ValueError, RuntimeError)):
        ds.data[0, 0] = 5


def test_sum_spectrum_si_cube() -> None:
    cube = np.arange(24, dtype=np.float64).reshape(2, 3, 4)
    ds = DataStruct(
        cube, DataKind.SPECTRUM_IMAGE,
        (AxisCal(), AxisCal(), AxisCal(scale=0.1, units="eV")),
    )
    assert ds.n_channels == 4
    assert ds.sum_spectrum().shape == (4,)
    assert ds.sum_spectrum()[0] == cube[:, :, 0].sum()
    assert ds.energy_axis[1] == pytest.approx(0.1)


@pytest.mark.parametrize(
    "kind, data",
    [
        (DataKind.SPECTRUM, np.ones(8, dtype=np.float64)),   # was a read-only view
        (DataKind.SPECTRUM, np.ones(8, dtype=np.float32)),   # copy via dtype cast
        (DataKind.SPECTRUM_IMAGE, np.ones((2, 2, 8), dtype=np.float64)),  # fresh .sum()
    ],
)
def test_sum_spectrum_is_writeable_copy(kind, data) -> None:
    # sum_spectrum() must return a mutable copy regardless of source dtype/kind:
    # the frozen DataStruct buffer is read-only and np.asarray on an already-
    # float64 1D spectrum used to leak that read-only flag through a view.
    axes = (AxisCal(scale=0.1, units="eV"),) if kind is DataKind.SPECTRUM \
        else (AxisCal(), AxisCal(), AxisCal(scale=0.1, units="eV"))
    ds = DataStruct(data, kind, axes)
    spec = ds.sum_spectrum()
    assert spec.flags.writeable
    spec[0] = 999.0  # must not raise, and must not touch the frozen source
    assert not ds.data.flags.writeable


def test_datakind_membership_uses_call_not_in() -> None:
    # `"image" in DataKind` raises TypeError on CPython < 3.12 (the supported
    # floor), so the canonical lookup is the constructor / identity check.
    assert DataKind("image") is DataKind.IMAGE
    assert DataKind.IMAGE == "image"
    with pytest.raises(ValueError):
        DataKind("not_a_kind")
