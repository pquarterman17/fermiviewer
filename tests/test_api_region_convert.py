"""4B — the label map ⇄ region-set conversion routes.

`calc/region_convert.py` has its own suite, and a passing round trip
there says nothing about whether the feature can be REACHED. That was
the shape of the worst defect in 4C-5: the geometry was right, the
request model dropped the field carrying it, and every test stopped
short of the HTTP boundary — so the feature was unreachable and the
tests were green. These cross it.

The seam with real teeth is the dtype. `routes/structure._register`
stores every derived map as float64, so the label map a segmentation
hands back is `array([1., 2., ...])` — and `labels_to_regions` refuses a
float array on purpose. A route that cast blindly would walk straight
past that refusal at the one boundary it exists to guard.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.project_session import project
from fermiviewer.routes.region_sets_api import MAX_EXACT_LABEL
from fermiviewer.server import create_app
from fermiviewer.session import store

pytestmark = pytest.mark.api


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


def _labels() -> np.ndarray:
    """Two labels, one of them holed and disconnected — so the assertions
    below distinguish a real conversion from a bounding box.

    NOT square, deliberately. A 24x24 map lets a transposed axis or a
    shape read off the wrong dimension produce the right answer, which is
    how a row/col swap survives a whole suite.
    """
    labels = np.zeros((24, 30), dtype=np.float64)
    labels[2:14, 2:14] = 1
    labels[6:10, 6:10] = 0
    labels[17:21, 17:21] = 1
    labels[2:6, 25:29] = 2
    return labels


def _add(array: np.ndarray, name: str = "grains.tif") -> str:
    ds = DataStruct(
        data=array, kind=DataKind.IMAGE, axes=(AxisCal(), AxisCal()), metadata={}
    )
    return store.add_parsed(ds, name)


def _install(client: TestClient, manifest: dict) -> None:
    assert client.post("/api/region-sets/replace", json=manifest).status_code == 200


# ── the loop the feature exists for ──────────────────────────────────


def test_a_label_map_converts_edits_and_converts_back(client) -> None:
    """The whole point of 4B in one pass: segment, convert, correct by
    hand, convert back, and get a label map that differs from the
    original in exactly the pixels the edit touched.

    The edit here DELETES a region, which is the cheapest correction to
    verify and the one a hand-correction workflow makes most: label 2 was
    a mis-segmented speck. Its pixels must come back as background and
    nothing else may move.
    """
    labels = _labels()
    image_id = _add(labels)

    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert made.status_code == 200, made.text
    manifest = made.json()
    (group,) = manifest["sets"]
    assert [r["id"] for r in group["regions"]] == ["label_1", "label_2"]
    assert group["image_id"] == image_id, "a traced region is bound to its map"

    # the hand edit: drop the speck, keep the grain
    group["regions"] = [r for r in group["regions"] if r["id"] != "label_2"]
    _install(client, manifest)

    back = client.post(
        "/api/region-sets/to-labels",
        json={
            "set_id": "grains",
            "image_id": image_id,
            "values": {"label_1": 1},
        },
    )
    assert back.status_code == 200, back.text
    out = np.asarray(store.get(back.json()["id"]).data)

    expected = labels.copy()
    expected[expected == 2] = 0
    assert np.array_equal(out, expected)


def test_structure_survives_the_route_not_just_the_pixels(client) -> None:
    """A hole and a second component have to reach the client, since the
    hand-editing UI is what consumes them. Rasterizing to the right
    pixels through a union would hide either one."""
    image_id = _add(_labels())
    manifest = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    one, two = manifest["sets"][0]["regions"]
    assert len(one["parts"]) == 2, "label 1 is disconnected"
    # `regions_to_manifest` omits `holes` when there are none, so the
    # holed part is found by asking rather than by indexing — and the
    # absence is asserted too, since a reader who expects the key would
    # write this test wrong (I did).
    holes = [len(p["shape"].get("holes", ())) for p in one["parts"]]
    assert sorted(holes) == [0, 1]
    assert "holes" not in one["parts"][holes.index(0)]["shape"]
    assert len(two["parts"]) == 1


def test_the_id_prefix_reaches_the_converter(client) -> None:
    """A request field that never arrives is the 4C-5 defect exactly, and
    it is invisible whenever the default happens to be right."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains", "prefix": "grain"},
    ).json()
    assert [r["id"] for r in made["sets"][0]["regions"]] == ["grain_1", "grain_2"]


