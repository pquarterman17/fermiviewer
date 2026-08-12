"""EELS suite tests: synthetic physics oracles + golden realdata."""

from __future__ import annotations

import tracemalloc

import numpy as np
import pytest

from fermiviewer.calc.eels import EELS_EDGES, background, extract_map, thickness_map
from fermiviewer.calc.eels_advanced import align_zlp, fourier_log, kramers_kronig, svd
from fermiviewer.io.dm import load_dm

pytestmark = pytest.mark.eels


# ── synthetic oracles ────────────────────────────────────────────────

def test_edge_table_contents() -> None:
    assert len(EELS_EDGES) == 49
    by_symbol = {e.symbol: e for e in EELS_EDGES}
    assert by_symbol["C-K"].onset_ev == 284 and by_symbol["C-K"].z == 6
    assert by_symbol["Fe-L23"].onset_ev == 708 and by_symbol["Fe-L23"].z == 26
    assert by_symbol["O-K"].onset_ev == 532


def test_background_recovers_powerlaw() -> None:
    e = np.linspace(400, 700, 600)
    spec = 5e6 * e**-2.5
    sig, bg, p = background(e, spec, fit_window=(400, 500))
    assert p["r"] == pytest.approx(2.5, rel=1e-6)
    assert p["A"] == pytest.approx(5e6, rel=1e-4)
    np.testing.assert_allclose(sig, 0.0, atol=1e-6)
    # add an edge and the residual should recover it
    edge = np.where(e > 550, 1000.0, 0.0)
    sig2, _, _ = background(e, spec + edge, fit_window=(400, 500))
    assert sig2[e > 560].mean() == pytest.approx(1000, rel=1e-3)


def test_background_exponential() -> None:
    e = np.linspace(100, 200, 300)
    spec = 2e4 * np.exp(-0.03 * e)
    _, _, p = background(e, spec, fit_window=(100, 150), method="exponential")
    assert p["b"] == pytest.approx(-0.03, rel=1e-9)


def test_thickness_map_log_ratio() -> None:
    e = np.linspace(-10, 90, 200)
    zlp = np.exp(-(e**2))                       # ZLP at 0
    plasmon = 0.6 * np.exp(-((e - 20) ** 2) / 9)
    spec = 1000 * (zlp + plasmon)
    cube = np.tile(spec, (3, 4, 1))
    t, mask = thickness_map(cube, e, zlp_window=(-5, 5))
    expected = np.log(spec.sum() / spec[(e >= -5) & (e <= 5)].sum())
    assert mask.all()
    np.testing.assert_allclose(t, expected, rtol=1e-12)


def test_extract_map_background_subtracted() -> None:
    e = np.linspace(400, 700, 512)
    bg = 1e5 * e**-2.0
    edge = np.where(e > 532, 500.0, 0.0)
    cube = np.empty((2, 3, e.size))
    weights = np.arange(6, dtype=np.float64).reshape(2, 3) + 1
    for y in range(2):
        for x in range(3):
            cube[y, x] = bg + weights[y, x] * edge
    m = extract_map(cube, e, (532, 600), background_window=(420, 520))
    n_sig_above = int(((e >= 532) & (e <= 600) & (e > 532)).sum())
    np.testing.assert_allclose(m / (500 * n_sig_above), weights, rtol=1e-2)


def test_extract_map_dtype_agnostic_float64_promotion() -> None:
    """Selecting the signal/background channels before promoting to float64
    must not change the result versus casting the whole cube up front —
    the memory-safety fix must be bit-identical, direct-sum and
    background-fit branches both."""
    e = np.linspace(400, 700, 300)
    rng = np.random.default_rng(3)
    cube_u16 = rng.integers(0, 4000, size=(5, 6, 300)).astype(np.uint16)
    cube_f64 = cube_u16.astype(np.float64)

    for bg_window, method in (
        (None, "powerlaw"),
        ((420, 520), "powerlaw"),
        ((420, 520), "exponential"),
    ):
        m_u16 = extract_map(cube_u16, e, (532, 600), bg_window, method)
        m_f64 = extract_map(cube_f64, e, (532, 600), bg_window, method)
        np.testing.assert_array_equal(m_u16, m_f64)
        assert m_u16.dtype == np.float64


