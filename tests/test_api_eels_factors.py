"""`POST /api/factors/derive-eels` and the `eels_derive_cross_sections` op
(roadmap 5b, the EELS half of the factor box) — through the API and
through `ops.run`.

`tests/test_eels_factors.py` already proves the pure `calc.eels_factors`
arithmetic. This file proves the ROUTE and the OP wire it up correctly:
that the route resolves a standard (stored or inline), scopes the right
pixels, converts the certificate to the atomic basis `eels_quant`
requires, and that the op reproduces the same numbers for the same input.

The cube throughout carries two REAL edges (O K at 532 eV, Fe L23 at
708 eV, onsets from `calc.eels.EELS_EDGES` rather than transcribed) over
a shared power-law background, mirroring `tests/test_api_eels_maps.py`'s
approach.

The closure in `test_closure_reproduces_the_certificate_only_on_the_atomic_basis`
is the load-bearing test: `intensity/value`, normalised to 100, recovers
whatever atomic fractions the route actually divided by — a general
identity of `derive_cross_sections`'s algebra (see the derivation in that
test's docstring), so it fails outright if the route forgot to convert a
weight-basis certificate to atomic fractions before deriving.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fermiviewer.ops as ops
from fermiviewer.calc.eels import EELS_EDGES
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.ops import catalogue_eels_factors  # noqa: F401 (registers the op)
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.minidm4 import write_mini_dm4

pytestmark = pytest.mark.api

NY, NX, NE = 2, 2, 400
SCALE, OFFSET = 2.0, 300.0  # eV/ch, eV — energies run 300..1098 eV


def _edge(element: str, edge: str):
    return next(e for e in EELS_EDGES if e.element == element and e.edge == edge)


O_EDGE = _edge("O", "K")           # onset 532 eV, Z=8
FE_EDGE = _edge("Fe", "L23")       # onset 708 eV, Z=26

#: signal/background windows either side of each onset, wide enough for a
#: clean power-law fit and never overlapping the other edge
O_SIGNAL, O_BG = (540.0, 600.0), (450.0, 525.0)
FE_SIGNAL, FE_BG = (715.0, 775.0), (630.0, 700.0)

#: One material (Fe2O3) on both bases — the atomic figures are the round
#: 40/60 split; the weight figures are what `calc.composition` converts
#: them to (a_i ∝ w_i/M_i), reusing the exact numbers `test_eels_factors.py`
#: already checked against the real atomic masses so this file need not
#: re-derive them.
AT_PCT = {"Fe": 40.0, "O": 60.0}
WT_PCT = {"Fe": 69.9427, "O": 30.0573}


def _energy() -> np.ndarray:
    return OFFSET + SCALE * np.arange(NE)


def _pixel(o_amp: float, fe_amp: float) -> np.ndarray:
    """One pixel's spectrum: power-law background plus two step edges."""
    energy = _energy()
    background = 8000.0 * (energy / energy[0]) ** -3.0
    o_jump = o_amp * (energy >= O_EDGE.onset_ev)
    fe_jump = fe_amp * (energy >= FE_EDGE.onset_ev)
    return (background + o_jump + fe_jump).astype(np.float32)


#: amplitudes for the uniform cube (tests 1-6, 8): both edges present in
#: every pixel, ratio not 1:1 so a basis mix-up cannot hide as a fluke
UNIFORM_PIXEL = _pixel(o_amp=4000.0, fe_amp=2500.0)

#: amplitudes for the split cube (test 7): opposite O:Fe ratios left vs
#: right, the same trick `test_api_standards_factors.py`'s
#: `test_a_region_restricts_which_pixels_are_fitted` uses for EDS
LEFT_PIXEL = _pixel(o_amp=6000.0, fe_amp=1200.0)
RIGHT_PIXEL = _pixel(o_amp=1200.0, fe_amp=6000.0)


def _write_cube(tmp_path, name: str, columns: list[np.ndarray]) -> Path:
    """`columns[x]` is the (identical-down-every-row) spectrum for column x."""
    cube = np.empty((NY, NX, NE), dtype=np.float32)
    for x, spec in enumerate(columns):
        for y in range(NY):
            cube[y, x] = spec
    # file order is d0 (x) fastest, E slowest (tests/test_api_eels_maps.py)
    flat = np.transpose(cube, (2, 0, 1)).ravel()
    return write_mini_dm4(
        tmp_path / name, dims=[NX, NY, NE], data=flat, data_type=2,
        cal=[
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": 1, "origin": 0, "units": "nm"},
            {"scale": SCALE, "origin": -OFFSET / SCALE, "units": "eV"},
        ],
    )


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FV_STANDARDS_PATH", str(tmp_path / "standards.json"))
    monkeypatch.setenv("FV_FACTORS_PATH", str(tmp_path / "factors.json"))
    monkeypatch.setenv("FV_PROFILES_PATH", str(tmp_path / "profiles.json"))
    store.clear()
    yield
    store.clear()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(), base_url="http://localhost")