def test_explicit_label_values_reach_the_converter(client) -> None:
    """Deliberately NOT 1..n: a caller re-writing a corrected map wants
    the original numbering back, and auto-numbering would silently
    renumber every grain in a table that already refers to them."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    out = client.post(
        "/api/region-sets/to-labels",
        json={
            "set_id": "grains",
            "image_id": image_id,
            "values": {"label_1": 7, "label_2": 3},
        },
    ).json()
    array = np.asarray(store.get(out["id"]).data)
    assert sorted(np.unique(array).tolist()) == [0, 3, 7]


def test_an_unbound_conversion_is_offered_but_not_the_default(client) -> None:
    image_id = _add(_labels())
    body = {"image_id": image_id, "set_id": "grains", "bind_image": False}
    made = client.post("/api/region-sets/from-labels", json=body).json()
    assert made["sets"][0]["image_id"] is None
    assert made["sets"][0]["meta"]["derived_from"] == image_id, (
        "unbinding drops the CONSTRAINT, not the provenance"
    )


def test_from_labels_does_not_write_the_workspace(client) -> None:
    """`/replace` is the one path that writes the live section. A second
    one would be a second set of rules about what a write means."""
    image_id = _add(_labels())
    assert client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).status_code == 200
    assert client.get("/api/region-sets").json()["sets"] == []


def test_the_converted_set_is_accepted_by_the_replace_route(client) -> None:
    """The two routes must agree on the wire form; serializing through
    `regions_to_manifest` is what makes that true rather than hopeful."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    assert client.get("/api/region-sets").json() == made


# ── refusals at the boundary ─────────────────────────────────────────


def test_an_intensity_image_is_refused_rather_than_traced(client) -> None:
    """The dtype seam. A real micrograph has fractional values, and
    casting it would produce a region per grey level — a plausible,
    enormous, meaningless answer. `labels_to_regions` refuses a float
    array for this reason and the route must not step around it.
    """
    rng = np.random.default_rng(0)
    image_id = _add(rng.normal(100.0, 5.0, (16, 20)), "micrograph.dm4")
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "not a label map" in r.json()["detail"]


def test_a_float_map_of_whole_numbers_is_accepted(client) -> None:
    """The other half of the same rule: `_register` stores label maps as
    float64, so refusing every float would refuse the app's OWN maps and
    make the feature unreachable in the one case it is for."""
    image_id = _add(_labels())
    assert store.get(image_id).data.dtype == np.float64
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_a_map_with_a_non_finite_value_is_refused(client, bad: float) -> None:
    """NaN and infinity fail for DIFFERENT reasons, which is why the
    check tests both. `np.rint(nan) == nan` compares False, so a NaN is
    caught by the whole-number test alone — but `np.rint(inf) == inf` is
    True, so an infinity passes it and reaches `astype(np.int64)`, which
    turns it into -9223372036854775808 and traces a region for it.
    """
    labels = _labels()
    labels[0, 0] = bad
    image_id = _add(labels)
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "not a label map" in r.json()["detail"]


def test_unknown_ids_are_404_and_bad_references_are_422(client) -> None:
    image_id = _add(_labels())
    assert client.post(
        "/api/region-sets/from-labels",
        json={"image_id": "nope", "set_id": "grains"},
    ).status_code == 404
    assert client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": "nope"},
    ).status_code == 404
    r = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    )
    assert r.status_code == 422


def test_a_set_drawn_on_another_image_cannot_become_this_one_s_labels(client) -> None:
    """ADR 0007 §6, reached through the route rather than restated in it.
    Writing a region from another specimen into this map's labels would
    put the wrong shapes on the wrong sample with nothing to show for it.
    """
    image_id = _add(_labels())
    other_id = _add(_labels(), "other.tif")
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": other_id, "set_id": "grains"},
    ).json()
    _install(client, made)

    r = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    )
    assert r.status_code == 422
    assert "drawn on image" in r.json()["detail"]


def test_a_single_region_reference_is_refused(client) -> None:
    """`set/region` resolves fine and means one region — but a label map
    is made from a whole set, and quietly writing a one-region map would
    look like the set converted."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    r = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains/label_1", "image_id": image_id},
    )
    assert r.status_code == 422
    assert "whole set" in r.json()["detail"]


def test_overlapping_regions_are_refused_at_the_route(client) -> None:
    """The hand-editing case that produces it: a user drags one region
    over another. `LabelOverlapError` is a ValueError, so this arrives as
    a 422 rather than escaping as a 500."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    regions = made["sets"][0]["regions"]
    regions[1]["parts"] = [dict(p) for p in regions[0]["parts"]]
    _install(client, made)

    r = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    )
    assert r.status_code == 422
    assert "overlaps" in r.json()["detail"]


