"""Cross-section layer analysis tests — synthetic ground truth (no golden).

Build stacks with interfaces at known depths and known erf widths, then
recover thickness, σ_erf, growth axis and tilt within tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.special import erf

from fermiviewer.calc.layers import (
    analyze_layers,
    cross_section_profile,
    detect_growth_orientation,
    detect_interfaces,
    detect_interfaces_scale_space,
    recompute_layers,
    trace_interface,
)

pytestmark = pytest.mark.imaging

CENTERS = (50.0, 100.0, 150.0)
SIGMAS = (3.0, 3.0, 3.0)
LEVELS = (0.2, 0.8, 0.4, 0.9)          # 4 plateaus → 3 interfaces
H, W = 200, 120


def _layered(tilt_deg: float = 0.0) -> np.ndarray:
    """Horizontal erf-step layers, optionally tilted by tilt_deg."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float64)
    a = np.radians(tilt_deg)
    d = (yy - H / 2) * np.cos(a) + (xx - W / 2) * np.sin(a) + H / 2
    out = np.full_like(d, LEVELS[0])
    steps = zip(LEVELS, LEVELS[1:], strict=False)   # 4 levels → 3 steps (intentional)
    for c, s, (lo, hi) in zip(CENTERS, SIGMAS, steps, strict=True):
        out += (hi - lo) * 0.5 * (1 + erf((d - c) / (s * np.sqrt(2))))
    return out


# ── orientation ──────────────────────────────────────────────────────

def test_orientation_horizontal_layers() -> None:
    o = detect_growth_orientation(_layered())
    assert o.axis == "y"
    assert o.layers_horizontal
    assert abs(o.tilt_deg) < 1.0
    assert o.coherence > 0.8


def test_orientation_vertical_layers() -> None:
    o = detect_growth_orientation(_layered().T)
    assert o.axis == "x"
    assert not o.layers_horizontal


def test_orientation_tilt_recovered() -> None:
    o = detect_growth_orientation(_layered(tilt_deg=5.0))
    assert o.axis == "y"
    assert 3.0 < abs(o.tilt_deg) < 7.0     # ~5° tilt detected


# ── profile + interface detection ────────────────────────────────────

def test_cross_section_profile_recovers_step_profile() -> None:
    pos, prof = cross_section_profile(_layered(), axis="y", reduce="mean")
    assert pos.size == H
    # plateaus match the construction levels (lateral mean of a uniform stack)
    assert prof[10] == pytest.approx(LEVELS[0], abs=1e-6)
    assert prof[190] == pytest.approx(LEVELS[3], abs=1e-6)


def test_detect_interfaces_finds_three() -> None:
    _pos, prof = cross_section_profile(_layered(), axis="y")
    peaks = detect_interfaces(prof)
    assert peaks.size == 3
    np.testing.assert_allclose(np.sort(peaks), CENTERS, atol=2)


def test_detect_interfaces_n_layers_hint() -> None:
    _pos, prof = cross_section_profile(_layered(), axis="y")
    peaks = detect_interfaces(prof, sensitivity=0.05, n_layers=3)  # keep 2 strongest
    assert peaks.size == 2


# ── full pipeline ────────────────────────────────────────────────────

def test_analyze_layers_recovers_thickness_and_sigma() -> None:
    res = analyze_layers(_layered(), pixel_size=1.0)
    assert res.axis == "y" and res.layers_horizontal
    assert len(res.interfaces) == 3
    centers = sorted(i.position for i in res.interfaces)
    np.testing.assert_allclose(centers, CENTERS, atol=0.5)        # sub-pixel
    for it in res.interfaces:
        assert it.sigma_erf == pytest.approx(3.0, abs=0.6)        # erf width
        assert it.r_squared > 0.98
    # two bounded layers (between consecutive interfaces), each 50 px thick
    assert len(res.layers) == 2
    for lyr in res.layers:
        assert lyr.thickness == pytest.approx(50.0, abs=1.0)


def test_analyze_layers_pixel_size_scales_thickness() -> None:
    res = analyze_layers(_layered(), pixel_size=0.5, unit="nm")
    assert res.unit == "nm"
    for lyr in res.layers:
        assert lyr.thickness == pytest.approx(25.0, abs=0.5)      # 50 px × 0.5 nm
    for it in res.interfaces:
        assert it.sigma_erf == pytest.approx(1.5, abs=0.3)        # 3 px × 0.5 nm


def test_analyze_layers_axis_override() -> None:
    # force the wrong axis on a horizontal stack → no lateral structure → no layers
    res = analyze_layers(_layered(), axis="x")
    assert res.axis == "x"
    assert len(res.interfaces) == 0


def test_analyze_layers_roi_restricts_depth() -> None:
    # ROI covering only the first two interfaces (rows 1..120)
    res = analyze_layers(_layered(), roi=(1, 1, 120, W))
    centers = sorted(i.position for i in res.interfaces)
    assert len(centers) == 2
    np.testing.assert_allclose(centers, [50.0, 100.0], atol=1.0)


def test_analyze_layers_requires_2d() -> None:
    with pytest.raises(ValueError, match="2-D"):
        analyze_layers(np.zeros((4, 4, 4)))


# ── Tier 2: σ_w waviness ─────────────────────────────────────────────

def _wavy_interface(depth: np.ndarray) -> np.ndarray:
    """Single erf interface whose depth varies per column (shape (H, W))."""
    yy = np.arange(160, dtype=np.float64)[:, None]
    return 0.2 + 0.6 * 0.5 * (1 + erf((yy - depth[None, :]) / (3 * np.sqrt(2))))


