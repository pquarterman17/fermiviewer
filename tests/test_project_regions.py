"""The `regions` section of a `.fvp` — roadmap item 4's persistence box:
`fermiviewer.io.regions_model` through `save_project` / `load_project`.

A region set is the thing an analysis will run inside. If a field of it
does not survive save → reopen, the project has quietly forgotten part of
what the user selected — so the round-trip tests here assert every field
individually rather than comparing objects, exactly as
`test_project_results.py` does, so that a field added later and silently
dropped shows up in review as a missing assertion.

## Why the comparisons are hand-rolled

`Shape` cannot be compared with `==`. It is a frozen dataclass holding
`np.ndarray` rings, so the generated `__eq__` returns an array for any
shape carrying an `outline` or `holes` and raises
"truth value of an array is ambiguous". It works for a plain rect and
fails for a polygon — which makes `assert loaded == saved` a trap rather
than a shortcut. `same_shape` below compares rings with
`np.array_equal`; see the note in the module docstring of
`io/regions_model.py`.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fermiviewer.calc.regions import (
    Part,
    Region,
    circle,
    ellipse,
    polygon,
    rasterize,
    rect,
)
from fermiviewer.datastruct import AxisCal, DataKind, DataStruct
from fermiviewer.io.project_file import load_project, save_project
from fermiviewer.io.project_manifest import (
    LoadedProject,
    ProjectFormatError,
    validate_manifest,
)
from fermiviewer.io.regions_model import (
    REGIONS_SCHEMA,
    RegionClass,
    RegionSet,
    load_regions,
)
from fermiviewer.project_session import ProjectSession, project
from fermiviewer.server import create_app
from fermiviewer.session import store
from fixtures.v1_session import write_v1_session

# ── fixtures ─────────────────────────────────────────────────────────


def _image(img_id: str = "img1") -> tuple[str, str, DataStruct]:
    return (
        img_id,
        "frame.tif",
        DataStruct(
            data=np.arange(64, dtype=np.uint16).reshape(8, 8),
            kind=DataKind.IMAGE,
            axes=(AxisCal(0.5, units="nm"), AxisCal(0.5, units="nm")),
        ),
    )


def _region(region_id: str = "r1") -> Region:
    """One region exercising every structural feature at once: a bounds
    shape with a hole, an exclusion, and a disjoint second include."""
    return Region(
        id=region_id,
        name="grain 3",
        region_class="precipitate",
        meta={"drawn_by": "paige", "nested": {"pass": 2}},
        parts=(
            Part(rect(1, 1, 5, 5, holes=[[(2, 2), (2, 4), (4, 4), (4, 2)]])),
            Part(circle(3.5, 3.5, 1.25), mode="exclude"),
            Part(polygon([(6.5, 6.25), (6.5, 7.75), (7.5, 7.0)])),
        ),
    )


def _set(set_id: str = "s1") -> RegionSet:
    return RegionSet(
        id=set_id,
        name="grain boundaries",
        image_id="img1",
        regions=(_region(),),
        meta={"source": "manual"},
    )


def _save(tmp_path: Path, **kw) -> Path:
    return save_project(tmp_path / "study.fvp", [_image()], **kw)


def _manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json"))


def _rewrite_manifest(path: Path, mutate) -> None:
    """Rewrite manifest.json in place, so a test can produce a container
    no save path would ever write — which is the only way to check what a
    reader does with a hand-edited or newer-build project."""
    with zipfile.ZipFile(path) as zf:
        entries = {n: zf.read(n) for n in zf.namelist()}
    manifest = json.loads(entries["manifest.json"])
    mutate(manifest)
    entries["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def same_ring(a, b) -> bool:
    return a is None and b is None or np.array_equal(np.asarray(a), np.asarray(b))


def same_shape(a, b) -> bool:
    return (
        a.kind == b.kind
        and a.bounds == b.bounds
        and same_ring(a.outline, b.outline)
        and len(a.holes) == len(b.holes)
        and all(same_ring(x, y) for x, y in zip(a.holes, b.holes, strict=True))
    )


# ── the round trip ───────────────────────────────────────────────────


def test_round_trip_is_deep_equal(tmp_path: Path) -> None:
    """Every field of a set and of its regions must survive save → load.
    A region IS the selection an analysis ran inside, so anything dropped
    here is a selection the reopened project can no longer reproduce."""
    original = _set()
    loaded = load_project(_save(tmp_path, region_sets=[original]))

    (group,) = loaded.region_sets
    assert group.id == "s1"
    assert group.name == "grain boundaries"
    assert group.image_id == "img1"
    assert group.meta == {"source": "manual"}

    (region,) = group.regions
    assert region.id == "r1"
    assert region.name == "grain 3"
    assert region.region_class == "precipitate"
    assert region.meta == {"drawn_by": "paige", "nested": {"pass": 2}}
    assert len(region.parts) == 3
    for got, want in zip(region.parts, original.regions[0].parts, strict=True):
        assert got.mode == want.mode
        assert same_shape(got.shape, want.shape)


def test_the_reopened_region_masks_the_same_pixels(tmp_path: Path) -> None:
    """The assertions above compare stored numbers; this one compares the
    only thing a user cares about — which pixels the region selects. A
    coordinate convention silently changed on the way through (0-based to
    1-based, inclusive to half-open) would leave every field equal-looking
    and still move the selection."""
    original = _set()
    loaded = load_project(_save(tmp_path, region_sets=[original]))
    shape = (8, 8)
    before = rasterize(original.regions[0], shape)
    after = rasterize(loaded.region_sets[0].regions[0], shape)

    assert before.any(), "fixture selects no pixels; the test proves nothing"
    assert np.array_equal(before, after)


@pytest.mark.parametrize(
    "shape",
    [
        rect(1, 1, 3, 3),
        rect(0, 0, 7, 7, holes=[[(2, 2), (2, 5), (5, 5), (5, 2)]]),
        ellipse(1, 1, 6, 4),
        circle(3.5, 4.25, 2.5),
        circle(4, 4, 0),
        polygon([(0.5, 0.5), (0.5, 6.5), (6.5, 3.5)]),
        polygon([(1, 1), (1, 6), (6, 6), (6, 1)], holes=[[(2, 2), (2, 4), (4, 4)]]),
    ],
)
def test_every_shape_kind_survives_with_its_geometry(tmp_path: Path, shape) -> None:
    """Each kind reads its stored numbers differently — an ellipse's bounds
    are a pixel footprint, a circle's are a bounding box — so a kind
    mis-tagged in transit would rasterize as a different set of pixels
    while still looking like valid geometry."""
    region = Region(id="r1", parts=(Part(shape),))
    loaded = load_project(_save(tmp_path, region_sets=[RegionSet("s1", (region,))]))
    (back,) = loaded.region_sets[0].regions

    assert same_shape(back.parts[0].shape, shape)
    assert np.array_equal(rasterize(back, (8, 8)), rasterize(region, (8, 8)))


def test_sub_pixel_coordinates_are_not_rounded_by_the_round_trip(
    tmp_path: Path,
) -> None:
    """Region coordinates are float and the rasterizer samples pixel
    centres, so a vertex at 2.5 selects different pixels than one at 2.4.
    JSON round-trips float64 exactly (`repr` is shortest-round-trip) and
    this pins that nothing in the save path quantizes on the way."""
    outline = [(1.1, 1.9), (1.1, 6.0000001), (6.25, 3.0), (2.5, 1.5)]
    region = Region(id="r1", parts=(Part(polygon(outline)),))
    loaded = load_project(_save(tmp_path, region_sets=[RegionSet("s1", (region,))]))

    back = loaded.region_sets[0].regions[0].parts[0].shape.outline
    assert back is not None
    assert back.tolist() == [[float(r), float(c)] for r, c in outline]


def test_a_loaded_project_resaves_its_regions_losslessly(tmp_path: Path) -> None:
    """The server-carried path: load, hand the values straight back to
    `save_project`, reopen. This is what every save through the route does
    with regions the client never echoed back."""
    first = load_project(_save(tmp_path, region_sets=[_set()], region_classes=[
        RegionClass(id="precipitate", label="Precipitate", color="#ff0000"),
    ]))
    again = save_project(
        tmp_path / "again.fvp",
        first.entries,
        region_sets=first.region_sets,
        region_classes=first.region_classes,
    )
    second = load_project(again)

    assert [g.id for g in second.region_sets] == ["s1"]
    assert [c.id for c in second.region_classes] == ["precipitate"]
    assert same_shape(
        second.region_sets[0].regions[0].parts[0].shape,
        first.region_sets[0].regions[0].parts[0].shape,
    )


# ── classes ──────────────────────────────────────────────────────────


def test_region_classes_round_trip_with_their_decoration(tmp_path: Path) -> None:
    loaded = load_project(
        _save(
            tmp_path,
            region_classes=[
                RegionClass(id="substrate", label="Substrate", color="#123456"),
                RegionClass(id="void", note="counted separately"),
            ],
        )
    )
    first, second = loaded.region_classes
    assert (first.id, first.label, first.color) == ("substrate", "Substrate", "#123456")
    assert (second.id, second.label, second.note) == ("void", None, "counted separately")


def test_a_region_may_carry_a_class_that_was_never_declared(tmp_path: Path) -> None:
    """`Region.region_class` is free text by contract — the vocabulary is
    the user's. Persistence must not be stricter than the contract, or a
    region drawn before its class was registered would be unsavable, and
    the section would have invented a second rule about what a class is."""
    region = Region(id="r1", parts=(Part(rect(1, 1, 3, 3)),), region_class="mystery")
    loaded = load_project(
        _save(
            tmp_path,
            region_sets=[RegionSet("s1", (region,))],
            region_classes=[RegionClass(id="substrate")],
        )
    )
    assert loaded.region_sets[0].regions[0].region_class == "mystery"
    assert [c.id for c in loaded.region_classes] == ["substrate"]


# ── the container ────────────────────────────────────────────────────


def test_geometry_is_inline_and_adds_no_zip_members(tmp_path: Path) -> None:
    """Unlike `results`, region geometry lives in the manifest. Measured
    before choosing: a 7,285-point traced contour is 120.5 KiB as JSON
    against 114.0 KiB as .npy, since .npy pays 16 bytes a point for
    float64 either way. Members would buy 1.1x at the cost of a whole
    allocation-and-degradation path, so there is none — and this pins that
    the container shape is unchanged."""
    path = _save(tmp_path, region_sets=[_set()])
    with zipfile.ZipFile(path) as zf:
        assert sorted(zf.namelist()) == [
            "manifest.json",
            "pixels/img1.npy",
            "thumbs/img1.png",
        ]
    section = _manifest(path)["regions"]
    assert section["schema"] == REGIONS_SCHEMA
    assert section["sets"][0]["regions"][0]["parts"][0]["shape"]["bounds"] == [
        1.0,
        1.0,
        5.0,
        5.0,
    ]


def test_a_project_without_regions_loads_with_empty_tuples(tmp_path: Path) -> None:
    """Non-breaking extension, both ways: a save with no regions writes an
    explicit empty section, and a manifest with the key removed entirely —
    every project written before this section existed — loads identically
    rather than raising."""
    path = _save(tmp_path)
    assert _manifest(path)["regions"] == {
        "schema": REGIONS_SCHEMA,
        "classes": [],
        "sets": [],
    }
    assert load_project(path).region_sets == ()

    _rewrite_manifest(path, lambda m: m.pop("regions"))
    older = load_project(path)
    assert older.region_sets == ()
    assert older.region_classes == ()


def test_a_v1_workspace_migrates_with_no_regions(tmp_path: Path) -> None:
    """v1 predates the section entirely; migration must invent nothing —
    empty tuples, not a fabricated set (ADR 0002 §4)."""
    json_path, _ = write_v1_session(tmp_path / "legacy.json", [_image()], {})

    loaded = load_project(json_path)
    assert loaded.region_sets == ()
    assert loaded.region_classes == ()


# ── refusals ─────────────────────────────────────────────────────────


def test_duplicate_ids_are_refused_before_anything_is_written(tmp_path: Path) -> None:
    """An id is how a caller addresses a set after reopening, so a
    duplicate is a silent overwrite waiting to happen."""
    with pytest.raises(ProjectFormatError, match="duplicate region set id"):
        _save(tmp_path, region_sets=[_set("s1"), _set("s1")])
    with pytest.raises(ProjectFormatError, match="duplicate region id"):
        _save(tmp_path, region_sets=[RegionSet("s1", (_region("r1"), _region("r1")))])
    with pytest.raises(ProjectFormatError, match="duplicate region class id"):
        _save(tmp_path, region_classes=[RegionClass("a"), RegionClass("a")])
    assert not (tmp_path / "study.fvp").exists()


def test_a_malformed_region_names_itself_rather_than_leaking_a_value_error(
    tmp_path: Path,
) -> None:
    """`Shape.__post_init__` raises `ValueError` for the invariants JSON
    Schema cannot state — here, a region whose first part excludes, which
    subtracts from nothing. A `.fvp` is a file a stranger can send, so the
    reader must say WHICH region is wrong rather than letting a bare
    geometry complaint escape from two layers down."""
    path = _save(tmp_path, region_sets=[_set()])

    def flip(manifest):
        manifest["regions"]["sets"][0]["regions"][0]["parts"][0]["mode"] = "exclude"

    _rewrite_manifest(path, flip)
    with pytest.raises(ProjectFormatError, match=r"region 'r1' in set 's1'"):
        load_project(path)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda s: s["parts"][0]["shape"].update(outline=[[1, 1], [1, 3], [3, 3]]),
         "bounds"),
        (lambda s: s["parts"][0]["shape"].update(kind="blob"), "not one of"),
        (lambda s: s["parts"][0]["shape"].update(bounds=[1, 1, 3]), "too short"),
        (lambda s: s.update(parts=[]), "non-empty"),
        (lambda s: s.pop("id"), "required property"),
    ],
)
def test_the_schema_refuses_a_manifest_no_reader_could_trust(
    tmp_path: Path, mutate, match
) -> None:
    """`validate_manifest` runs on every load as well as before every save,
    so the schema — not a hand-written parser — is what rejects a bad
    section. The first case is the one worth naming: a shape carrying BOTH
    bounds and an outline is two contradictory geometries, and without the
    schema's discriminated variants one of them would be silently ignored
    at rasterization."""
    path = _save(tmp_path, region_sets=[_set()])
    _rewrite_manifest(path, lambda m: mutate(m["regions"]["sets"][0]["regions"][0]))
    with pytest.raises(ProjectFormatError, match=match):
        load_project(path)


# ── the server carry: session and route ──────────────────────────────
# The section is only as good as the path a real save takes through it.
# Everything above exercises `save_project`/`load_project` directly; these
# pin the two places that would silently DESTROY a user's regions instead
# of merely failing — the session that holds them between calls, and the
# save route that has to pass them back down.


def test_adopt_replaces_region_sets_and_a_merge_appends_and_dedupes() -> None:
    """Region sets are server-carried exactly like results and
    placeholders: a replacing load swaps them, an append load must not drop
    the open project's sets, and re-loading one file must not double them."""
    session = ProjectSession()
    a, b = _set("aaa"), _set("bbb")

    session.adopt(LoadedProject(region_sets=(a,)), Path("one.fvp"))
    assert [g.id for g in session.current().region_sets] == ["aaa"]

    session.adopt(LoadedProject(region_sets=(b,)), Path("two.fvp"))
    assert [g.id for g in session.current().region_sets] == ["bbb"]

    session.adopt(LoadedProject(region_sets=(a,)), Path("one.fvp"), merge=True)
    assert [g.id for g in session.current().region_sets] == ["bbb", "aaa"]

    session.adopt(LoadedProject(region_sets=(a,)), Path("one.fvp"), merge=True)
    assert [g.id for g in session.current().region_sets] == ["bbb", "aaa"]