def test_the_registered_map_records_where_it_came_from(client) -> None:
    """A label map with no provenance cannot be told from a segmenter's
    own output, and the difference is whether a human edited it."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    out = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    ).json()
    meta = store.get(out["id"]).metadata
    assert meta["region_source"] == "grains"
    assert meta["converter"] == "regions"


def test_a_spectrum_image_is_refused_by_kind_not_by_value(client) -> None:
    """`raster_of` answers for a SPECTRUM_IMAGE by summing the energy
    axis, and a count cube sums to whole numbers — so the value check
    would pass and this would trace a region per count. The kind settles
    it before any value is looked at. Same for RGB, whose raster is a
    luminance.
    """
    counts = np.zeros((8, 8, 4), dtype=np.float64)
    counts[2:5, 2:5, :] = 3.0
    ds = DataStruct(
        data=counts,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal()),
        metadata={},
    )
    si_id = store.add_parsed(ds, "si.dm4")
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": si_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "spectrum_image" in r.json()["detail"]


def test_to_labels_still_accepts_any_raster_for_its_shape(client) -> None:
    """The two routes ask different things of their image, so they get
    different rules. `from-labels` READS the values, so the kind matters;
    `to-labels` uses the image only for its SHAPE, and a spectrum image
    has a perfectly good one."""
    cube = np.zeros((24, 30, 3), dtype=np.float64)
    ds = DataStruct(
        data=cube,
        kind=DataKind.SPECTRUM_IMAGE,
        axes=(AxisCal(), AxisCal(), AxisCal()),
        metadata={},
    )
    si_id = store.add_parsed(ds, "si.dm4")
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": _add(_labels()), "set_id": "grains", "bind_image": False},
    ).json()
    _install(client, made)
    out = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": si_id},
    )
    assert out.status_code == 200, out.text
    assert np.asarray(store.get(out.json()["id"]).data).shape == (24, 30)


# ── the default edit loop preserves identity ─────────────────────────


def _sparse() -> np.ndarray:
    """Labels 2 and 5, no 1, no 3 — the shape `min_area` filtering and
    hand deletion both produce, and the one positional renumbering
    destroys."""
    labels = np.zeros((24, 30), dtype=np.float64)
    labels[2:8, 2:8] = 2
    labels[14:20, 20:26] = 5
    return labels


def test_the_edit_loop_preserves_sparse_labels_with_no_mapping(client) -> None:
    """The workflow as a client actually performs it: convert, edit,
    convert back — WITHOUT reconstructing a values mapping. Requiring one
    made the default lossy and pushed the loss onto every caller, and the
    round-trip tests missed it because they supplied the original
    numbering out of band.
    """
    labels = _sparse()
    image_id = _add(labels)
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)

    out = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    )
    assert out.status_code == 200, out.text
    assert np.array_equal(np.asarray(store.get(out.json()["id"]).data), labels)


def test_deleting_a_region_leaves_the_others_numbered_as_they_were(client) -> None:
    """Label 5 must still be 5 after label 2 is deleted. Positionally it
    became 1, which silently moves every measurement recorded against it."""
    image_id = _add(_sparse())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    made["sets"][0]["regions"] = [
        r for r in made["sets"][0]["regions"] if r["id"] != "label_2"
    ]
    _install(client, made)

    out = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    ).json()
    array = np.asarray(store.get(out["id"]).data)
    assert sorted(np.unique(array).tolist()) == [0, 5]


def test_the_source_value_travels_in_metadata_not_only_in_the_id(client) -> None:
    """An id is a NAME and a caller may rename a region. Parsing the
    value back out of one would make the name load-bearing, so the value
    rides in `meta` and survives the manifest round trip."""
    image_id = _add(_sparse())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    assert [r["meta"]["label_value"] for r in made["sets"][0]["regions"]] == [2, 5]

    # rename both, and the values must still come back
    for region, name in zip(made["sets"][0]["regions"], ("alpha", "beta"), strict=True):
        region["id"] = name
    _install(client, made)
    out = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    ).json()
    array = np.asarray(store.get(out["id"]).data)
    assert sorted(np.unique(array).tolist()) == [0, 2, 5]


# ── integer identity at the registration seam ────────────────────────


def test_a_label_beyond_exact_float64_is_refused_not_rounded(client) -> None:
    """A session map is float64, so 2**53 + 1 is stored as 2**53 — two
    regions merged into one with nothing in the array to say so. Refused
    rather than rounded, and the bound is checked on the produced MAP, so
    a value arriving through region metadata is covered too.
    """
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    r = client.post(
        "/api/region-sets/to-labels",
        json={
            "set_id": "grains",
            "image_id": image_id,
            "values": {"label_1": 1, "label_2": 2**53 + 1},
        },
    )
    assert r.status_code == 422
    assert "float64" in r.json()["detail"]


def test_a_label_beyond_int64_is_a_422_not_a_500(client) -> None:
    """numpy raises `OverflowError` — an ArithmeticError, not a
    ValueError — writing this into the int64 map, so it escaped the
    `value_error_as_422` guard and surfaced as a server error."""
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    r = client.post(
        "/api/region-sets/to-labels",
        json={
            "set_id": "grains",
            "image_id": image_id,
            "values": {"label_1": 1, "label_2": 2**63},
        },
    )
    assert r.status_code == 422


@pytest.mark.parametrize("bad", [True, "2", 2.0])
def test_the_request_model_does_not_coerce_its_way_past_the_refusals(
    client, bad: object
) -> None:
    """Pydantic's lax mode turns `true` into 1, `"2"` into 2 and `2.0`
    into 2 — so `regions_to_labels`' bool, string and float refusals never
    saw the value they exist to reject. `StrictInt` makes them reachable
    by refusing at the boundary instead, in the boundary's own vocabulary.
    """
    image_id = _add(_labels())
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    ).json()
    _install(client, made)
    # BOTH regions get a value, and 9 collides with nothing. Without
    # that, `label_2` has no value and the 422 comes from the missing-key
    # check instead — the test passes under lax coercion and proves
    # nothing. (It did; mutation testing is what said so.)
    r = client.post(
        "/api/region-sets/to-labels",
        json={
            "set_id": "grains",
            "image_id": image_id,
            "values": {"label_1": bad, "label_2": 9},
        },
    )
    assert r.status_code == 422


# ── one supported range, both directions ─────────────────────────────


def _at(value: int, dtype: object = np.float64) -> np.ndarray:
    labels = np.zeros((12, 12), dtype=dtype)  # type: ignore[arg-type]
    labels[2:6, 2:6] = value
    return labels


def test_the_two_directions_agree_on_the_largest_label(client) -> None:
    """The property that was broken, stated directly: anything
    `from-labels` hands out, `to-labels` takes back.

    `to-labels` alone enforced the float64 bound, which made the domain
    ASYMMETRIC rather than bounded — `from-labels` accepted 2**53 + 2
    (exactly representable, so it passed every check), recorded it as a
    region's `label_value`, and `to-labels` then refused that same
    untouched region. The default round trip was not lossless for any
    input the two ends disagreed about.

    2**53 is the boundary value, so it exercises the bound rather than
    sitting safely inside it.
    """
    labels = _at(MAX_EXACT_LABEL)
    image_id = _add(labels)
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["sets"][0]["regions"][0]["meta"]["label_value"] == MAX_EXACT_LABEL
    _install(client, body)

    back = client.post(
        "/api/region-sets/to-labels",
        json={"set_id": "grains", "image_id": image_id},
    )
    assert back.status_code == 200, back.text
    assert np.array_equal(np.asarray(store.get(back.json()["id"]).data), labels)


def test_a_label_past_the_range_is_refused_on_the_way_in(client) -> None:
    """2**53 + 2 is exactly representable in float64, so no rounding check
    catches it — only the range does. Refused at input rather than
    accepted and rejected later, which is the asymmetry itself."""
    image_id = _add(_at(MAX_EXACT_LABEL + 2))
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "supported range" in r.json()["detail"]


def test_a_label_past_int64_does_not_reach_the_cast(client) -> None:
    """`astype(np.int64)` on 2**63 does not raise — it warns
    (`invalid value encountered in cast`) and yields INT_MIN. This repo
    runs `filterwarnings = ["error"]`, so under test it became an
    exception and a 500; in production it would have silently traced a
    region for -9223372036854775808."""
    image_id = _add(_at(2**63))
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "supported range" in r.json()["detail"]


@pytest.mark.parametrize("dtype", [np.int64, np.uint64])
def test_an_integer_map_is_bounded_too_though_it_skips_the_cast(
    client, dtype: object
) -> None:
    """An integer image needs no float cast, so it used to skip every
    check that rode along with one — a uint64 map holding 2**63 + 7
    produced a region carrying a label no int64 map can hold. The bound is
    checked on the VALUES, before and independent of any cast."""
    value = 2**63 + 7 if dtype is np.uint64 else 2**62
    image_id = _add(_at(value, dtype))
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "supported range" in r.json()["detail"]


def test_an_ordinary_negative_still_gets_the_message_about_background(client) -> None:
    """The range check bounds MAGNITUDE, deliberately leaving a plain
    negative to `labels_to_regions` — whose message names background and
    tells the caller more than a range would."""
    image_id = _add(_at(-1))
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "non-negative" in r.json()["detail"]


def test_a_hugely_negative_value_is_stopped_before_the_cast(client) -> None:
    """The bound is two-sided even though labels are non-negative.
    -2**64 warns and yields INT_MIN from `astype` exactly as 2**63 does,
    so it has to be caught before the cast — `labels_to_regions`' own
    non-negative refusal comes one step too late to prevent it."""
    image_id = _add(_at(-(2**64)))
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": image_id, "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "supported range" in r.json()["detail"]


def test_a_complex_image_is_refused_by_dtype_and_warns_about_nothing(client) -> None:
    """`DataStruct` permits a complex IMAGE, and 1+1j passes both value
    checks: `isfinite` is true of a complex whose parts are finite, and
    `rint` rounds each part so the value equals its own rounding. Only
    the cast notices — by discarding the imaginary component and calling
    it label 1. A complex micrograph is not a segmentation of its real
    part.

    The refusal is asserted to be SILENT as well as correct: warnings are
    errors in this suite, but stating it locally says the 422 is
    deliberate rather than a `ComplexWarning` that happened to surface.
    """
    import warnings

    data = np.zeros((10, 10), dtype=np.complex128)
    data[2:5, 2:5] = 1 + 1j
    image_id = _add(data, "exit-wave.dm4")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        r = client.post(
            "/api/region-sets/from-labels",
            json={"image_id": image_id, "set_id": "grains"},
        )
    assert r.status_code == 422
    assert "complex128" in r.json()["detail"]


def test_a_real_valued_complex_array_is_refused_too(client) -> None:
    """1+0j has nothing to lose in the cast, which is exactly why it must
    still be refused: accepting it would make the rule "complex is fine
    when it happens to be real", and the next caller's array is 1+1j."""
    data = np.zeros((10, 10), dtype=np.complex64)
    data[2:5, 2:5] = 1 + 0j
    r = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": _add(data, "fft.dm4"), "set_id": "grains"},
    )
    assert r.status_code == 422
    assert "complex64" in r.json()["detail"]