@pytest.fixture()
def cube_id(client, tmp_path) -> str:
    """Uniform 2x2 px cube: every pixel carries both edges identically."""
    f = _write_cube(tmp_path, "eels.dm4", [UNIFORM_PIXEL, UNIFORM_PIXEL])
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


@pytest.fixture()
def split_cube_id(client, tmp_path) -> str:
    """2x2 px cube: column 1 is O-rich, column 2 is Fe-rich."""
    f = _write_cube(tmp_path, "split.dm4", [LEFT_PIXEL, RIGHT_PIXEL])
    r = client.post("/api/session/open", json={"paths": [str(f)]})
    assert r.status_code == 200
    return r.json()[0]["id"]


def _edge_specs() -> list[dict]:
    return [
        {"element": "O", "shell": "K", "z": 8, "onset_ev": O_EDGE.onset_ev,
         "signal_window": list(O_SIGNAL), "bg_window": list(O_BG)},
        {"element": "Fe", "shell": "L", "z": 26, "onset_ev": FE_EDGE.onset_ev,
         "signal_window": list(FE_SIGNAL), "bg_window": list(FE_BG)},
    ]


def _derive(client, **over):
    body: dict = {
        "edges": _edge_specs(),
        "beam_kv": 200.0,
        "collection_semi_angle_mrad": 10.0,
    }
    body.update(over)
    return client.post("/api/factors/derive-eels", json=body)


def _derive_ok(client, **over) -> dict:
    r = _derive(client, **over)
    assert r.status_code == 200, r.text
    return r.json()


def _standard(client, **over) -> dict:
    body = {
        "name": "Fe2O3",
        "basis": "wt",
        "composition": {"Fe": {"value": WT_PCT["Fe"], "unit": "%", "sigma": 0.0},
                         "O": WT_PCT["O"]},
    }
    body.update(over)
    r = client.post("/api/standards", json=body)
    assert r.status_code == 200, r.text
    return r.json()["standard"]


# ── 1. happy path: response shape ───────────────────────────────────────


def test_happy_path_response_shape(client, cube_id) -> None:
    body = _derive_ok(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at"
    )
    assert body["kind"] == "sigma"
    assert body["reference_element"] in ("O", "Fe")

    for el in ("O", "Fe"):
        f = body["factors"][el]
        # every field the route promises, each independently checkable
        # rather than merely present (a wrong number here still has the key)
        assert f["value"] > 0.0
        assert f["intensity"] > 0.0
        assert f["model_value"] > 0.0
        assert f["atomic_fraction"] == pytest.approx(AT_PCT[el] / 100.0)
        assert isinstance(f["sigma"], float)
        assert isinstance(f["intensity_sigma"], float)
        assert isinstance(body["model_ratio"][el], float)

    cond = body["conditions"]
    assert cond["beam_kv"] == 200.0
    assert cond["collection_semi_angle_mrad"] == 10.0
    assert cond["background_method"] == "powerlaw"
    assert cond["windows"]["O"]["onset_ev"] == O_EDGE.onset_ev
    assert cond["windows"]["O"]["signal_window"] == list(O_SIGNAL)
    assert cond["windows"]["Fe"]["bg_window"] == list(FE_BG)

    df = body["derived_from"]
    assert df["basis"] == "at"
    assert df["image_id"] == cube_id
    assert df["scope"]["scoped"] is False        # whole image, no roi/region
    assert df["anchor"] == "hydrogenic model (calc.eels_quant.cross_section)"

    cal = body["calibration"]
    assert cal["beam_kv"]["value"] == 200.0
    assert cal["beam_kv"]["origin"] == "request"
    assert cal["collection_semi_angle_mrad"]["origin"] == "request"


# ── 2. the closure that catches a basis mix-up ──────────────────────────