def test_a_merge_dedupes_region_classes_by_id() -> None:
    """Two projects that both declare "substrate" describe one class, not
    two — a duplicated vocabulary would show the user the same label twice
    and make the registry grow on every append load."""
    session = ProjectSession()
    sub = RegionClass(id="substrate", label="Substrate")
    void = RegionClass(id="void")

    session.adopt(LoadedProject(region_classes=(sub,)), Path("one.fvp"))
    session.adopt(
        LoadedProject(region_classes=(sub, void)), Path("two.fvp"), merge=True
    )
    assert [c.id for c in session.current().region_classes] == ["substrate", "void"]


@pytest.fixture()
def client():
    store.clear()
    project.clear()
    yield TestClient(create_app())
    store.clear()
    project.clear()


@pytest.mark.api
def test_the_save_route_preserves_regions_the_client_never_sent_back(
    client: TestClient, tmp_path: Path
) -> None:
    """The data-loss trap, and the reason the section is server-carried:
    the browser posts only its own `client_state`, which says nothing about
    region sets. A save route that took regions from the client would write
    an empty section over the user's regions on the very next save — and
    every test above would still pass, because none of them goes through a
    route. This one does.
    """
    path = save_project(
        tmp_path / "study.fvp",
        [_image()],
        region_sets=[_set()],
        region_classes=[RegionClass(id="precipitate", label="Precipitate")],
    )

    loaded = client.post("/api/project/load", json={"path": str(path)})
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["project"]["n_region_sets"] == 1
    section = body["regions"]
    assert section["schema"] == REGIONS_SCHEMA
    assert [g["id"] for g in section["sets"]] == ["s1"]
    assert [c["label"] for c in section["classes"]] == ["Precipitate"]
    # the wire form IS the manifest form, so the browser and the .fvp
    # cannot drift into two spellings of one region
    assert section["sets"][0]["regions"][0]["parts"][0]["shape"]["kind"] == "rect"

    saved = client.post(
        "/api/project/save",
        json={
            "path": str(tmp_path / "resaved.fvp"),
            "client_state": body["client_state"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["n_region_sets"] == 1

    (group,) = load_project(tmp_path / "resaved.fvp").region_sets
    assert group.id == "s1"
    assert group.name == "grain boundaries"
    assert [r.id for r in group.regions] == ["r1"]
    assert same_shape(group.regions[0].parts[0].shape, _region().parts[0].shape)


# ── the schema number is load-bearing, so it is enforced ─────────────


def test_a_newer_regions_schema_is_refused_rather_than_reinterpreted(
    tmp_path: Path,
) -> None:
    """`schema` is the SOLE statement of the coordinate convention, so a
    reader that ignored it would parse a future build's geometry under
    this build's convention — and then rewrite it as schema 1 on the next
    save, destroying whatever the newer revision added. That is a silent
    downgrade exactly where the meaning of the coordinates may have
    changed, so opening fails instead."""
    path = _save(tmp_path, region_sets=[_set()])

    def to_v2(manifest):
        manifest["regions"]["schema"] = 2
        manifest["regions"]["sets"][0]["coordinate_origin"] = "centre"

    _rewrite_manifest(path, to_v2)
    with pytest.raises(ProjectFormatError, match="const|schema"):
        load_project(path)


def test_a_regions_section_must_declare_its_schema(tmp_path: Path) -> None:
    """Absent is not "assume 1": a section with no schema was written by
    something that did not agree to this convention, and guessing is the
    same mistake as accepting a higher number."""
    path = _save(tmp_path, region_sets=[_set()])
    _rewrite_manifest(path, lambda m: m["regions"].pop("schema"))
    with pytest.raises(ProjectFormatError, match="schema"):
        load_project(path)


@pytest.mark.parametrize("declared", [0, 2, 99, "1", None])
def test_load_regions_refuses_an_unsupported_schema_on_its_own(declared) -> None:
    """`load_regions` is public and reachable without `validate_manifest`,
    so it does not rely on the JSON Schema having run. `"1"` and `None` are
    in the sweep because a JSON-typed check that only compared magnitude
    would let a string or a null through."""
    with pytest.raises(ProjectFormatError, match="unsupported regions schema"):
        load_regions({"schema": declared, "sets": [], "classes": []})


def test_a_supported_schema_still_loads() -> None:
    """The refusal above must not be a blanket one — the positive case is
    what proves the check discriminates rather than just rejecting."""
    loaded = load_regions(
        {"schema": REGIONS_SCHEMA, "classes": [{"id": "a"}], "sets": []}
    )
    assert [c.id for c in loaded.classes] == ["a"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.update(schema=2), id="a-newer-schema"),
        pytest.param(lambda r: r.pop("schema"), id="no-schema-at-all"),
    ],
)
def test_the_json_schema_refuses_the_section_on_its_own(mutate) -> None:
    """The refusal is deliberately in two layers, and this proves the
    OUTER one. The tests above all reach the section through
    `load_project`, where `load_regions` rejects first — so removing the
    `required`/`const` from the JSON Schema leaves every one of them
    green, and the manifest contract would silently stop guaranteeing
    what the loader happens to enforce.

    `validate_manifest` is what a save runs before committing a container,
    so this is also what stops THIS build writing a section it could not
    read back.
    """
    manifest = {
        "format": "fermiviewer-project",
        "version": 2,
        "generation": "abc12345",
        "payload_mode": "light",
        "images": [],
        "regions": {"schema": REGIONS_SCHEMA, "classes": [], "sets": []},
    }
    mutate(manifest["regions"])
    with pytest.raises(ProjectFormatError, match="regions"):
        validate_manifest(manifest)


# ── metadata is JSON-safe, or the project cannot be saved ────────────


@pytest.mark.parametrize(
    ("label", "meta"),
    [
        ("numpy scalar", {"dose": np.float32(1.5)}),
        ("ndarray", {"pts": np.zeros(3)}),
        ("nan", {"drift": float("nan")}),
        ("inf", {"ratio": float("inf")}),
        ("nested numpy", {"run": {"gain": np.float64(2.0), "n": np.int32(7)}}),
    ],
)
@pytest.mark.parametrize("where", ["set", "region"])
def test_metadata_cannot_make_a_project_unsavable(tmp_path, label, meta, where) -> None:
    """`meta` is `dict[str, Any]` and is where a caller puts whatever it
    likes — which in this app means ordinary scientific metadata. A numpy
    value reaches `json.dumps` AFTER the manifest has validated, so it
    raises with the container half-decided and the user unable to save at
    all. A NaN is worse in a quieter way: `json.dumps` writes the bare
    token `NaN`, which every other JSON parser rejects, so the `.fvp`
    stops being portable while still looking fine here.
    """
    region = Region(id="r1", parts=(Part(rect(1, 1, 3, 3)),),
                    meta=meta if where == "region" else {})
    group = RegionSet("s1", (region,), meta=meta if where == "set" else {})

    path = _save(tmp_path, region_sets=[group])          # must not raise
    raw = zipfile.ZipFile(path).read("manifest.json").decode()
    assert "NaN" not in raw and "Infinity" not in raw
    json.loads(raw)                                       # strict parse
    load_project(path)


def test_finite_metadata_still_round_trips_untouched(tmp_path: Path) -> None:
    """The scrub must not be a blanket flattening — ordinary metadata has
    to survive, or the test above would pass on a `meta` that was simply
    thrown away."""
    meta = {"drawn_by": "paige", "pass": 2, "scale": 0.125, "tags": ["a", "b"]}
    loaded = load_project(
        _save(tmp_path, region_sets=[RegionSet("s1", (_region(),), meta=meta)])
    )
    assert loaded.region_sets[0].meta == meta


# ── duplicate ids are refused on LOAD too ────────────────────────────


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        pytest.param(
            lambda r: r["sets"].append(dict(r["sets"][0])),
            "duplicate region set id",
            id="two-sets-one-id",
        ),
        pytest.param(
            lambda r: r["sets"][0]["regions"].append(dict(r["sets"][0]["regions"][0])),
            "duplicate region id",
            id="two-regions-one-id",
        ),
        pytest.param(
            lambda r: r["classes"].extend([{"id": "a"}, {"id": "a"}]),
            "duplicate region class id",
            id="two-classes-one-id",
        ),
    ],
)
def test_duplicate_ids_are_refused_on_load_not_only_on_save(
    tmp_path: Path, mutate, match
) -> None:
    """The serializer already rejects these, but JSON Schema cannot express
    uniqueness by an object property — so before this, a hand-edited or
    externally produced project OPENED with ambiguous ids and only failed
    when the user tried to save it. That is the worst moment to find out:
    by then they have done work they cannot write down.
    """
    path = _save(tmp_path, region_sets=[_set()])
    _rewrite_manifest(path, lambda m: mutate(m["regions"]))
    with pytest.raises(ProjectFormatError, match=match):
        load_project(path)


