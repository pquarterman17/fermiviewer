"""Wave-D advanced-EELS ops (roadmap 3E): eels_kk, eels_fourier_log,
eels_svd, eels_align_zlp, eels_subpixel_align, eels_richardson_lucy.

Parity contract (ADR 0005 §1): each op's numbers must equal a direct call
to the SAME calc/eels_advanced composition its route calls. Envelope
contract (§5): every value op returns value = {"outputs": [...]} of ADR
0004 {kind, name, data} envelopes with unique names; the two alignment
ops instead return a derived SPECTRUM_IMAGE DataStruct whose metadata
carries the routes' scalar diagnostics (wave-D addendum standing rule).

Fixture: the low-loss SI cube from tests/test_api_eels_adv.py — gaussian
ZLP at 0 eV + plasmon at 20 eV, rank-1 per-pixel amplitude ramp, pixel
(0, 1) rolled +3 channels (alignment ground truth). t/λ = ln(I_t/I_0) is
closed-form from the construction.
"""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.eels_advanced import (
    align_zlp,
    fourier_log,
    kramers_kronig,
    richardson_lucy,
    svd,
    zlp_psf,
)
from fermiviewer.calc.eels_report import svd_view
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import catalogue_eels_advanced  # noqa: F401  (registers the ops)
from fermiviewer.ops._envelopes import OUTPUT_KINDS
from fermiviewer.ops.base import ParamError, produces_value_result

pytestmark = pytest.mark.eels

_WAVE_D_VALUE = ("eels_kk", "eels_fourier_log", "eels_svd", "eels_richardson_lucy")
_WAVE_D_DERIVED = ("eels_align_zlp", "eels_subpixel_align")

NY, NX, NE = 3, 4, 256
SCALE, ORIGIN = 0.25, 40.0  # e_i = (i - 40) * 0.25 → -10..53.75 eV
ENERGY = (np.arange(NE) - ORIGIN) * SCALE
SPEC = 1000.0 * np.exp(-(ENERGY**2) / (2 * 0.5**2)) + 150.0 * np.exp(
    -((ENERGY - 20.0) ** 2) / (2 * 3.0**2)
)
SHIFT_CH = 3  # pixel (0, 1) rolled by +3 channels


def _expected_t_over_lambda() -> float:
    zlp = SPEC[(ENERGY >= -5) & (ENERGY <= 5)].sum()
    return float(np.log(SPEC.sum() / zlp))


def _cube_ds() -> DataStruct:
    data = np.empty((NY, NX, NE))
    for y in range(NY):
        for x in range(NX):
            amp = 1.0 + 0.05 * (y * NX + x)
            s = SPEC * amp
            if (y, x) == (0, 1):
                s = np.roll(s, SHIFT_CH)
            data[y, x] = s
    return DataStruct(
        data=data,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"), AxisCal(SCALE, ORIGIN, "eV")),
        metadata={"source": "synthetic"},
    )


def _spectrum_ds() -> DataStruct:
    return DataStruct(
        data=SPEC.copy(),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(SCALE, ORIGIN, "eV"),),
        metadata={"source": "synthetic"},
    )


def _image_ds() -> DataStruct:
    return DataStruct(
        data=np.ones((5, 6)),
        kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
        metadata={"source": "synthetic"},
    )


@pytest.fixture()
def cube() -> DataStruct:
    return _cube_ds()


def _outputs(result) -> dict[str, dict]:
    """{name: envelope} for a wave op's value, validating the §5 contract
    (unique names included — a duplicate would shadow in this map)."""
    assert result.derived is None
    assert set(result.value) == {"outputs"}
    by_name = {}
    for env in result.value["outputs"]:
        assert set(env) == {"kind", "name", "data"}
        assert env["kind"] in OUTPUT_KINDS
        assert isinstance(env["data"], dict)
        assert env["name"] not in by_name
        by_name[env["name"]] = env
    return by_name


# ── registration ─────────────────────────────────────────────────────


def test_wave_d_eels_adv_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    for name in _WAVE_D_VALUE + _WAVE_D_DERIVED:
        assert by_name[name].category == "eels", name
    for name in _WAVE_D_VALUE:
        # `eels` implies nothing — the explicit flag is required
        assert by_name[name].produces_value, name
        assert produces_value_result(by_name[name]), name
    for name in _WAVE_D_DERIVED:
        # derived-cube producers leave produces_value UNSET
        assert not by_name[name].produces_value, name
        assert not produces_value_result(by_name[name]), name


# ── eels_kk ──────────────────────────────────────────────────────────


