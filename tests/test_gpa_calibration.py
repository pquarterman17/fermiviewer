"""GPA strain is dimensionless; GPA displacement is not.

`geometric_phase_analysis` converted its displacements to physical units
and then differentiated them against PIXEL indices, so every strain
component came out multiplied by `pixel_size`. Strain is
``d(u_x)/dx`` -- the scale is in the numerator and the denominator and
must cancel -- so `exx` was ten times too large at `pixel_size=10` and
right only at the default of 1, which is the only value the MATLAB
golden test exercises.

Both callers (`routes/imaging_ops.py`, `ops/catalogue_fourier.py`) pass
`pixel_size` straight from a user-supplied parameter, so values other
than 1 are the normal case rather than a corner.

The oracle here is the analytic strain of the chirped lattice, derived
below from the phase it was constructed with, not a number read out of
the implementation.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

import fermiviewer.ops as ops
from fermiviewer.calc.gpa import geometric_phase_analysis
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.routes.imaging_ops import GpaRequest, analyze_gpa
from fermiviewer.session import store

#: interior window, avoiding phase-unwrap edge artefacts (the window the
#: MATLAB golden capture uses)
WINDOW = (slice(16, 48), slice(24, 72))
G1 = (12, 0)
G2 = (0, 10)
CHIRP = 0.15


def _chirped_lattice() -> np.ndarray:
    """A lattice whose column frequency drifts quadratically, giving a
    linear `exx` ramp. Same construction as the MATLAB golden fixture."""
    x = np.arange(96, dtype=np.float64)[None, :]
    y = np.arange(64, dtype=np.float64)[:, None]
    return np.cos(2 * np.pi * (12 * x / 96 + CHIRP * (x / 96) ** 2)) + np.cos(
        2 * np.pi * 10 * y / 64
    )


def _analytic_exx_mean() -> float:
    """`exx` for the chirped lattice, from the phase it was built with.

    The lattice carries phase ``2*pi*(12x/96 + C*(x/96)**2)`` against a
    reference of ``g = 12/96`` cycles per column. The excess phase is
    ``2*pi*C*(x/96)**2``, so the displacement is
    ``u_x = -C*(x/96)**2 / g`` and ``exx = du_x/dx = -2*C*x / (96**2 * g)``.
    Averaged over the window's columns. Independent of the code under
    test, and of `pixel_size` -- which is the whole point.
    """
    g = 12 / 96
    cols = np.arange(WINDOW[1].start, WINDOW[1].stop, dtype=np.float64)
    return float(np.mean(-2 * CHIRP * cols / (96**2 * g)))


# ── the defect ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("pixel_size", [0.5, 1.0, 2.0, 10.0])
def test_strain_does_not_depend_on_pixel_size(pixel_size: float) -> None:
    """The bug, stated as the number it produced: `exx` scaled linearly
    with `pixel_size`, so the same lattice measured in nm and in
    angstroms reported strains differing by a factor of ten."""
    res = geometric_phase_analysis(
        _chirped_lattice(), G1, G2, pixel_size=pixel_size
    )
    assert res.exx[WINDOW].mean() == pytest.approx(_analytic_exx_mean(), rel=0.05)


def test_every_strain_component_is_scale_invariant() -> None:
    """Not just `exx`: shear and rotation are dimensionless too, and the
    off-diagonal terms mix the two axes, so they are the ones a
    half-applied fix would leave behind."""
    latt = _chirped_lattice()
    one = geometric_phase_analysis(latt, G1, G2, pixel_size=1.0)
    ten = geometric_phase_analysis(latt, G1, G2, pixel_size=10.0)
    for field in ("exx", "eyy", "exy", "rotation"):
        # An absolute floor as well as a relative one, and for a reason
        # rather than to make the test pass: these fields cross zero, and
        # scaling by ten then dividing by ten reorders float operations,
        # leaving ~4e-17 of noise. Against an element that is itself
        # ~1e-18 that is a relative difference of 30, while the defect
        # being guarded is a factor of TEN on values of order 1e-2. The
        # floor sits far below the one and far above the other.
        np.testing.assert_allclose(
            getattr(one, field), getattr(ten, field), rtol=1e-9, atol=1e-14,
            err_msg=f"{field} moved with pixel_size",
        )


def test_displacement_is_a_length_and_does_scale() -> None:
    """The counterpart: displacements are lengths, so they must scale
    exactly. A 'fix' that made everything invariant would be wrong."""
    latt = _chirped_lattice()
    base = geometric_phase_analysis(latt, G1, G2, pixel_size=1.0)
    for factor in (0.5, 3.0):
        got = geometric_phase_analysis(latt, G1, G2, pixel_size=factor)
        np.testing.assert_allclose(
            got.displacement_x, factor * base.displacement_x, rtol=1e-12
        )
        np.testing.assert_allclose(
            got.displacement_y, factor * base.displacement_y, rtol=1e-12
        )


# ── anisotropy: the two displacements take different scales ──────────────


def test_displacement_x_takes_the_column_extent_and_y_the_row() -> None:
    """`displacement_x` is along COLUMNS and `displacement_y` along ROWS,
    so on non-square pixels they scale by different numbers. Scaling only
    the rows must leave `displacement_x` untouched, and vice versa."""
    latt = _chirped_lattice()
    base = geometric_phase_analysis(latt, G1, G2, spacing=(1.0, 1.0))

    rows_only = geometric_phase_analysis(latt, G1, G2, spacing=(4.0, 1.0))
    np.testing.assert_allclose(
        rows_only.displacement_x, base.displacement_x, rtol=1e-12,
        err_msg="a ROW rescale must not move the COLUMN displacement",
    )
    np.testing.assert_allclose(
        rows_only.displacement_y, 4.0 * base.displacement_y, rtol=1e-12
    )

    cols_only = geometric_phase_analysis(latt, G1, G2, spacing=(1.0, 4.0))
    np.testing.assert_allclose(
        cols_only.displacement_x, 4.0 * base.displacement_x, rtol=1e-12
    )
    np.testing.assert_allclose(
        cols_only.displacement_y, base.displacement_y, rtol=1e-12,
        err_msg="a COLUMN rescale must not move the ROW displacement",
    )


def test_normal_strains_survive_anisotropy_but_shear_need_not() -> None:
    """`exx` and `eyy` each divide a displacement by a length along the
    SAME axis, so both stay invariant under any spacing. `exy` mixes the
    axes -- ``du_x/dy`` carries ``s_col/s_row`` -- so it legitimately
    changes, and asserting that it does not would be asserting a bug.
    """
    latt = _chirped_lattice()
    iso = geometric_phase_analysis(latt, G1, G2, spacing=(1.0, 1.0))
    ani = geometric_phase_analysis(latt, G1, G2, spacing=(3.0, 1.0))
    np.testing.assert_allclose(ani.exx, iso.exx, rtol=1e-12)
    np.testing.assert_allclose(ani.eyy, iso.eyy, rtol=1e-12)


def test_explicit_spacing_beats_the_pixel_size_fallback() -> None:
    """`pixel_size` cannot describe non-square pixels, so anything more
    specific wins -- the same precedence the calibration work in #202
    settled on."""
    latt = _chirped_lattice()
    got = geometric_phase_analysis(
        latt, G1, G2, pixel_size=99.0, spacing=(1.0, 4.0)
    )
    expected = geometric_phase_analysis(latt, G1, G2, spacing=(1.0, 4.0))
    np.testing.assert_allclose(got.displacement_x, expected.displacement_x, rtol=1e-12)


@pytest.mark.parametrize("bad", [(0.0, 1.0), (-1.0, 1.0), (float("nan"), 1.0)])
def test_unusable_spacing_falls_back_rather_than_poisoning_the_result(
    bad: tuple[float, float],
) -> None:
    """A zero, negative or non-finite spacing is not a calibration. It
    must not divide the gradients and produce infinities."""
    got = geometric_phase_analysis(
        _chirped_lattice(), G1, G2, pixel_size=2.0, spacing=bad
    )
    assert np.isfinite(got.exx).all()
    assert np.isfinite(got.displacement_x).all()


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_unusable_pixel_size_falls_back_rather_than_poisoning_the_result(
    bad: float,
) -> None:
    """The same guarantee for the parameter the callers actually pass.

    `spacing` reaches no caller yet; `pixel_size` reaches both, and
    neither the route model nor the op's `OpParam` excludes zero. Zero
    used to be harmless -- the displacements came out identically zero
    and so did the strains. Dividing the gradients by it instead makes
    every map NaN and fires sixteen numpy RuntimeWarnings, which this
    repo's ``filterwarnings = ["error"]`` turns into a hard failure.

    The assertion is the ANALYTIC strain rather than mere finiteness: a
    fallback that returned zeros everywhere would be just as wrong and
    would sail through an `isfinite` check. Strain is dimensionless, so
    the correct answer at a nonsense calibration is the same answer as at
    a good one -- not NaN.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = geometric_phase_analysis(_chirped_lattice(), G1, G2, pixel_size=bad)
    assert got.exx[WINDOW].mean() == pytest.approx(_analytic_exx_mean(), rel=0.05)