def test_a_boolean_mask_is_still_a_label_map(client) -> None:
    """The restriction is to REAL numeric and bool, not to int and float.
    A boolean mask is the natural one-region label map and must keep
    working — `np.issubdtype(np.bool_, np.integer)` is False, so it
    travels the float path and would be easy to exclude by accident."""
    mask = np.zeros((12, 12), dtype=bool)
    mask[3:8, 3:8] = True
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": _add(mask, "mask.tif"), "set_id": "grains"},
    )
    assert made.status_code == 200, made.text
    regions = made.json()["sets"][0]["regions"]
    assert [r["meta"]["label_value"] for r in regions] == [1]


def test_a_whole_valued_intensity_image_converts_and_that_is_the_contract(
    client,
) -> None:
    """The honest limit of this route, pinned so it cannot be misread.

    Ordinary micrographs are uint8/uint16 — whole-valued, real, in range —
    so they pass every check and convert into one region per distinct
    intensity. No test on the VALUES can do better: a label map and a
    count image are the same array with different meanings. Calling
    `from-labels` is the caller's assertion that this one is a label map.

    Asserted rather than left implicit because the docstring used to
    claim the opposite, and a false claim in a comment is worse than a
    silent gap — it tells the next reader not to check. If a semantic
    guard is ever added (a metadata marker plus an override), this test
    should FAIL and be rewritten deliberately, which is exactly what it
    is for.
    """
    rng = np.random.default_rng(0)
    micrograph = rng.integers(1000, 1120, (48, 48), dtype=np.uint16)
    made = client.post(
        "/api/region-sets/from-labels",
        json={"image_id": _add(micrograph, "micrograph.dm4"), "set_id": "grains"},
    )
    assert made.status_code == 200
    assert len(made.json()["sets"][0]["regions"]) == len(np.unique(micrograph))