def test_extract_map_does_not_materialize_the_whole_cube() -> None:
    """Peak allocation must scale with the selected channels, not the whole
    cube. Guards the class of defect this repo keeps re-finding: casting a
    multi-gigabyte spectrum image to float64 to read a narrow energy
    window. numpy reports its data allocations to tracemalloc, so a
    regression to a full-cube cast shows up directly as peak memory."""
    tracemalloc.start()
    try:
        probe = np.empty(2_000_000, dtype=np.float64)  # 16 MB
        _, probe_peak = tracemalloc.get_traced_memory()
        del probe
        if probe_peak < 8_000_000:  # pragma: no cover - platform dependent
            pytest.skip("tracemalloc does not observe numpy data allocations here")

        # A wide axis (1900 eV over 8192 channels) with narrow windows (a
        # few percent of the axis) — proportioned like the EDS memory-guard
        # test (tests/test_eds_maps.py), so a full-cube cast dwarfs a
        # correctly-scoped one instead of being comparable to it.
        e = np.linspace(100, 2000, 8192)
        rng = np.random.default_rng(4)
        cube = rng.integers(0, 4000, size=(32, 32, 8192)).astype(np.uint16)
        full_cast = cube.size * 8  # bytes a float64 copy of the cube would need

        for call in (
            lambda: extract_map(cube, e, (532, 572)),
            lambda: extract_map(cube, e, (532, 572), (462, 512), "powerlaw"),
            lambda: extract_map(cube, e, (532, 572), (462, 512), "exponential"),
        ):
            tracemalloc.reset_peak()
            baseline, _ = tracemalloc.get_traced_memory()
            call()
            _, peak = tracemalloc.get_traced_memory()
            transient = peak - baseline
            assert transient < full_cast // 4, (
                f"call allocated {transient / 1e6:.1f} MB, approaching a full "
                f"float64 cube copy ({full_cast / 1e6:.1f} MB) - the cast is back"
            )
    finally:
        tracemalloc.stop()


def test_align_zlp_recovers_known_shifts() -> None:
    e = np.linspace(-10, 10, 201)
    base = np.exp(-(e**2) / 0.5) * 1e4
    true_shifts = np.array([[0, 3], [-4, 2]])
    cube = np.empty((2, 2, e.size))
    for y in range(2):
        for x in range(2):
            cube[y, x] = np.roll(base, -int(true_shifts[y, x]))
    aligned, shifts = align_zlp(cube, e, window=(-8, 8))
    np.testing.assert_array_equal(shifts, true_shifts)
    peaks = aligned.reshape(-1, e.size).argmax(axis=1)
    assert np.ptp(peaks) == 0                    # all ZLPs on one channel


def test_fourier_log_t_over_lambda() -> None:
    e = np.linspace(-5, 95, 400)
    zlp = 1e5 * np.exp(-(e**2) / 0.5)
    plasmon = 2e4 * np.exp(-((e - 22) ** 2) / 16)
    spec = zlp + plasmon
    ssd, tol_val = fourier_log(e, spec, zlp_window=(-5, 5))
    assert tol_val == pytest.approx(np.log(spec.sum() / spec[np.abs(e) <= 5].sum()), rel=1e-6)
    assert ssd.shape == spec.shape and (ssd >= 0).all()


def test_svd_rank_two_cube() -> None:
    e = np.linspace(0, 100, 256)
    c1 = np.exp(-((e - 30) ** 2) / 20)
    c2 = np.exp(-((e - 70) ** 2) / 40)
    rng_free = np.linspace(0, 1, 24).reshape(4, 6)          # deterministic weights
    cube = rng_free[..., None] * c1 + (1 - rng_free[..., None]) * c2
    res = svd(cube, e, n_components=5)
    assert res.explained[0] > 99.0                           # centered rank-1
    assert res.eigenspectra.shape == (256, 5)
    assert res.score_maps.shape == (4, 6, 5)
    assert np.all(np.diff(res.explained) <= 1e-12)
    rec = svd(cube, e, n_components=2, denoise=True).denoised_cube
    np.testing.assert_allclose(rec, cube, atol=1e-10)


