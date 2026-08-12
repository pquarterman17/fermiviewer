"""EELS/EDS/diffraction batch ops (Scripting #6, remaining half).

Parity contract: each op's output must equal a direct call to the SAME
calc/ function the analogous route calls, on the same synthetic input —
never a reimplementation. Onset energies / line energies come from the
app's own tables (calc.eels.EELS_EDGES, calc.eds.line_energy), matching
the fixtures-derive-from-production-tables convention used elsewhere in
this repo (tools/make_synthetic_si.py).
"""

from __future__ import annotations

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.eds import cliff_lorimer, line_energy
from fermiviewer.calc.eds_maps import element_map, extract_element_maps
from fermiviewer.calc.eels import EELS_EDGES, extract_map
from fermiviewer.calc.eels_quant import ElementEdge, quantify
from fermiviewer.calc.energy_units import to_kev
from fermiviewer.calc.radial import radial_profile
from fermiviewer.calc.smoothing import savgol_derivative, savgol_smooth
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops.base import ParamError
from fermiviewer.ops.catalogue import raster_of

pytestmark = pytest.mark.parser


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


def _eels_cube(h: int = 3, w: int = 4) -> DataStruct:
    """Synthetic SI cube with two core-loss edges (O K + Fe L23) over a
    power-law background — onsets from the app's own EELS_EDGES table."""
    o_edge = _edge("O", "K")
    fe_edge = _edge("Fe", "L23")
    scale, offset, n = 2.0, 300.0, 400
    energy = offset + scale * np.arange(n)             # 300..1098 eV
    background = 8000.0 * (energy / energy[0]) ** -3.0
    spectrum = (
        background
        + 40.0 * (energy >= o_edge.onset_ev)
        + 25.0 * (energy >= fe_edge.onset_ev)
    )
    cube = np.tile(spectrum, (h, w, 1))
    return DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, -offset / scale, "eV"),
        ),
        metadata={"source": "synthetic-eels"},
    )


def _eds_cube(h: int = 4, w: int = 5) -> tuple[DataStruct, float, float]:
    """Synthetic SI cube with Fe Ka + Si Ka peaks — energies from the app's
    own line_energy() table."""
    scale, n = 0.01, 1200
    energy_kev = scale * np.arange(n)                  # 0..11.99 keV
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    si_e, _ = line_energy("Si", beam_kv=200.0)
    spectrum = np.full(n, 2.0)
    spectrum += 60.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
    spectrum += 40.0 * np.exp(-((energy_kev - si_e) ** 2) / (2 * 0.03**2))
    cube = np.tile(spectrum, (h, w, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"),
            AxisCal(scale, 0.0, "keV"),
        ),
        metadata={"source": "synthetic-eds"},
    )
    return ds, float(fe_e), float(si_e)


# ── registration ─────────────────────────────────────────────────────

def test_spectral_ops_are_registered_with_expected_categories() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    assert by_name["eels_map"].category == "eels"
    assert by_name["eels_quantify"].category == "eels"
    assert by_name["eds_element_map"].category == "eds"
    assert by_name["eds_quantify"].category == "eds"
    assert by_name["radial_profile"].category == "diffraction"
    # value-producing ops must say so even though their category isn't
    # "analysis" — this is what /api/batch/operations reports as produces
    assert by_name["eels_quantify"].produces_value
    assert by_name["eds_quantify"].produces_value
    assert by_name["radial_profile"].produces_value
    assert not by_name["eels_map"].produces_value
    assert not by_name["eds_element_map"].produces_value


# ── EELS ─────────────────────────────────────────────────────────────

def test_eels_map_op_matches_direct_calc_call() -> None:
    ds = _eels_cube()
    expected = extract_map(ds.data, ds.energy_axis, (532.0, 572.0),
                           (462.0, 522.0), "powerlaw")
    result = ops.run("eels_map", ds, {
        "signal_lo": 532.0, "signal_hi": 572.0,
        "bg_lo": 462.0, "bg_hi": 522.0, "method": "powerlaw",
    })
    assert result.produces_image
    assert result.derived.kind is DataKind.IMAGE
    np.testing.assert_allclose(result.derived.data, expected)


def test_eels_map_without_background_window_is_a_direct_window_sum() -> None:
    ds = _eels_cube()
    expected = extract_map(ds.data, ds.energy_axis, (532.0, 572.0))
    result = ops.run("eels_map", ds, {"signal_lo": 532.0, "signal_hi": 572.0})
    np.testing.assert_allclose(result.derived.data, expected)


def test_eels_map_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eels_map", img, {"signal_lo": 1.0, "signal_hi": 2.0})


