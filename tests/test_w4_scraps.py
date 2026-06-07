"""W4 scraps vs MATLAB goldens: VDF, composition profile, CTF, FBP."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from fermiviewer.calc.ctf import estimate_ctf
from fermiviewer.calc.eds_maps import composition_profile, virtual_dark_field
from fermiviewer.calc.tomo import back_project

pytestmark = [pytest.mark.golden]

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "imaging.json").read_text()
)
REL = 1e-9


@pytest.fixture(scope="module")
def synth() -> dict[str, np.ndarray]:
    r = np.arange(1, 65, dtype=np.float64)[:, None]
    c = np.arange(1, 97, dtype=np.float64)[None, :]
    base = np.sin(r / 7) * np.cos(c / 11) + 0.001 * (r * c) / (64 * 96)
    noisy = base + 0.05 * np.sin(13 * r + 7 * c)
    x = np.arange(96, dtype=np.float64)[None, :]
    y = np.arange(64, dtype=np.float64)[:, None]
    latt = np.cos(2 * np.pi * (12 * x / 96 + 0.15 * (x / 96) ** 2)) + np.cos(
        2 * np.pi * 10 * y / 64
    )
    return {"base": base, "noisy": noisy, "latt": latt}


@pytest.mark.eds
def test_virtual_dark_field(synth) -> None:
    g = GOLDEN["vdf"]
    v1 = virtual_dark_field(synth["latt"], (33, 61), mask_radius=4)
    assert v1.sum() == pytest.approx(g["circleSum"], rel=REL)
    assert v1[19, 29] == pytest.approx(g["circlePx"], rel=REL)
    v2 = virtual_dark_field(
        synth["latt"], (33, 49), mask_radius=10,
        mask_shape="annulus", inner_radius=3,
    )
    assert v2.sum() == pytest.approx(g["annulusSum"], rel=REL)
    with pytest.raises(ValueError):
        virtual_dark_field(synth["latt"], (33, 49), mask_shape="square")


@pytest.mark.eds
def test_composition_profile(synth) -> None:
    g = GOLDEN["compProfile"]
    dist, pct = composition_profile(
        [np.abs(synth["base"]), np.abs(synth["noisy"])],
        ["Fe", "O"],
        10, 8, 80, 50,
        n_points=64, pixel_size=0.4, width=5,
    )
    assert dist[-1] == pytest.approx(g["distEnd"], rel=REL)
    assert pct[:, 0].sum() == pytest.approx(g["sumA"], rel=REL)
    assert pct[:, 1].sum() == pytest.approx(g["sumB"], rel=REL)
    assert pct[31, 0] == pytest.approx(g["mid"], rel=REL)
    # degenerate line → zeros
    d0, p0 = composition_profile(
        [np.abs(synth["base"])], ["Fe"], 5, 5, 5, 5, n_points=8
    )
    assert d0.sum() == 0 and p0.sum() == 0


@pytest.mark.diffraction
def test_estimate_ctf() -> None:
    # image whose |FFT|² IS a CTF² → exact Thon rings (Df0 = 15000 Å)
    g = GOLDEN["ctf"]
    lam = 12.2643 / np.sqrt(200e3 + 0.97845e-6 * 200e3**2)
    cs = 1.2e7
    ax = np.arange(-64, 64) / (128 * 2)
    ku, kv = np.meshgrid(ax, ax)
    k2d = np.hypot(ku, kv)
    ctf_true = np.sin(
        np.pi * lam * 15000 * k2d**2 - 0.5 * np.pi * cs * lam**3 * k2d**4
    )
    img = np.real(np.fft.ifft2(np.fft.ifftshift(ctf_true)))

    res = estimate_ctf(img, pixel_size=2)
    assert res.lambda_a == pytest.approx(g["lambda"], rel=REL)
    # optimizer paths differ (fminsearch vs NM, TolX = 1 Å granularity)
    assert res.defocus == pytest.approx(g["defocus"], rel=1e-3)
    assert res.r_squared == pytest.approx(g["rSquared"], rel=1e-3)
    assert res.radial_freq.size == g["radialN"]
    assert res.radial_power.sum() == pytest.approx(
        g["radialPowSum"], rel=REL
    )
    assert res.ctf_fit.sum() == pytest.approx(g["ctfFitSum"], rel=1e-3)
    # sanity: the true defocus is recovered to within the search step
    assert abs(res.defocus - 15000) < 200


@pytest.mark.diffraction
def test_back_project(synth) -> None:
    g = GOLDEN["backproject"]
    sino = synth["base"][:31, :]
    bp = back_project(sino, filter_name="ramp", output_size=96)
    assert list(bp.reconstruction.shape) == g["ramp"]["size"]
    assert bp.reconstruction.sum() == pytest.approx(g["ramp"]["sum"], rel=REL)
    assert bp.reconstruction[39, 49] == pytest.approx(
        g["ramp"]["px"], rel=REL
    )
    bp2 = back_project(sino, filter_name="hamming", output_size=64)
    assert bp2.reconstruction.sum() == pytest.approx(
        g["hamming"]["sum"], rel=REL
    )
    bp3 = back_project(sino, filter_name="none", output_size=96)
    assert bp3.reconstruction.sum() == pytest.approx(
        g["none"]["sum"], rel=REL
    )
    # default angles span the tomography tilt range
    assert bp.angles[0] == -70 and bp.angles[-1] == 70
    with pytest.raises(ValueError):
        back_project(sino, angles=np.array([1.0, 2.0]))
    with pytest.raises(ValueError):
        back_project(sino, filter_name="butter")