def test_kramers_kronig_synthetic_drude() -> None:
    e = np.linspace(-5, 60, 600)
    zlp = 1e6 * np.exp(-(e**2) / 0.3)
    plasmon = 3e4 * np.exp(-((e - 15) ** 2) / 8)
    kk = kramers_kronig(e, zlp + plasmon, acc_voltage=200)
    assert np.isfinite(kk.eps1).all() and np.isfinite(kk.eps2).all()
    band = (kk.energy > 10) & (kk.energy < 20)
    assert kk.eps2[band].max() > 0
    assert kk.thickness > 0


# ── golden realdata (vs frozen MATLAB outputs) ───────────────────────

@pytest.mark.golden
@pytest.mark.realdata
class TestGoldenRealData:
    @pytest.fixture(scope="class")
    @classmethod
    def zlp_ds(cls, eels_corpus):
        return load_dm(eels_corpus / "FigS6_apatite_ZLP.dm4")

    def test_fourier_log_matches(self, golden, zlp_ds) -> None:
        z = golden("eels_realdata")["zlp"]
        _, tol_val = fourier_log(zlp_ds.energy_axis, zlp_ds.sum_spectrum())
        assert tol_val == pytest.approx(z["fourierLogTOverLambda"], rel=1e-9)

    def test_thickness_map_matches(self, golden, zlp_ds) -> None:
        z = golden("eels_realdata")["zlp"]
        t, mask = thickness_map(zlp_ds.data, zlp_ds.energy_axis)
        assert int(mask.sum()) == z["thicknessValidPx"]
        assert float(np.nanmedian(t[mask])) == pytest.approx(
            z["thicknessMapMedian"], rel=1e-9
        )

    def test_align_zlp_matches(self, golden, zlp_ds) -> None:
        z = golden("eels_realdata")["zlp"]
        _, shifts = align_zlp(zlp_ds.data, zlp_ds.energy_axis)
        assert int(np.abs(shifts).max()) == z["alignMaxAbsShift"]

    def test_kramers_kronig_matches(self, golden, zlp_ds) -> None:
        z = golden("eels_realdata")["zlp"]
        kk = kramers_kronig(
            zlp_ds.energy_axis, zlp_ds.sum_spectrum(),
            acc_voltage=200, collection_angle=10,
        )
        assert kk.thickness == pytest.approx(z["kkThickness"], rel=1e-9)
        band = (kk.energy > 8) & (kk.energy < 30)
        assert float(np.median(kk.eps2[band])) == pytest.approx(
            z["kkEps2MedianPlasmon"], rel=1e-9
        )

    def test_okedge_background_and_map(self, golden, eels_corpus) -> None:
        o = golden("eels_realdata")["okedge"]
        ds = load_dm(eels_corpus / "Fig4_apatite79221_OKedge_vesicle.dm4")
        e = ds.energy_axis
        spec = ds.sum_spectrum()
        win = tuple(o["bgFitWindow"])
        sig, _, p = background(e, spec, fit_window=win)
        assert p["r"] == pytest.approx(o["bgPowerlawR"], rel=1e-9)
        assert p["A"] == pytest.approx(o["bgPowerlawA"], rel=1e-9)
        post = (e > 532) & (e < 572)
        frac = sig[post].sum() / spec[post].sum()
        assert frac == pytest.approx(o["edgeFraction"], rel=1e-9)

        m = extract_map(ds.data, e, (532, 572), background_window=win)
        assert m.sum() == pytest.approx(o["mapSum"], rel=1e-6)
        assert m.max() == pytest.approx(o["mapMax"], rel=1e-6)

        res = svd(ds.data, e, n_components=5)
        np.testing.assert_allclose(
            res.explained[:3], o["svdExplained"], rtol=1e-6
        )

    def test_f_fe_background(self, golden, eels_corpus) -> None:
        f = golden("eels_realdata")["f_fe"]
        ds = load_dm(eels_corpus / "FigS4_apatite79221_F_Fe.dm4")
        e = ds.energy_axis
        _, _, p = background(e, ds.sum_spectrum(), fit_window=(e[0] + 2, 678))
        assert p["r"] == pytest.approx(f["bgPowerlawR"], rel=1e-9)

    def test_edge_table_matches(self, golden) -> None:
        g = golden("eels_realdata")["edgeTable"]
        assert [e.symbol for e in EELS_EDGES] == g["symbol"]
        assert [e.onset_ev for e in EELS_EDGES] == g["onsetEV"]
        assert [e.z for e in EELS_EDGES] == g["Z"]