def test_eels_map_rejects_a_1d_spectrum() -> None:
    """A bare 1-D spectrum has no spatial dims to make a MAP from — distinct
    from (and previously untested alongside) the plain-2D-image rejection."""
    spec = DataStruct(
        data=np.ones(10), kind=DataKind.SPECTRUM, axes=(AxisCal(1.0, 0.0, "eV"),),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eels_map", spec, {"signal_lo": 1.0, "signal_hi": 2.0})


def test_eels_map_signal_window_entirely_outside_the_energy_axis_raises() -> None:
    ds = _eels_cube()  # energy axis spans 300..1098 eV
    with pytest.raises(ValueError, match="no channels"):
        ops.run("eels_map", ds, {"signal_lo": 5000.0, "signal_hi": 5100.0})


def test_eels_map_inverted_bg_window_raises_clear_error() -> None:
    """bg_lo > bg_hi leaves the fit-window mask empty (never auto-swapped,
    unlike EDS's element_map) — pinning that EELS's policy is "raise",
    not "silently swap the bounds"."""
    ds = _eels_cube()
    with pytest.raises(ValueError, match="< 2 channels"):
        ops.run("eels_map", ds, {
            "signal_lo": 532.0, "signal_hi": 572.0,
            "bg_lo": 522.0, "bg_hi": 462.0,  # inverted
        })


def test_eels_map_single_energy_channel_direct_sum_still_works() -> None:
    """No background window -> a straight window sum, which needs no
    fit and so works even with a single-channel cube."""
    cube = np.full((3, 4, 1), 5.0)
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "eV")),
    )
    result = ops.run("eels_map", ds, {"signal_lo": -1.0, "signal_hi": 1.0})
    np.testing.assert_allclose(result.derived.data, 5.0)


def test_eels_quantify_op_matches_direct_calc_call() -> None:
    ds = _eels_cube()
    edges = [
        ElementEdge("O", "K", 8, 532.0, (532.0, 572.0), (462.0, 522.0)),
        ElementEdge("Fe", "L", 26, 708.0, (708.0, 748.0), (632.0, 698.0)),
    ]
    expected = quantify(ds.energy_axis, ds.sum_spectrum(), edges, 200.0, 10.0, "powerlaw")
    result = ops.run("eels_quantify", ds, {
        "elements": "O,Fe",
        "shells": "K,L",
        "z": "8,26",
        "onset_ev": "532,708",
        "signal_windows": "532:572,708:748",
        "bg_windows": "462:522,632:698",
        "e0_kv": 200.0,
        "beta_mrad": 10.0,
        "method": "powerlaw",
    })
    assert not result.produces_image
    assert result.value["elements"] == expected.elements
    np.testing.assert_allclose(result.value["atomic_percent"], expected.atomic_percent)
    np.testing.assert_allclose(result.value["intensity"], expected.intensity)
    np.testing.assert_allclose(result.value["sigma"], expected.sigma)


def test_eels_quantify_rejects_mismatched_edge_lists() -> None:
    ds = _eels_cube()
    with pytest.raises(ValueError, match="same non-zero number of edges"):
        ops.run("eels_quantify", ds, {
            "elements": "O,Fe", "shells": "K", "z": "8,26",
            "onset_ev": "532,708", "signal_windows": "532:572,708:748",
            "bg_windows": "462:522,632:698",
        })


def test_eels_quantify_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectral"):
        ops.run("eels_quantify", img, {
            "elements": "O", "shells": "K", "z": "8", "onset_ev": "532",
            "signal_windows": "532:572", "bg_windows": "462:522",
        })


def test_eels_quantify_accepts_a_bare_1d_spectrum() -> None:
    """Unlike eels_map/eds_*, eels_quantify's onset-window math only needs
    the energy axis + a spectrum — a 1-D SPECTRUM (no spatial dims) is
    deliberately valid input here, not just a SPECTRUM_IMAGE cube."""
    ds = _eels_cube()
    spec = DataStruct(
        data=ds.sum_spectrum(), kind=DataKind.SPECTRUM, axes=(ds.axes[-1],),
    )
    result = ops.run("eels_quantify", spec, {
        "elements": "O", "shells": "K", "z": "8", "onset_ev": "532",
        "signal_windows": "532:572", "bg_windows": "462:522",
    })
    assert not result.produces_image
    assert result.value["elements"] == ["O"]


