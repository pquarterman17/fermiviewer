"""The FFT → index path on anisotropic pixels, end to end.

A generated FFT used to be registered uncalibrated, so spot indexing on
it had no way to know the source's pixels were not square: the reciprocal
grid was read as square, and a (200) spot along rows measured a different
d than the same spot along columns. `calc/fourier.fft_axes` now gives the
FFT its true reciprocal calibration (``1 / (N * s)`` per axis, origin at
DC) and FFT-mode indexing inverts it to recover the source's pixel aspect
(`calc/diffraction_index.pattern_spacing`).
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.calibration import (
    is_reciprocal_unit,
    real_spacing_from_reciprocal,
    reciprocal_spacing,
)
from fermiviewer.calc.diffraction_index import pattern_spacing
from fermiviewer.calc.fourier import compute_fft, fft_axes, fft_datastruct
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.server import ALLOWED_HOSTS, create_app
from fermiviewer.session import store

ALLOWED_HOSTS.add("testserver")

A_SI = 5.4309  # Å
G = 2.0 / A_SI  # the (200) reciprocal component, 1/Å
N = 128
#: cycles of the (200) component across the field: 24 along columns and 36
#: along rows, so the pixels are 3:2 and every spot lands on an exact bin
CYCLES_COL, CYCLES_ROW = 24, 36
S_COL_A = CYCLES_COL / (G * N)  # Å per column
S_ROW_A = CYCLES_ROW / (G * N)  # Å per row
NM = 0.1  # Å → nm
D_200, D_220 = A_SI / 2, A_SI / np.sqrt(8)


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _silicon_001() -> DataStruct:
    """A [001] Silicon-like lattice image: cosines at the four independent
    200/220 g-vectors, sampled on 3:2 pixels and calibrated in nm."""
    col = np.arange(N, dtype=np.float64)[None, :]
    row = np.arange(N, dtype=np.float64)[:, None]
    u = 2 * np.pi * CYCLES_COL * col / N
    v = 2 * np.pi * CYCLES_ROW * row / N
    img = np.cos(u) + np.cos(v) + np.cos(u + v) + np.cos(u - v)
    return DataStruct(
        data=img,
        kind=DataKind.IMAGE,
        axes=(
            AxisCal(scale=S_ROW_A * NM, units="nm"),
            AxisCal(scale=S_COL_A * NM, units="nm"),
        ),
        metadata={},
    )


def _uncalibrated(
    shape: tuple[int, int] = (8, 8), axes: tuple[AxisCal, AxisCal] | None = None
) -> DataStruct:
    return DataStruct(
        data=np.zeros(shape),
        kind=DataKind.IMAGE,
        axes=axes or (AxisCal(), AxisCal()),
        metadata={},
    )


# ── calc ───────────────────────────────────────────────────────────────


def test_reciprocal_spacing_is_its_own_inverse() -> None:
    sp = (0.75, 0.5)
    r = reciprocal_spacing((128, 256), sp)
    assert r == (pytest.approx(1 / 96), pytest.approx(1 / 128))
    assert real_spacing_from_reciprocal((128, 256), r) == (
        pytest.approx(0.75),
        pytest.approx(0.5),
    )
    assert is_reciprocal_unit("1/nm") and is_reciprocal_unit(" 1/Å")
    assert not is_reciprocal_unit("nm") and not is_reciprocal_unit("")


def test_fft_axes_are_reciprocal_per_axis_with_the_origin_at_dc() -> None:
    src = _silicon_001()
    rows, cols = fft_axes(src, (N, N))
    assert rows.units == cols.units == "1/nm"
    assert rows.scale == pytest.approx(1 / (N * S_ROW_A * NM))
    assert cols.scale == pytest.approx(1 / (N * S_COL_A * NM))
    assert rows.origin == cols.origin == N // 2
    # a local FFT over a 40 x 96 rect: the same pixels, that rect's N
    rows, cols = fft_axes(src, (40, 96))
    assert rows.scale == pytest.approx(1 / (40 * S_ROW_A * NM))
    assert cols.scale == pytest.approx(1 / (96 * S_COL_A * NM))
    # and DC sits where compute_fft's fftshift puts it
    mag, _ = compute_fft(src.data + 4.0)
    assert np.unravel_index(np.argmax(mag), mag.shape) == (N // 2, N // 2)


def test_fft_axes_refuse_what_they_cannot_state() -> None:
    assert not any(a.calibrated for a in fft_axes(_uncalibrated(), (8, 8)))
    # an FFT of an FFT: the input is already reciprocal
    fft = fft_datastruct(np.zeros((N, N)), _silicon_001(), {})
    assert not any(a.calibrated for a in fft_axes(fft, (N, N)))
    # two units on the two axes are not a calibration either
    mixed = _uncalibrated(axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "um")))
    assert not any(a.calibrated for a in fft_axes(mixed, (8, 8)))


def test_fft_datastruct_records_the_source_pixels() -> None:
    fft = fft_datastruct(np.zeros((N, N)), _silicon_001(), {"parser": "derived"})
    assert fft.metadata["parser"] == "derived"
    assert fft.metadata["source_pixel_spacing"] == [
        pytest.approx(S_ROW_A * NM),
        pytest.approx(S_COL_A * NM),
    ]
    assert fft.metadata["source_pixel_unit"] == "nm"
    assert fft.pixel_unit == "1/nm"
    assert fft.pixel_spacing == (
        pytest.approx(1 / (N * S_ROW_A * NM)),
        pytest.approx(1 / (N * S_COL_A * NM)),
    )


def test_pattern_spacing_reads_the_source_aspect_off_a_reciprocal_pattern() -> None:
    nan = float("nan")
    fft = fft_datastruct(np.zeros((N, N)), _silicon_001(), {})
    # FFT mode: the typed column scale (Å) keeps its meaning and the row
    # extent follows the SOURCE ratio, 3:2 -- not the reciprocal grid's 2:3
    assert pattern_spacing(fft.data.shape, fft.pixel_spacing, fft.pixel_unit, S_COL_A, nan) == (
        pytest.approx(S_ROW_A),
        pytest.approx(S_COL_A),
    )
    # camera mode: the pattern's own pixel ratio, as for any detector image
    cam = _uncalibrated(axes=(AxisCal(0.02, 0.0, "mm"), AxisCal(0.01, 0.0, "mm")))
    assert pattern_spacing(cam.data.shape, cam.pixel_spacing, cam.pixel_unit, 0.01, 200.0) == (
        0.02,
        0.01,
    )
    # no calibration: one scale, as before
    bare = _uncalibrated()
    assert pattern_spacing(bare.data.shape, bare.pixel_spacing, bare.pixel_unit, 0.5, nan) is None


# ── end to end: source → FFT → detect → index ─────────────────────────


def _silicon(candidates: list[dict]) -> dict:
    return next(c for c in candidates if c["phase"] == "Silicon")


def _detect(client: TestClient, image_id: str) -> list[list[float]]:
    r = client.post("/api/diffraction/detect", json={"image_id": image_id, "min_radius": 10})
    assert r.status_code == 200, r.text
    return r.json()["spots"]


def _index(client: TestClient, image_id: str, spots: list[list[float]]) -> dict:
    r = client.post(
        "/api/diffraction/index",
        json={"image_id": image_id, "spots": spots, "pixel_size_mm": S_COL_A, "top_n": 100},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_fft_then_index_recovers_silicon_on_anisotropic_pixels(client) -> None:
    src_id = store.add_parsed(_silicon_001(), "si001.dm4")
    fft = client.post(f"/api/image/{src_id}/fft").json()
    # the registered FFT is calibrated in reciprocal nm, per axis
    assert fft["pixel_unit"] == "1/nm"
    assert fft["pixel_size"] == pytest.approx(1 / (N * S_COL_A * NM))
    assert store.get(fft["id"]).pixel_spacing == (
        pytest.approx(1 / (N * S_ROW_A * NM)),
        pytest.approx(1 / (N * S_COL_A * NM)),
    )
    spots = _detect(client, fft["id"])
    assert len(spots) == 8
    si = _silicon(_index(client, fft["id"], spots)["candidates"])
    assert si["score"] == 1.0
    assert sorted(np.round(si["matched_d"], 3).tolist()) == (
        [round(D_220, 3)] * 4 + [round(D_200, 3)] * 4
    )
    # the op indexes the same registered FFT the same way
    result = ops.run(
        "diffraction_index",
        store.get(fft["id"]),
        {"spots": spots, "pixel_size_mm": S_COL_A, "top_n": 100},
    )
    outs = {o["name"]: o for o in result.value["outputs"]}
    row = next(r for r in outs["candidates"]["data"]["rows"] if r[0] == "Silicon")
    assert row[2] == 1.0


def test_a_local_fft_takes_its_rect_size_into_the_axes(client) -> None:
    src_id = store.add_parsed(_silicon_001(), "si001.dm4")
    fft = client.post(f"/api/image/{src_id}/fft", json={"rect": [1, 1, 64, 96]}).json()
    assert store.get(fft["id"]).pixel_spacing == (
        pytest.approx(1 / (64 * S_ROW_A * NM)),
        pytest.approx(1 / (96 * S_COL_A * NM)),
    )


def test_an_uncalibrated_fft_still_reads_the_grid_as_square(client) -> None:
    """The defect this closes, kept as the reference: the same magnitude
    registered without axes reads the two row spots at 1.81 Å, which
    match no Silicon plane, and Silicon scores 6 of 8."""
    mag, _ = compute_fft(_silicon_001().data)
    bare = DataStruct(
        data=np.ascontiguousarray(mag), kind=DataKind.IMAGE,
        axes=(AxisCal(), AxisCal()), metadata={},
    )
    fft_id = store.add_parsed(bare, "bare-fft")
    spots = _detect(client, fft_id)
    assert len(spots) == 8
    assert _silicon(_index(client, fft_id, spots)["candidates"])["score"] == 0.75