def test_closure_reproduces_the_certificate_only_on_the_atomic_basis(
    client, cube_id
) -> None:
    """Certify on the WEIGHT basis, as a real Fe2O3 certificate would.

    `derive_cross_sections`'s algebra makes ``intensity/value`` exactly
    proportional to whatever atomic fraction was divided in — see
    `test_eels_factors.py`'s own closure test. So normalising the
    RETURNED intensities and values to 100 must reproduce the 40/60
    ATOMIC split, not the 69.94/30.06 WEIGHT split that was actually
    typed into the request. If the route treated `composition` as already
    atomic (skipped the wt->at conversion), this recovers ~70/30 instead
    and the assertion below fails.
    """
    body = _derive_ok(
        client, image_id=cube_id, composition=dict(WT_PCT), basis="wt"
    )
    intensity = np.array([body["factors"][e]["intensity"] for e in ("Fe", "O")])
    value = np.array([body["factors"][e]["value"] for e in ("Fe", "O")])
    ratio = intensity / value
    at_pct = 100.0 * ratio / ratio.sum()
    # rtol loosened from the calc-level test's 1e-9: the cube round-trips
    # through a float32 DM4 file and a numeric background/trapz fit, both
    # of which the pure-arithmetic test bypasses. 1e-4 is still four
    # orders of magnitude tighter than the ~75/25 a basis mix-up produces.
    np.testing.assert_allclose(at_pct, [AT_PCT["Fe"], AT_PCT["O"]], rtol=1e-4)

    # negative control: the WEIGHT split is a real, different number, so a
    # test that could not distinguish the two would not be exercising
    # anything -- assert it does NOT come back as 69.94/30.06
    assert at_pct[0] != pytest.approx(WT_PCT["Fe"], abs=1.0)


# ── 3. store round-trips ─────────────────────────────────────────────────


def test_store_round_trips_through_list_and_get(client, cube_id) -> None:
    body = _derive_ok(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at",
        store=True, name="Fe2O3 sigma",
    )
    fs = body["factor_set"]
    assert fs["kind"] == "sigma"

    listed = client.get("/api/factors?kind=sigma").json()["factor_sets"]
    assert fs["id"] in {s["id"] for s in listed}
    # kind filtering actually filters -- a "k" set from another test run
    # (or a bug that ignores the query param) would otherwise slip in
    assert all(s["kind"] == "sigma" for s in listed)

    got = client.get(f"/api/factors/{fs['id']}").json()["factor_set"]
    for el in ("O", "Fe"):
        assert got["factors"][el]["atomic_fraction"] == pytest.approx(
            body["factors"][el]["atomic_fraction"]
        )
        assert got["factors"][el]["model_value"] == pytest.approx(
            body["factors"][el]["model_value"]
        )
        assert got["factors"][el]["value"] == pytest.approx(
            body["factors"][el]["value"]
        )


# ── 4. reference_value_m2 rescales, model_value does not move ───────────


def test_reference_value_m2_rescales_every_value_uniformly(client, cube_id) -> None:
    base = _derive_ok(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at",
        reference_element="O",
    )
    model_o = base["factors"]["O"]["model_value"]
    factor = 3.7  # arbitrary, not 1 -- a bug that ignores the anchor is 1.0
    scaled = _derive_ok(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at",
        reference_element="O", reference_value_m2=factor * model_o,
    )
    for el in ("O", "Fe"):
        assert scaled["factors"][el]["value"] == pytest.approx(
            factor * base["factors"][el]["value"], rel=1e-9
        )
        # the comparison the response carries must survive the rescale
        # untouched -- it is a statement about the MODEL, not the anchor
        assert scaled["factors"][el]["model_value"] == pytest.approx(
            base["factors"][el]["model_value"]
        )


# ── 5. refusals name their cause ─────────────────────────────────────────


def test_empty_edges_is_refused(client, cube_id) -> None:
    r = _derive(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at", edges=[]
    )
    assert r.status_code == 422
    assert "at least one edge" in r.json()["detail"]


def test_two_edges_for_the_same_element_is_refused(client, cube_id) -> None:
    dupe_edges = [_edge_specs()[0], _edge_specs()[0]]  # both "O"
    r = _derive(
        client, image_id=cube_id, composition=dict(AT_PCT), basis="at",
        edges=dupe_edges,
    )
    assert r.status_code == 422
    assert "more than once" in r.json()["detail"]
    assert "O" in r.json()["detail"]