@pytest.mark.parametrize("bad_window", ["708:758:900", "abc:def", ":", "708"])
def test_eels_quantify_malformed_window_string_raises_clear_valueerror(
    bad_window: str,
) -> None:
    ds = _eels_cube()
    with pytest.raises(ValueError):
        ops.run("eels_quantify", ds, {
            "elements": "Fe", "shells": "L", "z": "26", "onset_ev": "708",
            "signal_windows": bad_window, "bg_windows": "632:698",
        })


# ── EDS ──────────────────────────────────────────────────────────────

def test_eds_element_map_op_matches_direct_calc_call() -> None:
    ds, fe_e, _ = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    expected = element_map(ds.data, energy_kev, fe_e - 0.085, fe_e + 0.085,
                           bg="linear", bg_width=float("nan"), bg_gap=0.0,
                           e0_kev=float("nan"))
    result = ops.run("eds_element_map", ds, {
        "e_lo": fe_e - 0.085, "e_hi": fe_e + 0.085, "bg": "linear",
    })
    assert result.produces_image
    np.testing.assert_allclose(result.derived.data, expected)


def test_eds_element_map_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_element_map", img, {"e_lo": 1.0, "e_hi": 2.0})


def test_eds_element_map_rejects_a_1d_spectrum() -> None:
    spec = DataStruct(
        data=np.ones(10), kind=DataKind.SPECTRUM, axes=(AxisCal(1.0, 0.0, "keV"),),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_element_map", spec, {"e_lo": 1.0, "e_hi": 2.0})


def test_eds_element_map_window_outside_axis_returns_a_zero_map_not_an_error() -> None:
    """Deliberately pinning the divergence from EELS's eels_map: EDS's
    element_map returns an all-zero map for a window with no overlapping
    channels rather than raising — this test documents that as the actual,
    intentional calc/ behavior rather than leaving it unverified."""
    ds, _fe_e, _si_e = _eds_cube()
    result = ops.run("eds_element_map", ds, {"e_lo": 900.0, "e_hi": 901.0})
    assert result.produces_image
    np.testing.assert_array_equal(result.derived.data, 0.0)


def test_eds_quantify_op_matches_direct_calc_call() -> None:
    ds, _fe_e, _si_e = _eds_cube()
    energy_kev = to_kev(ds.energy_axis, ds.energy_cal.units)
    entries = extract_element_maps(ds.data, energy_kev, ["Fe", "Si"], half_window=0.085)
    maps = [e.map for e in entries]
    syms = [e.symbol for e in entries]
    expected = cliff_lorimer(maps, syms)
    result = ops.run("eds_quantify", ds, {"elements": "Fe,Si"})
    assert not result.produces_image
    assert result.value["elements"] == syms
    np.testing.assert_allclose(result.value["mean_atomic_pct"], expected.mean_atomic_pct)
    np.testing.assert_allclose(result.value["mean_weight_pct"], expected.mean_weight_pct)
    np.testing.assert_allclose(result.value["k_factors"], expected.k_factors)


def test_eds_quantify_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_quantify", img, {"elements": "Fe"})


def test_eds_quantify_requires_at_least_one_element() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ValueError, match="at least one symbol"):
        ops.run("eds_quantify", ds, {"elements": " , "})


def test_eds_quantify_rejects_a_1d_spectrum() -> None:
    spec = DataStruct(
        data=np.ones(10), kind=DataKind.SPECTRUM, axes=(AxisCal(1.0, 0.0, "keV"),),
    )
    with pytest.raises(ValueError, match="spectrum-image"):
        ops.run("eds_quantify", spec, {"elements": "Fe"})


def test_eds_quantify_elements_with_whitespace_and_blank_entries() -> None:
    """"Fe, ,O" -> ["Fe", "O"], blank/whitespace-only entries dropped —
    exercised through the op, not just _split_csv in isolation."""
    ds, fe_e, si_e = _eds_cube()
    result = ops.run("eds_quantify", ds, {"elements": " Fe ,  , Si "})
    assert result.value["elements"] == ["Fe", "Si"]


def test_eds_quantify_unknown_element_only_warns_then_raises() -> None:
    ds, _, _ = _eds_cube()
    with pytest.warns(UserWarning, match="no known line"):
        with pytest.raises(ValueError, match="no usable element lines"):
            ops.run("eds_quantify", ds, {"elements": "Xx"})


def test_eds_quantify_unknown_element_mixed_with_known_skips_and_continues() -> None:
    ds, fe_e, _ = _eds_cube()
    with pytest.warns(UserWarning, match="no known line"):
        result = ops.run("eds_quantify", ds, {"elements": "Fe,Xx"})
    assert result.value["elements"] == ["Fe"]