def test_kk_op_matches_direct_calc_call(cube) -> None:
    result = ops.run("eels_kk", cube, {"refractive_index": 2.0})
    outs = _outputs(result)
    direct = kramers_kronig(
        cube.energy_axis,
        cube.sum_spectrum(),
        (-5.0, 5.0),
        refractive_index=2.0,
        collection_angle=10.0,
        acc_voltage=200.0,
        thickness=float("nan"),
    )
    for name, arr in (
        ("eps1", direct.eps1),
        ("eps2", direct.eps2),
        ("elf", direct.elf),
        ("optical_conductivity", direct.optical_conductivity),
        ("refractive_index", direct.refractive_index),
    ):
        env = outs[name]
        assert env["kind"] == "curve"
        assert env["data"]["x"] == direct.energy.tolist()
        assert env["data"]["y"] == arr.tolist()
        assert np.isfinite(env["data"]["y"]).all()
    assert len(direct.energy) == int((ENERGY > 0).sum())
    assert outs["thickness_nm"]["data"] == {
        "value": pytest.approx(direct.thickness),
        "unit": "nm",
    }
    assert direct.thickness > 0
    assert outs["t_over_lambda"]["data"]["value"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3
    )


def test_kk_op_accepts_a_plain_spectrum() -> None:
    ds = _spectrum_ds()
    outs = _outputs(ops.run("eels_kk", ds))
    direct = kramers_kronig(ds.energy_axis, ds.sum_spectrum(), (-5.0, 5.0))
    assert outs["eps1"]["data"]["y"] == direct.eps1.tolist()


# ── eels_fourier_log ─────────────────────────────────────────────────


def test_fourier_log_op_matches_direct_calc_and_oracle(cube) -> None:
    result = ops.run("eels_fourier_log", cube)
    outs = _outputs(result)
    energy = cube.energy_axis
    spec = cube.sum_spectrum()
    ssd, t_l = fourier_log(energy, spec, (-5.0, 5.0), regularize=1e-6)
    assert outs["spectrum"]["data"]["x"] == energy.tolist()
    assert outs["spectrum"]["data"]["y"] == spec.tolist()
    assert outs["ssd"]["data"]["y"] == ssd.tolist()
    assert min(outs["ssd"]["data"]["y"]) >= 0.0
    assert outs["t_over_lambda"]["data"]["value"] == pytest.approx(t_l)
    # the closed-form ln(I_t/I_0) oracle from the fixture construction
    assert outs["t_over_lambda"]["data"]["value"] == pytest.approx(
        _expected_t_over_lambda(), rel=1e-3
    )


# ── eels_svd ─────────────────────────────────────────────────────────


def test_svd_op_matches_direct_calc_composition(cube) -> None:
    result = ops.run("eels_svd", cube, {"n_components": 3, "n_score_maps": 2})
    outs = _outputs(result)
    direct = svd(cube.data, cube.energy_axis, 3, False)
    view = svd_view(direct, 2)
    assert view.k_show == 2
    # envelope count: 2 scree curves + an (eigenspectrum, score map) pair
    # per shown component
    assert len(result.value["outputs"]) == 2 + 2 * view.k_show
    assert outs["explained"]["data"]["y"] == direct.explained.tolist()
    assert outs["cumulative"]["data"]["y"] == direct.cumulative.tolist()
    # amplitude ramp + one rolled pixel → rank 2: two components capture
    # essentially all variance
    assert outs["explained"]["data"]["y"][0] > 80.0
    assert outs["cumulative"]["data"]["y"][1] > 99.9
    for j in range(view.k_show):
        eig = outs[f"eigenspectrum_{j + 1}"]
        assert eig["kind"] == "curve"
        assert eig["data"]["x"] == cube.energy_axis.tolist()
        assert eig["data"]["y"] == view.eigenspectra[j].tolist()
        smap = outs[f"score_{j + 1}"]
        assert smap["kind"] == "map"
        assert smap["data"]["values"] == view.score_maps[j].tolist()
        assert np.asarray(smap["data"]["values"]).shape == (NY, NX)


def test_svd_op_defaults_cap_score_maps_at_the_component_count(cube) -> None:
    view = svd_view(svd(cube.data, cube.energy_axis, 0, False), 4)
    result = ops.run("eels_svd", cube)
    assert len(result.value["outputs"]) == 2 + 2 * view.k_show
    # the route's denoise mode has no op (ADR 0005 wave-D addendum)
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eels_svd", cube, {"denoise": True})


# ── eels_align_zlp / eels_subpixel_align ─────────────────────────────