def test_element_the_standard_states_no_composition_for_is_refused(
    client, cube_id
) -> None:
    # composition states only O; the edges (O, Fe) ask for Fe as well
    r = _derive(
        client, image_id=cube_id, composition={"O": 100.0}, basis="at"
    )
    assert r.status_code == 422
    assert "no composition for" in r.json()["detail"]
    assert "Fe" in r.json()["detail"]


def test_neither_standard_id_nor_inline_composition_is_refused(client) -> None:
    r = _derive(client, edges=[_edge_specs()[0]])
    assert r.status_code == 422
    assert "standard_id" in r.json()["detail"]
    assert "inline composition" in r.json()["detail"]


def test_both_standard_id_and_inline_composition_is_refused(client) -> None:
    std = _standard(client)
    r = _derive(
        client, edges=[_edge_specs()[0]], standard_id=std["id"],
        composition=dict(AT_PCT), basis="at",
    )
    assert r.status_code == 422
    assert "not both" in r.json()["detail"]


# ── 6. a stored standard, and a region_label that scopes the sum ────────


def test_stored_standard_and_region_label_scope_the_sum(
    client, split_cube_id
) -> None:
    """`region_label` must resolve to exactly the pixels the same roi
    string would select directly -- so compare the two rather than merely
    asserting the request succeeds."""
    std = _standard(client)
    left_roi = f"1,1,{NY},1"
    r = client.post(
        f"/api/standards/{std['id']}/regions",
        json={"label": "o-rich", "image_id": split_cube_id, "roi": left_roi},
    )
    assert r.status_code == 200, r.text

    via_label = _derive_ok(client, standard_id=std["id"], region_label="o-rich")
    via_roi = _derive_ok(
        client, standard_id=std["id"], image_id=split_cube_id, roi=left_roi
    )
    for el in ("O", "Fe"):
        assert via_label["factors"][el]["value"] == pytest.approx(
            via_roi["factors"][el]["value"], rel=1e-9
        )
    # and provenance names the image the region actually pointed at, not
    # a null (the same self-review finding the EDS sibling test guards)
    assert via_label["derived_from"]["image_id"] == split_cube_id


# ── 7. region scoping is APPLIED, not merely recorded ────────────────────


def test_region_scoping_changes_the_derived_set(client, split_cube_id) -> None:
    """Column 1 is O-rich (6000:1200) and column 2 is Fe-rich (1200:6000)
    by construction, so a derivation restricted to one column must differ
    from one restricted to the other. If the route recorded `roi` in the
    response without ever masking the spectrum by it, both calls would
    read the same whole-field sum and come back identical -- the one
    mutation this test exists to catch.
    """
    # Pin the reference element explicitly: the DEFAULT reference's own
    # `value` is, by definition, the anchor -- identical in both calls
    # regardless of scope (`derive_cross_sections`: ratio_ref/ratio_ref
    # cancels for sym == ref). Testing the wrong element would pass
    # vacuously even with scoping completely broken.
    std = _standard(client)
    left = _derive_ok(
        client, standard_id=std["id"], image_id=split_cube_id,
        roi=f"1,1,{NY},1", reference_element="Fe",
    )
    right = _derive_ok(
        client, standard_id=std["id"], image_id=split_cube_id,
        roi=f"1,2,{NY},2", reference_element="Fe",
    )
    # raw measured intensities are untouched by any reference-anchoring
    # algebra, so they are the most direct evidence the mask selected
    # different pixels at all
    assert left["factors"]["O"]["intensity"] != pytest.approx(
        right["factors"]["O"]["intensity"], rel=1e-3
    )
    assert left["factors"]["Fe"]["intensity"] != pytest.approx(
        right["factors"]["Fe"]["intensity"], rel=1e-3
    )
    # and it propagates to the derived value of the non-reference element.
    # abs=0: pytest.approx's default 1e-12 absolute floor would swallow
    # any difference between two ~1e-25 m² cross-sections outright, which
    # is not a claim this test wants to make -- only the RELATIVE size of
    # the difference matters here.
    assert left["factors"]["O"]["value"] != pytest.approx(
        right["factors"]["O"]["value"], rel=1e-3, abs=0
    )
    assert left["model_ratio"]["O"] != pytest.approx(
        right["model_ratio"]["O"], rel=1e-3, abs=0
    )
    # Fe was pinned as the reference, so ITS value is the anchor alone and
    # must NOT move with the region -- the exemption `derive_cross_sections`
    # gives the reference element (`ratio_ref/ratio_ref` cancels) is a real
    # property of a sigma set worth pinning down, not an omission.
    assert left["factors"]["Fe"]["value"] == pytest.approx(
        right["factors"]["Fe"]["value"], rel=1e-9
    )
    # the scope block must say so too, not just the numbers
    assert left["derived_from"]["scope"]["scoped"] is True
    assert left["derived_from"]["scope"]["rect"] == [1, 1, NY, 1]