def test_eds_quantify_duplicate_elements_does_not_crash() -> None:
    """Not a crash, just a redundant/misleading 50/50 split between two
    identical maps — pinned as documented current behavior, not "fixed"
    into deduplication, since it's a caller input-quality issue, not a
    code-correctness one."""
    ds, fe_e, _ = _eds_cube()
    result = ops.run("eds_quantify", ds, {"elements": "Fe,Fe"})
    assert result.value["elements"] == ["Fe", "Fe"]
    np.testing.assert_allclose(result.value["mean_atomic_pct"], [50.0, 50.0])


def test_eds_quantify_known_line_without_a_builtin_k_factor_warns() -> None:
    """Rb has a tabulated K-line but no Cliff-Lorimer k-factor — an
    intentional diagnostic warning (falls back to k=1.00), asserted here
    with pytest.warns() rather than left as an untested path that would
    otherwise only surface as a surprise CI failure the day someone's
    recipe/test finally exercises it under this repo's strict warning
    filter."""
    h, w = 4, 5
    scale, n = 0.02, 1200  # up to 24 keV, covers Rb Ka (13.395 keV)
    energy_kev = scale * np.arange(n)
    fe_e, _ = line_energy("Fe", beam_kv=200.0)
    rb_e, _ = line_energy("Rb", beam_kv=200.0)
    spectrum = (
        np.full(n, 2.0)
        + 60.0 * np.exp(-((energy_kev - fe_e) ** 2) / (2 * 0.03**2))
        + 40.0 * np.exp(-((energy_kev - rb_e) ** 2) / (2 * 0.03**2))
    )
    cube = np.tile(spectrum, (h, w, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"), AxisCal(scale, 0.0, "keV")),
    )
    with pytest.warns(UserWarning, match="no built-in k-factor"):
        result = ops.run("eds_quantify", ds, {"elements": "Fe,Rb"})
    assert result.value["elements"] == ["Fe", "Rb"]


@pytest.mark.parametrize("method", ["cliff-lorimer", "zaf"])
def test_eds_quantify_on_an_all_nan_cube_raises_no_warning(method: str) -> None:
    """Regression: an all-masked-out map (every pixel's total intensity
    at or below mask_threshold — an all-NaN or all-zero cube being the
    simplest trigger) used to call np.nanmean on a zero-length array,
    emitting "RuntimeWarning: Mean of empty slice" — indistinguishable
    from a real bug under this repo's filterwarnings=error, and a
    needless warning for legitimate callers otherwise."""
    h, w, n = 4, 5, 1200
    cube = np.full((h, w, n), np.nan)
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(1.0, 0.0, "nm"), AxisCal(1.0, 0.0, "nm"), AxisCal(0.01, 0.0, "keV")),
    )
    result = ops.run("eds_quantify", ds, {"elements": "Fe,Si", "method": method})
    assert np.all(np.isnan(result.value["mean_atomic_pct"]))


# ── diffraction ──────────────────────────────────────────────────────

def test_radial_profile_op_matches_direct_calc_call() -> None:
    ds = DataStruct(
        data=np.arange(16 * 16, dtype=np.float64).reshape(16, 16),
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
    )
    expected_radii, expected_avg, expected_max = radial_profile(
        raster_of(ds), center=None, n_bins=5, normalize=False,
    )
    result = ops.run("radial_profile", ds, {"n_bins": 5})
    assert not result.produces_image
    np.testing.assert_allclose(result.value["radii"], expected_radii * ds.pixel_size)

    def clean(arr: np.ndarray) -> list[float | None]:
        return [None if not np.isfinite(v) else float(v) for v in arr]

    assert result.value["avg_profile"] == clean(expected_avg)
    assert result.value["max_profile"] == clean(expected_max)
    assert result.value["unit"] == "nm"


def test_radial_profile_runs_on_a_summed_spectrum_image_cube() -> None:
    """raster_of's SI-summing fallback applies here too (unlike EELS/EDS ops,
    which need the energy axis and must reject a cube's flattened raster)."""
    ds = _eels_cube()
    result = ops.run("radial_profile", ds, {"n_bins": 4})
    assert len(result.value["radii"]) == 4


def test_unknown_param_still_rejected_for_spectral_ops() -> None:
    ds, _, _ = _eds_cube()
    with pytest.raises(ParamError, match="unknown param"):
        ops.run("eds_quantify", ds, {"elements": "Fe", "typo": 1})


# ── Smoothing (Savitzky-Golay) ───────────────────────────────────────

def test_smoothing_ops_are_registered_with_expected_category() -> None:
    by_name = {s.name: s for s in ops.list_ops()}
    assert by_name["savgol"].category == "spectral"
    assert by_name["savgol_derivative"].category == "spectral"
    # both produce a derived spectrum, not a value
    assert not by_name["savgol"].produces_value
    assert not by_name["savgol_derivative"].produces_value