def test_align_zlp_op_returns_derived_cube_with_route_diagnostics(cube) -> None:
    result = ops.run("eels_align_zlp", cube, {"window_lo": -8, "window_hi": 8})
    aligned, shifts = align_zlp(cube.data, cube.energy_axis, (-8.0, 8.0), "mean", subpixel=False)
    assert result.value is None
    derived = result.derived
    assert derived is not None
    assert derived.kind is DataKind.SPECTRUM_IMAGE
    assert derived.axes == cube.axes
    np.testing.assert_array_equal(derived.data, aligned)
    md = derived.metadata
    assert md["parser"] == "derived"
    assert md["source"] == "eels_align_zlp"
    # the rolled pixel's shift is detected: the route's int diagnostic
    assert isinstance(md["max_shift"], int)
    assert md["max_shift"] == SHIFT_CH
    assert abs(int(shifts[0, 1])) == SHIFT_CH
    assert md["shifted_fraction"] == pytest.approx(1 / (NY * NX))


def test_subpixel_align_op_returns_derived_cube_with_route_diagnostics(cube) -> None:
    result = ops.run("eels_subpixel_align", cube, {"window_lo": -8, "window_hi": 8})
    aligned, shifts = align_zlp(cube.data, cube.energy_axis, (-8.0, 8.0), "mean", subpixel=True)
    assert result.value is None
    derived = result.derived
    assert derived is not None
    assert derived.kind is DataKind.SPECTRUM_IMAGE
    assert derived.axes == cube.axes
    np.testing.assert_array_equal(derived.data, aligned)
    md = derived.metadata
    assert md["parser"] == "derived"
    assert md["source"] == "eels_subpixel_align"
    # the sub-pixel route's diagnostics: FLOAT max shift, |shift|>0.01 fraction
    assert isinstance(md["max_shift"], float)
    assert md["max_shift"] == pytest.approx(float(np.abs(shifts).max()))
    assert md["max_shift"] == pytest.approx(SHIFT_CH, abs=0.5)
    assert md["shifted_fraction"] == pytest.approx(float((np.abs(shifts) > 0.01).mean()))


def test_align_ops_reference_choices_are_validated(cube) -> None:
    with pytest.raises(ParamError, match="not in"):
        ops.run("eels_align_zlp", cube, {"reference": "median"})
    with pytest.raises(ParamError, match="not in"):
        ops.run("eels_subpixel_align", cube, {"reference": "median"})
    # 'max' is a legal reference and matches the direct call
    result = ops.run("eels_align_zlp", cube, {"reference": "max"})
    aligned, _ = align_zlp(cube.data, cube.energy_axis, (-20.0, 20.0), "max")
    assert result.derived is not None
    np.testing.assert_array_equal(result.derived.data, aligned)


# ── eels_richardson_lucy ─────────────────────────────────────────────


def test_richardson_lucy_op_matches_direct_calc_composition(cube) -> None:
    result = ops.run("eels_richardson_lucy", cube, {"iterations": 5})
    outs = _outputs(result)
    energy = cube.energy_axis
    spectrum = cube.sum_spectrum()
    psf = zlp_psf(energy, spectrum, (-5.0, 5.0))
    deconv = richardson_lucy(spectrum, psf, iterations=5)
    assert outs["spectrum"]["data"]["x"] == energy.tolist()
    assert outs["spectrum"]["data"]["y"] == spectrum.tolist()
    assert outs["deconvolved"]["data"]["y"] == deconv.tolist()
    assert min(outs["deconvolved"]["data"]["y"]) >= 0.0
    assert outs["iterations"]["data"]["value"] == 5


# ── error paths ──────────────────────────────────────────────────────


def test_cube_ops_reject_non_cube_input() -> None:
    spectrum = _spectrum_ds()
    for name in ("eels_svd", "eels_align_zlp", "eels_subpixel_align"):
        with pytest.raises(ValueError, match="spectrum-image cube"):
            ops.run(name, spectrum)


def test_spectral_ops_reject_a_2d_image() -> None:
    image = _image_ds()
    for name in ("eels_kk", "eels_fourier_log", "eels_richardson_lucy"):
        with pytest.raises(ValueError, match="requires spectral input"):
            ops.run(name, image)


def test_unknown_and_out_of_bounds_params_are_rejected(cube) -> None:
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eels_kk", cube, {"bogus": 1})
    with pytest.raises(ParamError, match="min"):
        ops.run("eels_richardson_lucy", cube, {"iterations": 0})
    with pytest.raises(ParamError, match="min"):
        ops.run("eels_svd", cube, {"n_score_maps": 0})


def test_richardson_lucy_op_propagates_the_zlp_psf_window_error(cube) -> None:
    # a window spanning fewer than 2 channels: zlp_psf's ValueError (the
    # route maps it to 422)
    with pytest.raises(ValueError, match="fewer than 2 channels"):
        ops.run("eels_richardson_lucy", cube, {"zlp_lo": 900, "zlp_hi": 901})