# ── the guarantee that protects existing results ─────────────────────────


def test_the_two_entry_paths_agree_bit_for_bit_at_unit_scale() -> None:
    """`pixel_size=1` and `spacing=(1, 1)` are the same physical statement
    and must produce identical arrays, not merely close ones.

    This does NOT on its own establish that the default is unchanged --
    both sides of the comparison are the new code, so they would agree
    just as happily on a wrong number. What pins the old values is
    `tests/test_imaging.py::test_gpa`, which checks all eight fields at
    the default against the MATLAB capture: an oracle outside this repo
    entirely. This test guards the narrower thing its name says, that the
    default path and the explicit-spacing path cannot drift apart.
    """
    latt = _chirped_lattice()
    default = geometric_phase_analysis(latt, G1, G2)
    explicit = geometric_phase_analysis(latt, G1, G2, spacing=(1.0, 1.0))
    for field in ("exx", "eyy", "exy", "rotation", "displacement_x", "displacement_y"):
        np.testing.assert_array_equal(
            getattr(default, field), getattr(explicit, field)
        )


# ── the two live callers must actually pass `spacing` (ADR 0008) ─────────
#
# `geometric_phase_analysis` has always honoured `spacing` correctly (see
# above); the defect was that neither `routes/imaging_ops.py::analyze_gpa`
# nor `ops/catalogue_fourier.py::_gpa` ever passed it, so every GPA request
# through the API silently read the image as isotropic. `exx`/`eyy` cancel
# regardless (see `test_normal_strains_survive_anisotropy_but_shear_need
# _not` above), so the defect was invisible there; `exy` and `rotation`
# mix the two axes and came out wrong by the extent ratio on any
# anisotropic image -- a factor of 4 on 1:4 pixels.

