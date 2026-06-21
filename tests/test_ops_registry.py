"""Operation registry + catalogue (Scripting #1): registration, param
validation, and that every op round-trips a synthetic DataStruct. The
filter ops are checked against the calc functions the routes also call so
the op layer can't drift from the HTTP path."""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc import filters
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import ParamError

pytestmark = pytest.mark.parser


def _image(h: int = 8, w: int = 10) -> DataStruct:
    data = np.arange(h * w, dtype=np.float64).reshape(h, w)
    return DataStruct(
        data=data,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )


def test_catalogue_registers_expected_ops() -> None:
    names = {s.name for s in ops.list_ops()}
    assert {"gaussian", "median", "bin", "rotate90", "image_stats"} <= names
    assert {s.name for s in ops.list_ops("filter")} >= {"gaussian", "median"}


def test_every_op_runs_on_a_synthetic_image() -> None:
    ds = _image()
    for spec in ops.list_ops():
        result = ops.run(spec.name, ds)  # defaults only
        assert result.op == spec.name
        if result.produces_image:
            assert result.derived.kind is DataKind.IMAGE
            assert result.derived.data.ndim == 2
        else:
            assert result.value is not None


def test_gaussian_op_matches_the_calc_function() -> None:
    ds = _image()
    result = ops.run("gaussian", ds, {"sigma": 2.0})
    expected = filters.apply_gaussian(np.asarray(ds.data, dtype=np.float64), sigma=2.0)
    assert np.allclose(result.derived.data, expected)
    assert result.params["sigma"] == 2.0  # resolved params recorded


def test_bin_op_resamples_and_scales_calibration() -> None:
    ds = _image(8, 8)
    result = ops.run("bin", ds, {"bin_size": 2})
    assert result.derived.data.shape == (4, 4)
    # pixel size doubles when binning 2× (calibration carried through)
    assert result.derived.pixel_cal.scale == pytest.approx(1.0)
    assert result.derived.pixel_cal.units == "nm"


def test_rotate90_swaps_the_axes() -> None:
    ds = _image(4, 6)
    result = ops.run("rotate90", ds)
    assert result.derived.data.shape == (6, 4)  # transposed dims


def test_image_stats_returns_a_value_not_an_image() -> None:
    ds = _image()
    result = ops.run("image_stats", ds)
    assert not result.produces_image
    assert result.value["max"] == float(np.asarray(ds.data).max())
    assert result.value["shape"] == [8, 10]


def test_unknown_op_and_bad_params_raise() -> None:
    ds = _image()
    with pytest.raises(ops.UnknownOpError):
        ops.run("does_not_exist", ds)
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("gaussian", ds, {"sgima": 1.0})  # typo'd param
    with pytest.raises(ParamError, match="min"):
        ops.run("gaussian", ds, {"sigma": -1.0})  # below minimum
    with pytest.raises(ParamError, match="not in"):
        ops.run("bin", ds, {"mode": "median"})  # not an allowed choice


def test_bool_param_coercion_handles_string_falsy() -> None:
    from fermiviewer.ops.base import OpParam

    p = OpParam(bool, default=False)
    # the footgun: plain bool("false") is True — these must read as False
    for falsy in ("false", "False", "no", "0", "off", "", " FALSE "):
        assert p.coerce("flag", falsy) is False, falsy
    for truthy in ("true", "yes", "1", "on", 1, True):
        assert p.coerce("flag", truthy) is True, truthy
    assert p.coerce("flag", 0) is False
    assert p.coerce("flag", False) is False


def test_spectrum_input_is_rejected_by_raster_ops() -> None:
    spec = DataStruct(
        data=np.arange(6, dtype=np.float64),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, 0.0, "eV"),),
    )
    with pytest.raises(ValueError, match="raster"):
        ops.run("gaussian", spec)
