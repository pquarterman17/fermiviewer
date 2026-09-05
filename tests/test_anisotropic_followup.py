"""The single-scale sites v0.4.0 listed under *Known limitations*.

Each of these multiplied a pixel-space quantity by `pixel_size`, the
COLUMN extent, whatever direction the quantity ran in. On anisotropic
pixels that is a plausible number in the right unit, just not the length
of the thing measured. Every test here states the defect as the number it
produced, checks the corrected number against geometry rather than
another code path, and pins the contract that matters more: on SQUARE
pixels nothing moves at all.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.special import erf

from fermiviewer.calc.grain_layers import LayerBounds, measure_grains_by_layer
from fermiviewer.calc.layers import analyze_layers, recompute_layers
from fermiviewer.calc.layers_multi import compare_layers_across_maps
from fermiviewer.calc.profile_stats import measure_distance
from fermiviewer.calc.profiles import line_profile, line_profile_stats, polyline_profile
from fermiviewer.calc.radial import azimuthal_integrate, radial_profile, radial_profile_stats
from fermiviewer.calc.trace_roughness import analyze_trace
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

ALLOWED_HOSTS.add("testserver")

#: pixels 3 wide (columns) and 4 tall (rows): the CHANGELOG's example
ROW, COL = 4.0, 3.0
SPACING = (ROW, COL)
#: a 30-column, 40-row segment on those pixels is 183.6 units long
TRUE_LENGTH = float(np.hypot(30 * COL, 40 * ROW))
#: ... where hypot-then-scale printed 150
OLD_LENGTH = float(np.hypot(30, 40) * COL)


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _ds(img: np.ndarray, row: float, col: float, unit: str = "nm") -> DataStruct:
    return DataStruct(
        data=np.asarray(img, dtype=np.float64),
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=row, units=unit), AxisCal(scale=col, units=unit)),
        metadata={},
    )


# ── calc/profiles.py ───────────────────────────────────────────────────


def test_line_profile_distance_axis_uses_both_extents() -> None:
    img = np.zeros((64, 64))
    dist, _ = line_profile(img, 1, 1, 31, 41, spacing=SPACING)
    assert dist[-1] == pytest.approx(TRUE_LENGTH)
    assert dist[-1] != pytest.approx(OLD_LENGTH)
    # the old expression, still produced when only the column scale is known
    dist, _ = line_profile(img, 1, 1, 31, 41, pixel_size=COL)
    assert dist[-1] == pytest.approx(OLD_LENGTH)


def test_line_profile_square_pixels_are_bit_identical() -> None:
    rng = np.random.default_rng(0)
    img = rng.normal(size=(64, 64))
    old_d, old_i = line_profile(img, 3.2, 5.1, 40.7, 55.3, pixel_size=0.37, width=3)
    new_d, new_i = line_profile(
        img, 3.2, 5.1, 40.7, 55.3, pixel_size=0.37, width=3, spacing=(0.37, 0.37)
    )
    assert np.array_equal(old_d, new_d)
    assert np.array_equal(old_i, new_i)


def test_line_profile_intensity_is_still_sampled_in_pixels() -> None:
    """Only the distance axis is calibrated; the samples are the same."""
    rng = np.random.default_rng(1)
    img = rng.normal(size=(64, 64))
    _, px = line_profile(img, 1, 1, 31, 41, width=3)
    _, cal = line_profile(img, 1, 1, 31, 41, width=3, spacing=SPACING)
    assert np.array_equal(px, cal)


def test_line_profile_stats_and_polyline_carry_spacing() -> None:
    img = np.zeros((64, 64))
    dist, _, _ = line_profile_stats(img, 1, 1, 31, 41, width=3, spacing=SPACING)
    assert dist[-1] == pytest.approx(TRUE_LENGTH)
    # two legs: the segment and its reverse, each 183.6 long
    dist, _ = polyline_profile(img, [1, 31, 1], [1, 41, 1], spacing=SPACING)
    assert dist[-1] == pytest.approx(2 * TRUE_LENGTH)


def test_explicit_spacing_wins_over_pixel_size() -> None:
    dist, _ = line_profile(np.zeros((64, 64)), 1, 1, 31, 41, pixel_size=99.0, spacing=SPACING)
    assert dist[-1] == pytest.approx(TRUE_LENGTH)


def test_unusable_spacing_falls_back_to_pixel_size() -> None:
    img = np.zeros((64, 64))
    dist, _ = line_profile(img, 1, 1, 31, 41, pixel_size=COL, spacing=(float("nan"), COL))
    assert dist[-1] == pytest.approx(OLD_LENGTH)
    dist, _ = line_profile(img, 1, 1, 31, 41, spacing=(float("nan"), float("nan")))
    assert dist[-1] == pytest.approx(50.0)  # pixels


# ── calc/profile_stats.py ──────────────────────────────────────────────


def test_measure_distance_calibrated_lengths_use_both_extents() -> None:
    r = measure_distance(1, 1, 31, 41, pixel_size=COL, pixel_unit="nm", spacing=SPACING)
    assert r.raw_px == pytest.approx(50.0)  # the port, untouched
    assert r.raw_calibrated == pytest.approx(TRUE_LENGTH)
    assert r.corrected_calibrated == pytest.approx(TRUE_LENGTH)
    assert r.unit == "nm"


def test_measure_distance_tilt_scales_the_row_component_before_the_sum() -> None:
    # cross-section, tilt axis Y: dy /= sin(30 deg) = 2 * dy
    r = measure_distance(1, 1, 31, 41, tilt_angle_deg=30, spacing=SPACING)
    assert r.corrected_px == pytest.approx(np.hypot(30, 80))
    assert r.corrected_calibrated == pytest.approx(np.hypot(30 * COL, 80 * ROW))


def test_measure_distance_square_pixels_unchanged() -> None:
    old = measure_distance(1, 1, 31, 41, pixel_size=0.37, tilt_angle_deg=20)
    new = measure_distance(1, 1, 31, 41, pixel_size=0.37, tilt_angle_deg=20, spacing=(0.37, 0.37))
    assert old == new


# ── calc/radial.py ─────────────────────────────────────────────────────

RING_R = 30.0


def _ring(row: float, col: float) -> np.ndarray:
    """A physically circular ring of radius RING_R on (row, col) pixels."""
    h, w = int(120 / row) + 1, int(120 / col) + 1
    cy, cx = (h + 1) / 2, (w + 1) / 2
    yy = (np.arange(1, h + 1)[:, None] - cy) * row
    xx = (np.arange(1, w + 1)[None, :] - cx) * col
    return (np.abs(np.hypot(xx, yy) - RING_R) < 1.0).astype(np.float64)


def test_radial_profile_bins_by_physical_radius() -> None:
    img = _ring(2.0, 1.0)
    radii, avg, _ = radial_profile(img, spacing=(2.0, 1.0))
    peak = radii[int(np.nanargmax(avg))]
    assert peak == pytest.approx(RING_R, abs=1.5)
    # the ring lands in a couple of adjacent rings, not smeared over many
    near = np.abs(radii - RING_R) <= 2.5
    assert np.nansum(avg[near]) / np.nansum(avg) > 0.9


def test_radial_profile_without_spacing_smears_a_physical_ring() -> None:
    """The defect: in pixel space the ring spans radii 15..30."""
    img = _ring(2.0, 1.0)
    radii, avg, _ = radial_profile(img)
    near = np.abs(radii - RING_R) <= 2.5
    assert np.nansum(avg[near]) / np.nansum(avg) < 0.5


def test_radial_profile_square_pixels_bit_identical() -> None:
    rng = np.random.default_rng(2)
    img = rng.random((50, 70))
    old = radial_profile_stats(img, center=(31.5, 20.2), n_bins=17)
    new = radial_profile_stats(img, center=(31.5, 20.2), n_bins=17, spacing=(0.25, 0.25))
    assert np.array_equal(old[0] * 0.25, new[0])
    for a, b in zip(old[1:], new[1:], strict=True):
        assert np.array_equal(a, b, equal_nan=True)


def test_azimuthal_integrate_physical_rings_and_square_identity() -> None:
    img = _ring(2.0, 1.0)
    radii, inten = azimuthal_integrate(img, spacing=(2.0, 1.0))
    assert radii[int(np.nanargmax(inten))] == pytest.approx(RING_R, abs=1.5)
    # a quarter wedge of a full ring still peaks at the ring
    radii, inten = azimuthal_integrate(img, sector_min=30, sector_max=120, spacing=(2.0, 1.0))
    assert radii[int(np.nanargmax(inten))] == pytest.approx(RING_R, abs=1.5)

    rng = np.random.default_rng(3)
    noise = rng.random((50, 70))
    old = azimuthal_integrate(noise, pixel_size=0.25, sector_min=300, sector_max=60)
    new = azimuthal_integrate(noise, sector_min=300, sector_max=60, spacing=(0.25, 0.25))
    assert np.array_equal(old[0], new[0])
    assert np.array_equal(old[1], new[1], equal_nan=True)


# ── calc/layers.py + calc/trace_roughness.py ───────────────────────────

H, W = 200, 120
CENTERS = (50.0, 100.0, 150.0)


def _stack() -> np.ndarray:
    """Three horizontal erf interfaces 50 rows apart (as tests/test_layers)."""
    yy = np.arange(H, dtype=np.float64)[:, None] + np.zeros((1, W))
    levels = (0.2, 0.8, 0.4, 0.9)
    out = np.full_like(yy, levels[0])
    for c, (lo, hi) in zip(CENTERS, zip(levels, levels[1:], strict=False), strict=True):
        out += (hi - lo) * 0.5 * (1 + erf((yy - c) / (3 * np.sqrt(2))))
    return out


def test_layer_thickness_takes_the_growth_axis_extent() -> None:
    """The defect: 50 rows on 4 nm rows and 1 nm columns reported 50 nm."""
    res = analyze_layers(_stack(), pixel_size=1.0, unit="nm", spacing=(4.0, 1.0))
    assert res.axis == "y"
    assert res.pixel_size == 4.0 and res.lateral_size == 1.0
    for lyr in res.layers:
        assert lyr.thickness == pytest.approx(200.0, abs=4.0)
    for it in res.interfaces:
        assert it.sigma_erf == pytest.approx(12.0, abs=2.5)  # 3 px erf x 4 nm


def test_vertical_layers_take_the_column_extent() -> None:
    """Same stack transposed: depth now runs along columns."""
    res = analyze_layers(_stack().T, pixel_size=4.0, unit="nm", spacing=(1.0, 4.0))
    assert res.axis == "x"
    assert res.pixel_size == 4.0 and res.lateral_size == 1.0
    for lyr in res.layers:
        assert lyr.thickness == pytest.approx(200.0, abs=4.0)


def test_layers_square_pixels_unchanged_and_edit_matches() -> None:
    old = analyze_layers(_stack(), pixel_size=0.5, unit="nm")
    new = analyze_layers(_stack(), pixel_size=0.5, unit="nm", spacing=(0.5, 0.5))
    assert [lyr.thickness for lyr in old.layers] == [lyr.thickness for lyr in new.layers]
    assert [i.sigma_erf for i in old.interfaces] == [i.sigma_erf for i in new.interfaces]
    assert new.lateral_size == 0.5

    positions = [i.position for i in new.interfaces]
    edited = recompute_layers(
        _stack(), positions, axis="y", pixel_size=1.0, unit="nm", spacing=(4.0, 1.0)
    )
    assert edited.pixel_size == 4.0
    for lyr in edited.layers:
        assert lyr.thickness == pytest.approx(200.0, abs=4.0)


def test_multi_map_comparison_carries_per_map_spacing() -> None:
    img = _stack()
    res = compare_layers_across_maps(
        [img, img], [1.0, 1.0], ["nm", "nm"], waviness=False,
        spacings=[(4.0, 1.0), (4.0, 1.0)],
    )
    for block in res.maps:
        for row in block["layers"]:
            assert row["thickness"] == pytest.approx(200.0, abs=4.0)


def test_trace_roughness_heights_and_lateral_positions_scale_separately() -> None:
    x = np.arange(512, dtype=np.float64)
    rng = np.random.default_rng(4)
    trace = 3.0 * np.sin(2 * np.pi * x / 64) + rng.normal(0, 0.05, x.size)
    unit = analyze_trace(trace, 1.0)
    both = analyze_trace(trace, 4.0, lateral_size=1.0)
    # heights are along the growth axis: x4
    assert both.sigma_w == pytest.approx(4 * unit.sigma_w)
    assert both.sigma_raw == pytest.approx(4 * unit.sigma_raw)
    assert both.noise_floor == pytest.approx(4 * unit.noise_floor)
    assert np.allclose(both.psd_power, 16 * unit.psd_power)
    # lateral positions are along the interface: unchanged
    assert np.array_equal(both.psd_wavelength, unit.psd_wavelength)
    assert both.xi == pytest.approx(unit.xi)
    assert both.hurst == pytest.approx(unit.hurst)
    # and the one-scale form is the square-pixel case of the two-scale one
    square = analyze_trace(trace, 4.0)
    same = analyze_trace(trace, 4.0, lateral_size=4.0)
    assert square.sigma_w == same.sigma_w and square.xi == same.xi
    assert np.array_equal(square.psd_wavelength, same.psd_wavelength)


# ── calc/grain_layers.py ───────────────────────────────────────────────


def test_grain_layer_width_and_height_take_their_own_extents() -> None:
    labels = np.zeros((8, 8), dtype=np.int32)
    labels[0:4, 0:3] = 1     # 4 rows tall, 3 columns wide
    result = measure_grains_by_layer(
        labels, [LayerBounds(0, 0.0, 4.0)], selected_indices=[0], axis="y",
        pixel_size=1.0, unit="nm", spacing=(4.0, 1.0),
    )
    (grain,) = result.layers[0].grains
    assert grain.lateral_width == pytest.approx(3.0)     # 3 columns x 1 nm
    assert grain.depth_height == pytest.approx(16.0)     # 4 rows x 4 nm
    assert grain.aspect_ratio == pytest.approx(3.0 / 16.0)
    assert result.layers[0].thickness == pytest.approx(16.0)
    assert result.layers[0].area == pytest.approx(32 * 4.0)  # pixel area from both extents
    assert result.pixel_size == 4.0 and result.lateral_size == 1.0


def test_grain_layer_shape_angle_is_physical() -> None:
    # a 4x4 square of pixels on 4:1 pixels is a 16-tall, 4-wide rectangle
    labels = np.zeros((8, 8), dtype=np.int32)
    labels[0:4, 0:4] = 1
    square = measure_grains_by_layer(
        labels, [LayerBounds(0, 0.0, 4.0)], selected_indices=[0], axis="y",
    )
    tall = measure_grains_by_layer(
        labels, [LayerBounds(0, 0.0, 4.0)], selected_indices=[0], axis="y",
        spacing=(4.0, 1.0),
    )
    assert tall.layers[0].grains[0].shape_angle_deg == pytest.approx(90.0)
    assert tall.layers[0].grains[0].aspect_ratio == pytest.approx(0.25)
    assert square.layers[0].grains[0].aspect_ratio == pytest.approx(1.0)


def test_grain_layer_square_pixels_unchanged() -> None:
    labels = np.zeros((8, 8), dtype=np.int32)
    labels[0:4, 0:3] = 1
    labels[0:6, 4:8] = 2
    labels[4:8, 0:4] = 3
    kw = dict(selected_indices=[0, 1], axis="y", pixel_size=0.5, unit="nm")
    bands = [LayerBounds(0, 0.0, 4.0), LayerBounds(1, 4.0, 8.0)]
    old = measure_grains_by_layer(labels, bands, **kw)
    new = measure_grains_by_layer(labels, bands, **kw, spacing=(0.5, 0.5))
    assert old.layers == new.layers


# ── at the API ─────────────────────────────────────────────────────────


def test_measure_profile_route_reports_the_physical_length(client) -> None:
    image_id = store.add_parsed(_ds(np.zeros((64, 64)), ROW, COL), "aniso.dm4")
    r = client.post(
        "/api/measure/profile",
        json={"image_id": image_id, "a": [1, 1], "b": [41, 31]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["length"] == pytest.approx(TRUE_LENGTH)
    assert r.json()["unit"] == "nm"


def test_tilted_distance_route_reports_the_physical_length(client) -> None:
    image_id = store.add_parsed(_ds(np.zeros((64, 64)), ROW, COL), "aniso.dm4")
    r = client.post(
        "/api/measure/distance-tilted",
        json={"image_id": image_id, "x1": 1, "y1": 1, "x2": 31, "y2": 41},
    )
    assert r.status_code == 200, r.text
    assert r.json()["raw_px"] == pytest.approx(50.0)
    assert r.json()["raw_calibrated"] == pytest.approx(TRUE_LENGTH)


def test_layers_route_reports_depth_extent(client) -> None:
    image_id = store.add_parsed(_ds(_stack(), 4.0, 1.0), "stack.dm4")
    r = client.post("/api/analyze/layers", json={"image_id": image_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pixel_size"] == 4.0
    assert body["lateral_size"] == 1.0
    for lyr in body["layers"]:
        assert lyr["thickness"] == pytest.approx(200.0, abs=4.0)