def test_savgol_op_matches_direct_calc_call_on_a_1d_spectrum() -> None:
    ds = _eels_cube()
    spec = DataStruct(
        data=ds.sum_spectrum(), kind=DataKind.SPECTRUM, axes=(ds.axes[-1],),
    )
    expected = savgol_smooth(spec.sum_spectrum(), window=11, polyorder=3)
    result = ops.run("savgol", spec, {"window": 11, "polyorder": 3})
    assert result.produces_image  # derived DataStruct, even though kind is SPECTRUM
    assert result.derived.kind is DataKind.SPECTRUM
    np.testing.assert_allclose(result.derived.data, expected)


def test_savgol_op_on_a_spectrum_image_cube_sums_spatially_first() -> None:
    """A SPECTRUM_IMAGE cube must be reduced via sum_spectrum() before the
    1-D calc call — matching eels_quantify's convention for cube input."""
    ds = _eels_cube()
    expected = savgol_smooth(ds.sum_spectrum(), window=11, polyorder=3)
    result = ops.run("savgol", ds, {"window": 11, "polyorder": 3})
    np.testing.assert_allclose(result.derived.data, expected)
    assert result.derived.data.shape == (ds.n_channels,)


def test_savgol_op_defaults_are_window_11_polyorder_3() -> None:
    ds = _eels_cube()
    expected = savgol_smooth(ds.sum_spectrum(), window=11, polyorder=3)
    result = ops.run("savgol", ds)
    np.testing.assert_allclose(result.derived.data, expected)


def test_savgol_op_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectral"):
        ops.run("savgol", img)


def test_savgol_op_propagates_calc_validation_errors() -> None:
    ds = _eels_cube()  # 400 channels
    with pytest.raises(ValueError, match="window must be odd"):
        ops.run("savgol", ds, {"window": 10, "polyorder": 3})


def test_savgol_derivative_op_matches_direct_calc_call_using_axis_scale_as_delta() -> None:
    """The EELS fixture's energy axis has scale=2.0 (eV/channel) — a
    non-unit delta, so a bug that hardcoded delta=1.0 in the op would
    produce a result exactly 2x the correct one and this test would fail."""
    ds = _eels_cube()
    assert ds.energy_cal.scale == pytest.approx(2.0)  # pin the non-unit delta
    expected = savgol_derivative(
        ds.sum_spectrum(), window=11, polyorder=3, order=1, delta=ds.energy_cal.scale,
    )
    result = ops.run("savgol_derivative", ds, {"window": 11, "polyorder": 3, "order": 1})
    assert result.derived.kind is DataKind.SPECTRUM
    np.testing.assert_allclose(result.derived.data, expected)


def test_savgol_derivative_op_falls_back_to_delta_1_when_axis_uncalibrated() -> None:
    """The axis's scale is 5.0, but units="" makes it uncalibrated —
    _savgol_delta must fall back to 1.0, not read the (misleading) scale.
    A bug that read cal.scale unconditionally would fail this test."""
    cube = np.tile(np.linspace(0.0, 100.0, 50) ** 2, (2, 2, 1))
    ds = DataStruct(
        data=cube, kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal(scale=5.0, units="")),  # uncalibrated
    )
    assert not ds.energy_cal.calibrated
    expected = savgol_derivative(ds.sum_spectrum(), window=11, polyorder=3, order=1, delta=1.0)
    result = ops.run("savgol_derivative", ds, {"window": 11, "polyorder": 3, "order": 1})
    np.testing.assert_allclose(result.derived.data, expected)


def test_savgol_derivative_op_defaults_order_to_1() -> None:
    ds = _eels_cube()
    expected = savgol_derivative(
        ds.sum_spectrum(), window=11, polyorder=3, order=1, delta=ds.energy_cal.scale,
    )
    result = ops.run("savgol_derivative", ds, {"window": 11, "polyorder": 3})
    np.testing.assert_allclose(result.derived.data, expected)


def test_savgol_derivative_op_rejects_a_plain_image() -> None:
    img = DataStruct(
        data=np.zeros((4, 4)), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()),
    )
    with pytest.raises(ValueError, match="spectral"):
        ops.run("savgol_derivative", img)


def test_savgol_derivative_op_propagates_calc_validation_errors() -> None:
    ds = _eels_cube()
    with pytest.raises(ValueError, match=r"1 <= order <= polyorder"):
        ops.run("savgol_derivative", ds, {"window": 11, "polyorder": 3, "order": 4})