ROW_SPACING, COL_SPACING = 0.5, 2.0  # 1:4 pixels, ADR 0008's own example


def _aniso_ds(img: np.ndarray) -> DataStruct:
    return DataStruct(
        data=img,
        kind=DataKind.IMAGE,
        axes=(
            AxisCal(ROW_SPACING, 0.0, "nm"),
            AxisCal(COL_SPACING, 0.0, "nm"),
        ),
        metadata={"source": "synthetic"},
    )


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear()
    yield
    store.clear()


def test_gpa_route_passes_pixel_spacing_to_the_calc() -> None:
    """The defect, reproduced through `analyze_gpa` itself: at
    `pixel_size=2.0` (the COLUMN scale, ADR 0008) on an image whose rows
    are 0.5 nm and whose columns are 2.0 nm, the route must report the
    SAME `exy`/`rotation` as calling the calc directly with
    `spacing=(0.5, 2.0)` -- not the isotropic answer at `spacing=(2, 2)`.
    """
    latt = _chirped_lattice()
    image_id = store.add_parsed(_aniso_ds(latt), "aniso.dm4")
    req = GpaRequest(image_id=image_id, g1=G1, g2=G2, pixel_size=COL_SPACING)
    body = analyze_gpa(req)

    maps = {m["name"].split("(")[0]: m["id"] for m in body["maps"]}
    got_exy = store.get(maps["exy"]).data
    got_rotation = store.get(maps["rotation"]).data

    correct = geometric_phase_analysis(
        latt, G1, G2, pixel_size=COL_SPACING, spacing=(ROW_SPACING, COL_SPACING)
    )
    isotropic_wrong = geometric_phase_analysis(latt, G1, G2, pixel_size=COL_SPACING)

    np.testing.assert_array_equal(got_exy, correct.exy)
    np.testing.assert_array_equal(got_rotation, correct.rotation)
    # and it must actually differ from the isotropic (unfixed) answer --
    # otherwise this test would pass whether or not `spacing` was wired up
    assert not np.allclose(correct.exy, isotropic_wrong.exy)
    assert not np.allclose(correct.rotation, isotropic_wrong.rotation)