# ── 8. the op reproduces the route's numbers ─────────────────────────────


def test_op_matches_the_route_for_the_same_input(client, cube_id) -> None:
    """Parity contract (ADR 0005 §1): the op and the route must not be two
    implementations of the same idea that can silently drift apart."""
    route = _derive_ok(
        client, image_id=cube_id, composition=dict(WT_PCT), basis="wt",
        reference_element="O",
    )

    ds = DataStruct(
        data=np.tile(UNIFORM_PIXEL.astype(np.float64), (NY, NX, 1)),
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(1.0, 0.0, "nm"),
            AxisCal(SCALE, -OFFSET / SCALE, "eV"),
        ),
        metadata={"source": "synthetic-eels"},
    )
    edges_str = (
        f"O:K:8:{O_EDGE.onset_ev:g}:{O_SIGNAL[0]:g}-{O_SIGNAL[1]:g}:"
        f"{O_BG[0]:g}-{O_BG[1]:g},"
        f"Fe:L:26:{FE_EDGE.onset_ev:g}:{FE_SIGNAL[0]:g}-{FE_SIGNAL[1]:g}:"
        f"{FE_BG[0]:g}-{FE_BG[1]:g}"
    )
    comp_str = f"Fe:{WT_PCT['Fe']},O:{WT_PCT['O']}"
    result = ops.run(
        "eels_derive_cross_sections", ds,
        {
            "edges": edges_str,
            "composition": comp_str,
            "basis": "wt",
            "reference_element": "O",
            "reference_value_m2": 0.0,
            "beam_kv": 200.0,
            "collection_semi_angle_mrad": 10.0,
            "background": "powerlaw",
        },
    )
    table = result.value["outputs"][0]["data"]
    by_element = {row[0]: row for row in table["rows"]}
    assert result.value["reference_element"] == route["reference_element"]

    columns = table["columns"]
    for el in ("O", "Fe"):
        row = dict(zip(columns, by_element[el], strict=True))
        f = route["factors"][el]
        assert row["cross_section"] == pytest.approx(f["value"], rel=1e-9)
        assert row["cross_section_sigma"] == pytest.approx(f["sigma"], rel=1e-9)
        assert row["model_cross_section"] == pytest.approx(f["model_value"], rel=1e-9)
        assert row["net_intensity"] == pytest.approx(f["intensity"], rel=1e-9)
        assert row["net_intensity_sigma"] == pytest.approx(
            f["intensity_sigma"], rel=1e-9
        )
        assert row["atomic_fraction"] == pytest.approx(f["atomic_fraction"], rel=1e-9)


# ── 9. the op's edge-string parser refuses malformed edges ───────────────


def _dummy_ds() -> DataStruct:
    """Any spectral dataset — the parser errors below fire before the
    spectrum is ever read."""
    n = 20
    return DataStruct(
        data=np.linspace(1.0, 2.0, n),
        kind=DataKind.SPECTRUM,
        axes=(AxisCal(1.0, 0.0, "eV"),),
        metadata={},
    )


@pytest.mark.parametrize(
    ("edges", "match"),
    [
        # wrong field count -- 5 colon-separated fields, not 6
        ("O:K:8:532:540-600", "must be"),
        ("O:X:8:532:540-600:450-525", "shell must be 'K' or 'L'"),
        ("O:K:abc:532:540-600:450-525", "non-numeric Z or onset"),
        # signal window with no '-' separator
        ("O:K:8:532:540:450-525", "must be 'lo-hi' in eV"),
        ("O:K:8:532:600-540:450-525", "must have hi > lo"),
        (
            "O:K:8:532:540-600:450-525,O:K:8:532:715-775:630-700",
            "appear more than once",
        ),
    ],
)
def test_op_edge_parser_refusals(edges, match) -> None:
    with pytest.raises(ValueError, match=match):
        ops.run(
            "eels_derive_cross_sections", _dummy_ds(),
            {"edges": edges, "composition": "O:60,Fe:40", "basis": "at"},
        )
