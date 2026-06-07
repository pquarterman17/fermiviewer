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