def test_gpa_route_square_pixels_are_bit_identical() -> None:
    """Square pixels must be untouched by the fix: `spacing_at_column_scale`
    returns the spacing unchanged when `pixel_size` already matches its
    column extent, and `None` (falling back to isotropic) otherwise --
    either way the numbers on a square-pixel image must not move."""
    latt = _chirped_lattice()
    square_ds = DataStruct(
        data=latt,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )
    image_id = store.add_parsed(square_ds, "square.dm4")
    req = GpaRequest(image_id=image_id, g1=G1, g2=G2, pixel_size=0.5)
    body = analyze_gpa(req)
    got = {m["name"].split("(")[0]: store.get(m["id"]).data for m in body["maps"]}

    expected = geometric_phase_analysis(latt, G1, G2, pixel_size=0.5)
    for key in ("exx", "eyy", "exy", "rotation"):
        np.testing.assert_array_equal(got[key], getattr(expected, key))


def test_gpa_op_passes_pixel_spacing_to_the_calc() -> None:
    """Same defect, the op entry point (`ops/catalogue_fourier.py::_gpa`,
    registered as `gpa`)."""
    latt = _chirped_lattice()
    ds = _aniso_ds(latt)
    params = {
        "g1x": G1[0], "g1y": G1[1], "g2x": G2[0], "g2y": G2[1],
        "mask_radius": 0.0, "mask_order": 2.0, "pixel_size": COL_SPACING,
    }
    result = ops.run("gpa", ds, params)
    outputs = {
        o["name"]: o["data"]["values"]
        for o in result.value["outputs"]
        if o["kind"] == "map"
    }

    correct = geometric_phase_analysis(
        latt, G1, G2, pixel_size=COL_SPACING, spacing=(ROW_SPACING, COL_SPACING)
    )
    isotropic_wrong = geometric_phase_analysis(latt, G1, G2, pixel_size=COL_SPACING)

    np.testing.assert_array_equal(np.asarray(outputs["exy"]), correct.exy)
    np.testing.assert_array_equal(np.asarray(outputs["rotation"]), correct.rotation)
    assert not np.allclose(correct.exy, isotropic_wrong.exy)
    assert not np.allclose(correct.rotation, isotropic_wrong.rotation)


def test_gpa_op_square_pixels_are_bit_identical() -> None:
    latt = _chirped_lattice()
    ds = DataStruct(
        data=latt,
        kind=DataKind.IMAGE,
        axes=(AxisCal(0.5, 0.0, "nm"), AxisCal(0.5, 0.0, "nm")),
        metadata={"source": "synthetic"},
    )
    params = {
        "g1x": G1[0], "g1y": G1[1], "g2x": G2[0], "g2y": G2[1],
        "mask_radius": 0.0, "mask_order": 2.0, "pixel_size": 0.5,
    }
    result = ops.run("gpa", ds, params)
    outputs = {
        o["name"]: o["data"]["values"]
        for o in result.value["outputs"]
        if o["kind"] == "map"
    }
    expected = geometric_phase_analysis(latt, G1, G2, pixel_size=0.5)
    for key in ("exx", "eyy", "exy", "rotation"):
        np.testing.assert_array_equal(np.asarray(outputs[key]), getattr(expected, key))