# ── append-load must not silently drop a colliding set ───────────────


def _other_set(set_id: str = "s1") -> RegionSet:
    """Same id as `_set()`, deliberately different geometry — what a second
    project that also called its set "s1" looks like."""
    return RegionSet(
        id=set_id,
        name="voids",
        image_id="img2",
        regions=(Region(id="v1", parts=(Part(rect(6, 6, 7, 7)),)),),
    )


def test_an_append_load_keeps_a_colliding_set_instead_of_dropping_it() -> None:
    """Region set ids are the USER's, so two projects both naming a set
    "s1" is ordinary rather than a collision to resolve by deletion.
    Deduping by id alone — the rule images and results use — would append
    the second project's images while silently discarding its regions, and
    the next save would make that permanent.

    Renaming is safe where dropping is not: nothing references a set id
    yet, and a visible rename is recoverable where a silent deletion is
    not.
    """
    session = ProjectSession()
    session.adopt(LoadedProject(region_sets=(_set("s1"),)), Path("one.fvp"))
    session.adopt(
        LoadedProject(region_sets=(_other_set("s1"),)), Path("two.fvp"), merge=True
    )

    kept = session.current().region_sets
    assert [g.id for g in kept] == ["s1", "s1~2"]
    assert [g.name for g in kept] == ["grain boundaries", "voids"]
    # and the arriving geometry is intact, not the first set's
    assert [r.id for r in kept[1].regions] == ["v1"]