def test_trace_interface_recovers_sinusoidal_waviness() -> None:
    x = np.arange(200, dtype=np.float64)
    amp = 4.0
    depth = 80.0 + amp * np.sin(2 * np.pi * x / 40.0)
    img = _wavy_interface(depth)
    tr = trace_interface(img, axis="y", interface_pos=80.0, window=12)
    assert tr.size == 200
    np.testing.assert_allclose(tr, depth, atol=0.3)          # follows the wave
    # std of an amplitude-A sine ≈ A/√2
    assert float(np.std(tr)) == pytest.approx(amp / np.sqrt(2), rel=0.1)


def test_trace_interface_flat_is_low_waviness() -> None:
    img = _wavy_interface(np.full(200, 80.0))
    tr = trace_interface(img, axis="y", interface_pos=80.0)
    assert float(np.std(tr)) < 0.1


def test_analyze_layers_waviness_random_sigma_w() -> None:
    rng = np.random.default_rng(0)
    x = np.arange(200)
    sigma_true = 2.5
    # two parallel interfaces, both jittered by the same per-column noise so
    # σ_w is well-defined and the layer thickness stays ~constant
    jitter = rng.normal(0.0, sigma_true, size=200)
    yy = np.arange(160, dtype=np.float64)[:, None]
    d1 = 50.0 + jitter
    d2 = 110.0 + jitter
    img = (
        0.2
        + 0.6 * 0.5 * (1 + erf((yy - d1[None, :]) / (3 * np.sqrt(2))))
        - 0.4 * 0.5 * (1 + erf((yy - d2[None, :]) / (3 * np.sqrt(2))))
    )
    res = analyze_layers(img, pixel_size=1.0, waviness=True)
    assert len(res.interfaces) == 2
    for it in res.interfaces:
        assert it.sigma_w == pytest.approx(sigma_true, rel=0.2)
        assert it.trace is not None and it.trace.size == 200
    # both interfaces share the jitter → thickness barely varies across the FOV
    assert len(res.layers) == 1
    assert res.layers[0].thickness_std < 0.5
    _ = x


def test_analyze_layers_without_waviness_has_nan_sigma_w() -> None:
    res = analyze_layers(_layered(), pixel_size=1.0)   # waviness=False default
    assert all(np.isnan(i.sigma_w) for i in res.interfaces)
    assert all(i.trace is None for i in res.interfaces)


# ── Tier 3: BF/DF scale-space robustness ─────────────────────────────

def _fringed_profile() -> np.ndarray:
    """Two real erf interfaces (50, 100) buried under thickness fringes."""
    y = np.arange(160, dtype=np.float64)
    prof = (
        0.2
        + 0.6 * 0.5 * (1 + erf((y - 50) / (3 * np.sqrt(2))))
        - 0.4 * 0.5 * (1 + erf((y - 100) / (3 * np.sqrt(2))))
    )
    return prof + 0.05 * np.sin(2 * np.pi * y / 8.0)   # diffraction-contrast fringes


def test_scale_space_rejects_fringes() -> None:
    prof = _fringed_profile()
    plain = detect_interfaces(prof, sensitivity=0.3)
    ss = detect_interfaces_scale_space(prof, scales=(2.0, 4.0, 8.0))
    assert ss.size == 2
    np.testing.assert_allclose(np.sort(ss), [50, 100], atol=3)
    assert plain.size > ss.size                      # raw intensity over-detects


def test_scale_space_keeps_clean_interfaces() -> None:
    _pos, prof = cross_section_profile(_layered(), axis="y")
    ss = detect_interfaces_scale_space(prof, scales=(1.5, 3.0, 6.0))
    assert ss.size == 3
    np.testing.assert_allclose(np.sort(ss), CENTERS, atol=3)


def test_scale_space_n_layers_hint() -> None:
    prof = _fringed_profile()
    ss = detect_interfaces_scale_space(prof, n_layers=2)   # keep 1 strongest
    assert ss.size == 1


def test_recompute_layers_from_edited_positions() -> None:
    # supply the known interface depths directly → erf-refined, layers rebuilt
    res = recompute_layers(_layered(), [50.0, 100.0, 150.0], axis="y", pixel_size=1.0)
    assert len(res.interfaces) == 3
    centers = sorted(i.position for i in res.interfaces)
    np.testing.assert_allclose(centers, CENTERS, atol=0.5)
    assert len(res.layers) == 2
    for lyr in res.layers:
        assert lyr.thickness == pytest.approx(50.0, abs=1.0)


def test_recompute_layers_add_and_remove() -> None:
    # remove the middle interface → one big layer; positions drop out of range
    res = recompute_layers(_layered(), [50.0, 150.0, 999.0, -5.0], axis="y")
    assert len(res.interfaces) == 2          # 999/-5 dropped (out of range)
    assert len(res.layers) == 1
    assert res.layers[0].thickness == pytest.approx(100.0, abs=1.0)


def test_recompute_layers_waviness() -> None:
    res = recompute_layers(_layered(), [50.0, 100.0], axis="y", waviness=True)
    for it in res.interfaces:
        assert it.trace is not None
        assert np.isfinite(it.sigma_w)


def test_recompute_layers_bad_axis() -> None:
    with pytest.raises(ValueError, match="axis must be"):
        recompute_layers(_layered(), [50.0], axis="auto")


def test_analyze_layers_bf_modality_rejects_fringes() -> None:
    img = np.tile(_fringed_profile()[:, None], (1, 80))
    bf = analyze_layers(img, modality="bf")
    haadf = analyze_layers(img, modality="haadf")
    assert len(bf.interfaces) == 2                    # real interfaces only
    assert len(haadf.interfaces) > 2                  # fooled by the fringes
