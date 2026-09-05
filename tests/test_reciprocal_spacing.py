"""Reciprocal space from anisotropic pixels (roadmap item 5a, first box).

`estimate_ctf`, `lattice_measure` and `index_spots` each built reciprocal
space from ONE pixel size: the frequency step along rows was 1/(H * s)
with s the COLUMN extent. On anisotropic pixels that reads a physically
round Thon ring as an ellipse, a physically square lattice as a
rectangle, and a (200) spot along rows as something else entirely. Every
test states the number the single-scale form produced, checks the
corrected number against geometry rather than another code path, and
pins the contract that matters more: on SQUARE pixels nothing moves.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.calibration import spacing_at_column_scale
from fermiviewer.calc.ctf import _wavelength_a, estimate_ctf
from fermiviewer.calc.diffraction import _measured_d, index_spots, simulate
from fermiviewer.calc.diffraction_index import index_spots_roi
from fermiviewer.calc.lattice import lattice_measure
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

ALLOWED_HOSTS.add("testserver")

#: rows 2 Å tall, columns 1 Å wide
S_ROW, S_COL = 2.0, 1.0
SPACING = (S_ROW, S_COL)
#: rows 0.75 Å, columns 0.5 Å: every Silicon [001] 200/220 spot sits inside
#: both Nyquists, and the single-scale reading of a row spot (d = 1.81 Å)
#: matches no Silicon plane at the default 5 % tolerance
FFT_SPACING = (0.75, 0.5)
A_SI = 5.4309  # Å


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _ds(img: np.ndarray, row: float, col: float, unit: str = "A") -> DataStruct:
    return DataStruct(
        data=np.asarray(img, dtype=np.float64),
        kind=DataKind.IMAGE,
        axes=(AxisCal(scale=row, units=unit), AxisCal(scale=col, units=unit)),
        metadata={},
    )


def _outputs(result) -> dict:
    return {o["name"]: o for o in result.value["outputs"]}


# ── calc/calibration.py ────────────────────────────────────────────────


def test_spacing_at_column_scale() -> None:
    assert spacing_at_column_scale(1.0, None) is None
    assert spacing_at_column_scale(1.0, (float("nan"), 1.0)) is None
    assert spacing_at_column_scale(float("nan"), SPACING) is None
    assert spacing_at_column_scale(0.0, SPACING) is None
    # the image's own column extent: its spacing, bit for bit
    assert spacing_at_column_scale(0.37, (0.5, 0.37)) == (0.5, 0.37)
    # a user's override keeps the ratio: 2:1 rows on a 3 Å column scale
    assert spacing_at_column_scale(3.0, SPACING) == (6.0, 3.0)
    # square pixels: the override read as isotropic, exactly
    assert spacing_at_column_scale(3.0, (0.5, 0.5)) == (3.0, 3.0)


# ── calc/ctf.py ────────────────────────────────────────────────────────


def _thon_rings(
    h: int, w: int, s_row: float, s_col: float, defocus: float,
    voltage_kv: float = 200.0, cs_mm: float = 1.2, seed: int = 0,
) -> np.ndarray:
    """A real image whose power spectrum is |CTF|^2 times white noise, the
    CTF drawn in PHYSICAL frequency on (s_row, s_col) pixels."""
    lam = _wavelength_a(voltage_kv)
    cs = cs_mm * 1e7
    u = np.fft.fftfreq(w, d=s_col)[None, :]
    v = np.fft.fftfreq(h, d=s_row)[:, None]
    k2 = u**2 + v**2
    chi = np.pi * lam * defocus * k2 - 0.5 * np.pi * cs * lam**3 * k2**2
    rng = np.random.default_rng(seed)
    noise = np.fft.fft2(rng.normal(size=(h, w)))
    return np.real(np.fft.ifft2(noise * np.abs(np.sin(chi))))


def test_ctf_frequency_axes_take_both_extents() -> None:
    """128 rows of 2 Å under 256 columns of 1 Å: a square 256 Å field, so
    the true frequency step is 1/256 on both axes."""
    img = _thon_rings(128, 256, S_ROW, S_COL, 15000.0)
    aware = estimate_ctf(img, pixel_size=S_COL, spacing=SPACING)
    assert aware.defocus == pytest.approx(15000.0, rel=0.03)
    assert aware.radial_freq.max() < 0.25  # the row Nyquist, 1/(2 * 2 Å)
    # the defect: rows read on the column scale double every row
    # frequency, the rings become ellipses, and the radial fit degrades
    naive = estimate_ctf(img, pixel_size=S_COL)
    assert naive.r_squared < aware.r_squared


def test_ctf_square_pixels_bit_identical() -> None:
    img = _thon_rings(128, 128, 2.0, 2.0, 15000.0)
    old = estimate_ctf(img, pixel_size=2)
    new = estimate_ctf(img, pixel_size=2, spacing=(2.0, 2.0))
    assert old.defocus == new.defocus and old.r_squared == new.r_squared
    assert np.array_equal(old.radial_freq, new.radial_freq)
    assert np.array_equal(old.radial_power, new.radial_power)
    assert np.array_equal(old.ctf_fit, new.ctf_fit)


# ── calc/lattice.py ────────────────────────────────────────────────────


def test_lattice_reciprocal_vectors_take_both_extents() -> None:
    """A physically SQUARE 4 Å lattice on (2, 1) pixels of a 128 x 128
    image: the field is 256 Å tall by 128 Å wide, so the column spot sits
    128 * 1 / 4 = 32 columns out and the row spot 128 * 2 / 4 = 64 rows."""
    h = w = 128
    cr, cc = h // 2 + 1, w // 2 + 1
    aware = lattice_measure((cr, cc + 32), (cr + 64, cc), (h, w), spacing=SPACING)
    assert aware.a == pytest.approx(4.0) and aware.b == pytest.approx(4.0)
    assert aware.gamma_deg == pytest.approx(90.0)
    assert aware.d_spacing1 == pytest.approx(4.0)
    assert aware.d_spacing2 == pytest.approx(4.0)
    # the defect: the row spot read on the column scale is a 2 Å period
    naive = lattice_measure((cr, cc + 32), (cr + 64, cc), (h, w), pixel_size=S_COL)
    assert naive.a == pytest.approx(4.0) and naive.b == pytest.approx(2.0)


def test_lattice_square_pixels_bit_identical() -> None:
    old = lattice_measure((35, 60), (44, 47), (64, 96), pixel_size=0.05)
    new = lattice_measure((35, 60), (44, 47), (64, 96), pixel_size=0.05, spacing=(0.05, 0.05))
    for f in dataclasses.fields(old):
        assert np.array_equal(getattr(old, f.name), getattr(new, f.name)), f.name


# ── calc/diffraction.py ────────────────────────────────────────────────


def _si_fft_spots(h: int, w: int, s_row: float, s_col: float) -> np.ndarray:
    """1-based (row, col) of the Silicon [001] 200 and 220 families on the
    FFT of an h x w image with (s_row, s_col) pixels in Å."""
    cr, cc = h // 2 + 1, w // 2 + 1
    g = 2.0 / A_SI  # the (200) reciprocal component, 1/Å
    dirs = [(g, 0), (-g, 0), (0, g), (0, -g), (g, g), (g, -g), (-g, g), (-g, -g)]
    return np.array([(cr + gy * h * s_row, cc + gx * w * s_col) for gx, gy in dirs])


def _si(cands):
    return next(c for c in cands if c.phase_name == "Silicon")


def test_index_spots_fft_mode_reads_both_extents() -> None:
    h = w = 128
    pos = _si_fft_spots(h, w, *FFT_SPACING)
    kw = dict(pixel_size=FFT_SPACING[1], top_n=100)
    aware = _si(index_spots(pos, (h, w), spacing=FFT_SPACING, **kw))
    assert aware.score == 1.0
    assert sorted(np.round(aware.matched_d, 3).tolist()) == [1.92] * 4 + [2.715] * 4
    # the defect: the two (200) spots along rows, read on the column
    # scale, measure 1.81 Å and match nothing; six of eight spots survive
    naive = _si(index_spots(pos, (h, w), **kw))
    assert naive.score == 0.75


def test_index_spots_roi_passes_spacing_through() -> None:
    h = w = 128
    pos = _si_fft_spots(h, w, *FFT_SPACING)
    kw = dict(pixel_size=FFT_SPACING[1], spacing=FFT_SPACING, top_n=100)
    direct = _si(index_spots(pos, (h, w), **kw))
    via_roi = _si(index_spots_roi((h, w), pos, None, **kw).candidates)
    assert np.array_equal(direct.matched_d, via_roi.matched_d)


def test_index_spots_fft_mode_uses_both_image_dimensions() -> None:
    """Square pixels, NON-square image: the Silicon (200) row spot on a
    64-row, 128-column FFT at 0.5 Å/px sits 0.368 * 64 * 0.5 = 11.8 rows
    out. indexDiffraction.m's d = W * px / r read that as 5.43 Å, the
    lattice constant itself; the reciprocal vector reads 2.715 Å."""
    h, w, s = 64, 128, 0.5
    cr, cc = h // 2 + 1, w // 2 + 1
    g = 2.0 / A_SI
    pos = np.array([[cr + g * h * s, cc], [cr, cc + g * w * s]])
    r, d = _measured_d(pos, (cr, cc), (h, w), s, float("nan"), 200.0, None)
    assert d == pytest.approx([A_SI / 2, A_SI / 2])
    assert w * s / r[0] == pytest.approx(A_SI)  # the old reading of the row spot
    # on a square image the vector form is W * px / r to rounding
    h = w = 128
    cr = cc = h // 2 + 1
    pos = np.array([[cr + 20.0, cc + 7.0], [cr - 3.0, cc + 40.0]])
    r, d = _measured_d(pos, (cr, cc), (h, w), s, float("nan"), 200.0, None)
    np.testing.assert_allclose(d, w * s / r, rtol=1e-12)


def test_camera_mode_spot_distance_uses_both_extents() -> None:
    # a column spot and a row spot, both 20 px from the centre
    pos = np.array([[65.0, 85.0], [85.0, 65.0]])
    r, d = _measured_d(pos, (65, 65), (128, 128), 0.01, 200.0, 200.0, (0.02, 0.01))
    # on 2:1 camera pixels the row spot is physically twice as far: half the d
    assert d[1] == pytest.approx(d[0] / 2)
    r0, d0 = _measured_d(pos, (65, 65), (128, 128), 0.01, 200.0, 200.0, None)
    assert d0[0] == pytest.approx(d[0])
    assert d0[1] == d0[0]  # the port: both 20 px, one d
    assert np.array_equal(r0, r)


def test_index_spots_square_pixels_bit_identical() -> None:
    sim = simulate("Silicon", zone_axis=(0, 0, 1), scattering_model="z")
    pos = np.array([[s.pixel_row, s.pixel_col] for s in sim.spots[1:]])
    kw = dict(pixel_size=0.05, camera_length=200, acc_voltage=200)
    old = index_spots(pos, (512, 512), **kw)
    new = index_spots(pos, (512, 512), **kw, spacing=(0.05, 0.05))
    assert [c.phase_name for c in old] == [c.phase_name for c in new]
    for a, b in zip(old, new, strict=True):
        assert a.score == b.score and np.array_equal(a.matched_d, b.matched_d)
        assert np.array_equal(a.matched_idx, b.matched_idx)


# ── at the API and the op registry ─────────────────────────────────────


def test_lattice_route_and_op_take_the_images_spacing(client) -> None:
    h = w = 128
    cr, cc = h // 2 + 1, w // 2 + 1
    ds = _ds(np.zeros((h, w)), S_ROW, S_COL)
    image_id = store.add_parsed(ds, "lattice.dm4")
    spots = {"spot1": [cr, cc + 32], "spot2": [cr + 64, cc]}
    r = client.post("/api/analyze/lattice", json={"image_id": image_id, **spots})
    assert r.status_code == 200, r.text
    assert r.json()["a"] == pytest.approx(4.0) and r.json()["b"] == pytest.approx(4.0)
    # a user override is the COLUMN scale; the row extent keeps the ratio
    r = client.post(
        "/api/analyze/lattice", json={"image_id": image_id, "pixel_size": 0.5, **spots}
    )
    assert r.json()["a"] == pytest.approx(2.0) and r.json()["b"] == pytest.approx(2.0)
    outs = _outputs(ops.run(
        "lattice", ds,
        {"spot1_row": cr, "spot1_col": cc + 32, "spot2_row": cr + 64, "spot2_col": cc},
    ))
    assert outs["a"]["data"]["value"] == pytest.approx(4.0)
    assert outs["b"]["data"]["value"] == pytest.approx(4.0)


def test_ctf_route_and_op_take_the_images_spacing(client) -> None:
    img = _thon_rings(128, 256, S_ROW, S_COL, 15000.0)
    ds = _ds(img, S_ROW, S_COL)
    direct = estimate_ctf(img, pixel_size=S_COL, spacing=SPACING)
    image_id = store.add_parsed(ds, "thon.dm4")
    r = client.post("/api/analyze/ctf", json={"image_id": image_id, "pixel_size_a": S_COL})
    assert r.status_code == 200, r.text
    assert r.json()["defocus_a"] == direct.defocus
    outs = _outputs(ops.run("ctf", ds, {"pixel_size_a": S_COL}))
    assert outs["ctf"]["data"]["coefficients"]["defocus_a"] == direct.defocus


def test_index_route_and_op_take_the_patterns_spacing(client) -> None:
    h = w = 128
    pos = _si_fft_spots(h, w, *FFT_SPACING)
    ds = _ds(np.zeros((h, w)), *FFT_SPACING)
    direct = _si(
        index_spots(pos, (h, w), pixel_size=FFT_SPACING[1], spacing=FFT_SPACING, top_n=100)
    )
    image_id = store.add_parsed(ds, "fft.dm4")
    body = {
        "image_id": image_id, "spots": pos.tolist(),
        "pixel_size_mm": FFT_SPACING[1], "top_n": 100,
    }
    r = client.post("/api/diffraction/index", json=body)
    assert r.status_code == 200, r.text
    si = next(c for c in r.json()["candidates"] if c["phase"] == "Silicon")
    assert si["score"] == 1.0
    assert sorted(si["matched_d"]) == pytest.approx(sorted(direct.matched_d.tolist()))
    # the op shares index_spots_roi; on the column scale alone Silicon scores 0.75
    outs = _outputs(ops.run(
        "diffraction_index", ds,
        {"spots": pos.tolist(), "pixel_size_mm": FFT_SPACING[1], "top_n": 100},
    ))
    row = next(r for r in outs["candidates"]["data"]["rows"] if r[0] == "Silicon")
    assert row[2] == 1.0