def test_re_adopting_the_same_file_still_does_not_double_a_set() -> None:
    """The behaviour the id-dedupe was there for, which the value compare
    must preserve — otherwise every re-load of one project would grow the
    session by another copy of its regions."""
    session = ProjectSession()
    session.adopt(LoadedProject(region_sets=(_set("s1"),)), Path("one.fvp"))
    for _ in range(3):
        session.adopt(
            LoadedProject(region_sets=(_set("s1"),)), Path("one.fvp"), merge=True
        )
    assert [g.id for g in session.current().region_sets] == ["s1"]


def test_a_third_colliding_set_gets_the_next_free_id() -> None:
    session = ProjectSession()
    session.adopt(LoadedProject(region_sets=(_set("s1"),)), Path("one.fvp"))
    for name in ("two", "three"):
        session.adopt(
            LoadedProject(region_sets=(replace(_other_set("s1"), name=name),)),
            Path(f"{name}.fvp"),
            merge=True,
        )
    assert [g.id for g in session.current().region_sets] == ["s1", "s1~2", "s1~3"]


def test_a_colliding_class_id_keeps_the_first_decoration() -> None:
    """Deliberately NOT the same rule as sets, and the asymmetry is the
    point: a class id is a shared VOCABULARY key, so two projects both
    saying "substrate" mean the same class differently decorated, and the
    id carries the meaning while the label and colour are presentation.
    A set id is an ADDRESS for distinct data, so a collision there is two
    things and both must be kept.

    Renaming a class would also break the `region_class` of every region
    in the arriving set, which renaming a set cannot do.
    """
    session = ProjectSession()
    first = RegionClass(id="substrate", label="Substrate", color="#111111")
    second = RegionClass(id="substrate", label="Base layer", color="#222222")

    session.adopt(LoadedProject(region_classes=(first,)), Path("one.fvp"))
    session.adopt(
        LoadedProject(region_classes=(second,)), Path("two.fvp"), merge=True
    )
    (only,) = session.current().region_classes
    assert (only.id, only.label, only.color) == ("substrate", "Substrate", "#111111")
