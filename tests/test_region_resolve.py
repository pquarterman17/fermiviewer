"""The shared region resolver — roadmap 4C-0.

`fermiviewer.region_resolve` is the single place a region reference (a
named region from the ADR 0006 workspace, the frozen ``"r1,c1,r2,c2"``
string, or nothing at all) becomes pixels. Every later 4C wave migrates
its analysis onto it, so a defect here is a defect in every consumer at
once.

## Where the expected answers come from

Not from the resolver, and not from `calc.region_mask.rasterize` either.
`selected_pixels` below builds the expected pixel SET from the definition
of an inclusive rectangle — a nested loop over the grid applying
``r0 <= r <= r1 and c0 <= c <= c1`` — so a test failing here means the
resolver disagrees with the written contract, not that two spellings of
the same implementation drifted apart. The 4A suite learned this the hard
way: `tests/test_regions.py`'s rect sweep sampled only shapes where the
implementation's own assumption held, and missed that a one-pixel-wide
rect returned two corners.

The legacy-parity tests take their expected answer from an even more
independent place: `calc.raster.region_sum_spectrum`, the pre-4C rectangle
path, run on the same cube. The roadmap asks each wave to compare
exact-mask results against the legacy rectangular path, and these are that
comparison for the resolver itself — if the resolver cannot reproduce the
old answer for a rectangle, no wave built on it can either.
"""

from __future__ import annotations

import numpy as np
import pytest

from fermiviewer.calc.raster import region_sum_spectrum
from fermiviewer.calc.regions import Part, Region, circle, polygon, rect
from fermiviewer.io.regions_model import RegionSet
from fermiviewer.project_session import project
from fermiviewer.region_resolve import (
    REFERENCE_FRAME,
    RegionReferenceError,
    resolve_region,
    resolve_region_params,
)

SHAPE = (8, 8)


# ── independent oracles ──────────────────────────────────────────────


def selected_pixels(r0: int, c0: int, r1: int, c1: int, shape=SHAPE) -> set:
    """Every (row, col) inside a 0-based INCLUSIVE rect, straight from the
    definition. Deliberately a loop and not array arithmetic: this is the
    statement the contract makes, written out."""
    return {
        (r, c)
        for r in range(shape[0])
        for c in range(shape[1])
        if r0 <= r <= r1 and c0 <= c <= c1
    }


def mask_pixels(mask: np.ndarray) -> set:
    """A boolean mask as the set of (row, col) it selects."""
    return {(int(r), int(c)) for r, c in zip(*np.nonzero(mask), strict=True)}


def resolved_pixels(resolved) -> set:
    """Every pixel a ResolvedRegion selects, read the way a CONSUMER would:
    the rect narrowed by the cropped mask. Goes through the public
    accessors rather than `.mask`, so it also exercises the ``None``
    contract that rectangle-only consumers depend on."""
    rows, cols = resolved.rect_slices()
    cropped = resolved.cropped_mask()
    return {
        (rows.start + r, cols.start + c)
        for r, c in zip(*np.nonzero(cropped), strict=True)
    }


def region_of(*parts: Part, region_id: str = "r1") -> Region:
    return Region(id=region_id, parts=parts)


def set_of(*regions: Region, set_id: str = "s1", image_id=None) -> RegionSet:
    return RegionSet(id=set_id, regions=regions, image_id=image_id)


def sets_with(*regions: Region, **kw) -> tuple[RegionSet, ...]:
    return (set_of(*regions, **kw),)


#: A plain set for the tests that are about the REFERENCE rather than
#: the geometry — what it points at is incidental to what they assert.
PLAIN = sets_with(region_of(Part(rect(0, 0, 3, 3))))


# ── the whole-image and roi paths keep the legacy behaviour ──────────


def test_no_reference_at_all_is_the_whole_image() -> None:
    got = resolve_region(SHAPE)
    assert got.rect == (1, 1, 8, 8)
    assert got.mask is None
    assert got.pixel_count == 64
    assert got.provenance["source"] == "whole-image"


@pytest.mark.parametrize(
    "roi, expected",
    [
        ("1,1,8,8", (1, 1, 8, 8)),
        ("2,3,5,6", (2, 3, 5, 6)),
        ("3,4,3,4", (3, 4, 3, 4)),  # one pixel
        ("1,1,1,8", (1, 1, 1, 8)),  # one row — 4A's degenerate case
        ("1,1,8,1", (1, 1, 8, 1)),  # one column
        ("0,0,99,99", (1, 1, 8, 8)),  # clamped to the image
        ("5,6,2,3", (2, 3, 5, 6)),  # corners in either order
    ],
)
def test_a_roi_string_resolves_to_its_clamped_rect(roi, expected) -> None:
    got = resolve_region(SHAPE, roi=roi)
    assert got.rect == expected
    assert got.mask is None, "a plain rectangle must not carry a mask"
    r1, c1, r2, c2 = expected
    assert got.pixel_count == (r2 - r1 + 1) * (c2 - c1 + 1)
    assert resolved_pixels(got) == selected_pixels(r1 - 1, c1 - 1, r2 - 1, c2 - 1)


def test_a_roi_that_misses_the_image_is_refused() -> None:
    with pytest.raises(ValueError):
        resolve_region((8, 8), roi="20,20,30,30")


def test_a_malformed_roi_is_refused_rather_than_read_as_whole_image() -> None:
    """`parse_roi_param`'s reason for existing: a typo must not silently
    widen the analysis to the entire image."""
    with pytest.raises(ValueError):
        resolve_region(SHAPE, roi="1,2,3")


# ── the region-set path ──────────────────────────────────────────────


def test_a_named_region_resolves_to_exactly_its_pixels() -> None:
    regions = sets_with(region_of(Part(rect(2, 3, 5, 6))))
    got = resolve_region(SHAPE, region="s1/r1", sets=regions)
    assert resolved_pixels(got) == selected_pixels(2, 3, 5, 6)
    assert got.rect == (3, 4, 6, 7), "0-based (2,3,5,6) is 1-based (3,4,6,7)"
    assert got.pixel_count == 16


def test_a_whole_set_reference_unions_its_regions() -> None:
    """Two disjoint blobs drawn as separate regions are one selection —
    which is what lets a two-piece specimen be analyzed at once."""
    regions = sets_with(
        region_of(Part(rect(0, 0, 1, 1)), region_id="a"),
        region_of(Part(rect(6, 6, 7, 7)), region_id="b"),
    )
    got = resolve_region(SHAPE, region="s1", sets=regions)
    assert resolved_pixels(got) == selected_pixels(0, 0, 1, 1) | selected_pixels(
        6, 6, 7, 7
    )
    assert got.pixel_count == 8
    assert got.rect == (1, 1, 8, 8), "the bbox spans both blobs"
    assert got.provenance["region_ids"] == ["a", "b"]


def test_a_degenerate_region_selects_its_line_of_pixels() -> None:
    """The 4A defect, at the resolver's own boundary: a one-pixel-wide
    rect is a line, not its two corners."""
    regions = sets_with(region_of(Part(rect(1, 1, 1, 6))))
    got = resolve_region(SHAPE, region="s1/r1", sets=regions)
    assert resolved_pixels(got) == selected_pixels(1, 1, 1, 6)
    assert got.pixel_count == 6


# ── the mask-is-None invariant, in both directions ───────────────────


def test_a_region_that_fills_its_box_carries_no_mask() -> None:
    """The invariant a rectangle-only consumer depends on. A filled
    rectangle drawn as a REGION is still a rectangle, so it must resolve
    the same way the roi string does."""
    regions = sets_with(region_of(Part(rect(2, 2, 4, 4))))
    got = resolve_region(SHAPE, region="s1/r1", sets=regions)
    assert got.mask is None
    assert got.is_exact is False
    assert got.provenance["exact_mask"] is False
    assert got.rect == resolve_region(SHAPE, roi="3,3,5,5").rect


@pytest.mark.parametrize(
    "part",
    [
        Part(circle(3.5, 3.5, 4.0)),
        Part(polygon([(1.0, 1.0), (1.0, 6.0), (6.0, 1.0)])),
        Part(rect(1, 1, 6, 6, holes=[[(2, 2), (2, 5), (5, 5), (5, 2)]])),
    ],
    ids=["circle", "triangle", "rect-with-hole"],
)
def test_a_region_narrower_than_its_box_carries_a_mask(part) -> None:
    """The other direction: anything that does NOT fill its bounding box
    must hand back a mask, or a consumer slicing the rect would silently
    analyze pixels the user did not select."""
    got = resolve_region(SHAPE, region="s1/r1", sets=sets_with(region_of(part)))
    assert got.mask is not None
    assert got.is_exact is True
    assert got.provenance["exact_mask"] is True
    r1, c1, r2, c2 = got.rect
    assert got.pixel_count < (r2 - r1 + 1) * (c2 - c1 + 1)


def test_the_mask_when_present_agrees_with_the_reported_pixel_count() -> None:
    got = resolve_region(
        SHAPE, region="s1/r1", sets=sets_with(region_of(Part(circle(3.5, 3.5, 4.0))))
    )
    assert got.mask is not None
    assert len(mask_pixels(got.mask)) == got.pixel_count
    assert len(resolved_pixels(got)) == got.pixel_count


def test_the_bounding_box_is_tight_around_the_selected_pixels() -> None:
    """A box wider than the selection would let a rect-only consumer read
    unselected pixels; a narrower one would clip the selection."""
    got = resolve_region(
        SHAPE, region="s1/r1", sets=sets_with(region_of(Part(circle(3.5, 3.5, 4.0))))
    )
    assert got.mask is not None
    pixels = mask_pixels(got.mask)
    rows = {r for r, _ in pixels}
    cols = {c for _, c in pixels}
    assert got.rect == (min(rows) + 1, min(cols) + 1, max(rows) + 1, max(cols) + 1)


def test_an_exclusion_shrinks_the_box_rather_than_leaving_it_stale() -> None:
    """`bounding_box` derives from the rasterized mask, not the outlines —
    so trimming the region's edge moves the box."""
    trimmed = region_of(
        Part(rect(1, 1, 6, 6)), Part(rect(1, 1, 2, 6), mode="exclude")
    )
    got = resolve_region(SHAPE, region="s1/r1", sets=sets_with(trimmed))
    assert resolved_pixels(got) == selected_pixels(3, 1, 6, 6)
    assert got.rect == (4, 2, 7, 7)


# ── parity with the legacy rectangular path ──────────────────────────


@pytest.mark.parametrize(
    "roi",
    ["1,1,8,8", "2,3,5,6", "3,4,3,4", "1,1,1,8", "1,1,8,1", "4,4,8,8"],
)
def test_the_resolver_sums_a_cube_exactly_as_the_legacy_path_does(roi) -> None:
    """The roadmap's "compare exact-mask results against the legacy
    rectangular path", for the resolver itself. `region_sum_spectrum` is
    the pre-4C rectangle path; both must agree bit for bit."""
    rng = np.random.default_rng(4)
    cube = rng.integers(0, 500, size=(8, 8, 5)).astype(np.uint16)
    r1, c1, r2, c2 = (int(p) for p in roi.split(","))
    legacy, legacy_rect = region_sum_spectrum(cube, r1, c1, r2, c2)

    got = resolve_region(SHAPE, roi=roi)
    rows, cols = got.rect_slices()
    exact = cube[rows, cols][got.cropped_mask()].sum(axis=0, dtype=np.float64)

    assert got.rect == legacy_rect
    assert np.array_equal(exact, legacy)


def test_a_rect_region_sums_a_cube_exactly_as_the_legacy_path_does() -> None:
    """The same parity, reached through a NAMED region instead of a roi
    string — the migration's actual claim: adopting the region contract
    does not change the number a rectangle produces."""
    rng = np.random.default_rng(5)
    cube = rng.integers(0, 500, size=(8, 8, 5)).astype(np.uint16)
    legacy, _ = region_sum_spectrum(cube, 3, 4, 6, 7)

    got = resolve_region(
        SHAPE, region="s1/r1", sets=sets_with(region_of(Part(rect(2, 3, 5, 6))))
    )
    rows, cols = got.rect_slices()
    exact = cube[rows, cols][got.cropped_mask()].sum(axis=0, dtype=np.float64)
    assert np.array_equal(exact, legacy)


def test_an_exact_mask_sums_less_than_its_bounding_rectangle() -> None:
    """The reason 4C exists. A non-rectangular region must NOT give the
    legacy rectangle's answer — if it did, the exact mask would be
    decorative. Uses a strictly-positive cube so "fewer pixels" is
    guaranteed to mean "smaller sum"."""
    cube = np.ones((8, 8, 3), dtype=np.uint16)
    got = resolve_region(
        SHAPE, region="s1/r1", sets=sets_with(region_of(Part(circle(3.5, 3.5, 4.0))))
    )
    rows, cols = got.rect_slices()
    exact = cube[rows, cols][got.cropped_mask()].sum(axis=0, dtype=np.float64)
    legacy, _ = region_sum_spectrum(cube, *got.rect)

    assert np.all(exact < legacy)
    assert np.all(exact == got.pixel_count)


def test_cropped_mask_matches_the_rect_slice_shape() -> None:
    """A consumer slices its data to `rect` and masks with `cropped_mask`;
    a shape disagreement would be an IndexError at every call site."""
    for kwargs in (
        {"roi": "2,3,5,6"},
        {"region": "s1/r1", "sets": sets_with(region_of(Part(circle(3.5, 3.5, 4.0))))},
    ):
        got = resolve_region(SHAPE, **kwargs)
        rows, cols = got.rect_slices()
        data = np.zeros(SHAPE)[rows, cols]
        assert got.cropped_mask().shape == data.shape


# ── refusals ─────────────────────────────────────────────────────────


def test_giving_both_a_region_and_a_roi_is_refused() -> None:
    """Two different scopes in one call is a caller bug; honouring either
    one silently would hide it."""
    with pytest.raises(RegionReferenceError, match="not both"):
        resolve_region(SHAPE, region="s1/r1", roi="1,1,4,4", sets=PLAIN)


def test_an_unknown_set_names_what_is_available() -> None:
    with pytest.raises(RegionReferenceError, match="unknown region set 'nope'") as err:
        resolve_region(SHAPE, region="nope/r1", sets=PLAIN)
    assert "'s1'" in str(err.value)


def test_an_unknown_region_names_what_is_available() -> None:
    with pytest.raises(RegionReferenceError, match="unknown region 'nope'") as err:
        resolve_region(SHAPE, region="s1/nope", sets=PLAIN)
    assert "'r1'" in str(err.value)


def test_an_empty_set_is_refused_rather_than_resolving_to_nothing() -> None:
    with pytest.raises(RegionReferenceError, match="no regions"):
        resolve_region(SHAPE, region="s1", sets=(set_of(),))


def test_a_region_entirely_off_the_image_is_refused() -> None:
    """`bounding_box` refuses an empty selection rather than widening to
    the whole image; the resolver must not soften that into a silent
    whole-image analysis."""
    off = sets_with(region_of(Part(rect(20, 20, 30, 30))))
    with pytest.raises(RegionReferenceError, match="selects no pixels"):
        resolve_region(SHAPE, region="s1/r1", sets=off)


@pytest.mark.parametrize("reference", ["s1/", "/r1", "/"])
def test_a_half_empty_reference_is_refused(reference) -> None:
    """An id cannot be empty, so no split of these names anything; they can
    only be a set with that literal id, and none exists here."""
    with pytest.raises(RegionReferenceError, match="unknown region set"):
        resolve_region(SHAPE, region=reference, sets=PLAIN)


def test_a_set_literally_named_with_a_trailing_slash_resolves() -> None:
    """The flip side: `"s1/"` is refused above only because no such set
    exists. The whole string is always a candidate on its own, so a set
    that really is named that way is reachable rather than unaddressable."""
    odd = sets_with(region_of(Part(rect(0, 0, 3, 3))), set_id="s1/")
    assert resolve_region(SHAPE, region="s1/", sets=odd).provenance["set_id"] == "s1/"


# ── slashes in ids ───────────────────────────────────────────────────
#
# The schema constrains set and region ids only to be non-empty strings
# (`fvp-v2.schema.json`), so a slash is ordinary data on EITHER side of a
# reference. Splitting on one particular separator privileges one side and
# makes the other unreachable, which is what these pin down.


def test_a_set_id_containing_a_slash_resolves() -> None:
    odd = sets_with(region_of(Part(rect(0, 0, 3, 3))), set_id="a/b")
    got = resolve_region(SHAPE, region="a/b/r1", sets=odd)
    assert got.provenance["set_id"] == "a/b"
    assert got.provenance["region_ids"] == ["r1"]


def test_a_region_id_containing_a_slash_resolves() -> None:
    """The case a last-separator split makes permanently unreachable: it
    would look for a set called `"s1/r"` and report it as unknown."""
    odd = sets_with(region_of(Part(rect(0, 0, 3, 3)), region_id="r/1"))
    got = resolve_region(SHAPE, region="s1/r/1", sets=odd)
    assert got.provenance["set_id"] == "s1"
    assert got.provenance["region_ids"] == ["r/1"]


def test_a_reference_resolves_when_only_the_region_side_reading_exists() -> None:
    """`"a/b/r1"` with a set `"a"` holding a region `"b/r1"` has exactly one
    valid reading, so it must resolve rather than fail on the other one."""
    odd = (set_of(region_of(Part(rect(0, 0, 3, 3)), region_id="b/r1"), set_id="a"),)
    got = resolve_region(SHAPE, region="a/b/r1", sets=odd)
    assert got.provenance["set_id"] == "a"
    assert got.provenance["region_ids"] == ["b/r1"]


def test_a_reference_that_names_two_existing_targets_is_refused() -> None:
    """The silent-wrong-answer case. With a set `"a/b"` AND a set `"a"`
    holding `"b/r1"`, `"a/b/r1"` genuinely means two different selections;
    answering with either would report a number for a region the caller may
    not have asked for."""
    both = (
        set_of(region_of(Part(rect(0, 0, 3, 3))), set_id="a/b"),
        set_of(region_of(Part(rect(5, 5, 7, 7)), region_id="b/r1"), set_id="a"),
    )
    with pytest.raises(RegionReferenceError, match="ambiguous") as err:
        resolve_region(SHAPE, region="a/b/r1", sets=both)
    message = str(err.value)
    assert "'a/b'" in message and "'b/r1'" in message, "names both readings"


def test_duplicate_set_ids_resolve_to_the_first_not_the_last() -> None:
    """`load_regions` enforces id uniqueness, so duplicates reach here only
    from a direct caller — but the resolver still has to pick one, and it
    picks the first, matching the linear scan it replaced. Untested, that
    is a claim in a comment rather than a behaviour."""
    dupes = (
        set_of(region_of(Part(rect(0, 0, 3, 3))), set_id="s1"),
        set_of(region_of(Part(rect(5, 5, 7, 7))), set_id="s1"),
    )
    got = resolve_region(SHAPE, region="s1/r1", sets=dupes)
    assert resolved_pixels(got) == selected_pixels(0, 0, 3, 3)


def test_the_two_readings_would_have_selected_different_pixels() -> None:
    """Why the refusal earns its keep: resolved separately, the two readings
    of the same string disagree — so silently picking one is a wrong answer,
    not merely an arbitrary one."""
    left = (set_of(region_of(Part(rect(0, 0, 3, 3))), set_id="a/b"),)
    right = (set_of(region_of(Part(rect(5, 5, 7, 7)), region_id="b/r1"), set_id="a"),)
    a = resolve_region(SHAPE, region="a/b/r1", sets=left)
    b = resolve_region(SHAPE, region="a/b/r1", sets=right)
    assert resolved_pixels(a) == selected_pixels(0, 0, 3, 3)
    assert resolved_pixels(b) == selected_pixels(5, 5, 7, 7)
    assert resolved_pixels(a) != resolved_pixels(b)


# ── the image binding ────────────────────────────────────────────────


def test_a_region_drawn_on_another_image_is_refused() -> None:
    """Applying a region drawn on image A to image B would report numbers
    from the wrong specimen."""
    bound = sets_with(region_of(Part(rect(0, 0, 3, 3))), image_id="img1")
    with pytest.raises(RegionReferenceError, match="drawn on image"):
        resolve_region(SHAPE, region="s1/r1", sets=bound, image_id="img2")


def test_a_matching_image_id_resolves() -> None:
    bound = sets_with(region_of(Part(rect(0, 0, 3, 3))), image_id="img1")
    got = resolve_region(SHAPE, region="s1/r1", sets=bound, image_id="img1")
    assert got.provenance["image_id"] == "img1"


@pytest.mark.parametrize(
    "set_image, asked", [(None, "img2"), ("img1", None), (None, None)]
)
def test_an_unbound_side_makes_no_claim_to_contradict(set_image, asked) -> None:
    """Only a mismatch between two KNOWN images is an error: a set with no
    `image_id` is unbound by design, and a caller that passes none is not
    claiming anything."""
    sets = sets_with(region_of(Part(rect(0, 0, 3, 3))), image_id=set_image)
    assert resolve_region(SHAPE, region="s1/r1", sets=sets, image_id=asked).pixel_count == 16


# ── provenance ───────────────────────────────────────────────────────


def test_provenance_names_the_frame_structurally_not_as_prose() -> None:
    """The repo's free-text `convention` field carries at least ten
    incompatible kinds of claim; the resolver must not add an eleventh."""
    got = resolve_region(SHAPE, roi="2,3,5,6")
    assert got.provenance["frame"] == {
        "axis_order": "row-col",
        "index_base": 1,
        "bounds": "inclusive",
        "origin": "top-left",
    }
    assert "convention" not in got.provenance


def test_provenance_rect_agrees_with_the_resolved_rect() -> None:
    for kwargs in (
        {"roi": "2,3,5,6"},
        {"region": "s1/r1", "sets": sets_with(region_of(Part(circle(3.5, 3.5, 4.0))))},
    ):
        got = resolve_region(SHAPE, **kwargs)
        assert got.provenance["rect"] == list(got.rect)
        assert got.provenance["exact_mask"] is (got.mask is not None)


def test_mutating_returned_provenance_cannot_corrupt_the_shared_frame() -> None:
    """`REFERENCE_FRAME` is module-level; handing out the same dict would
    let one consumer's edit rewrite the frame for every later call."""
    got = resolve_region(SHAPE, roi="1,1,4,4")
    got.provenance["frame"]["index_base"] = 99
    assert REFERENCE_FRAME["index_base"] == 1
    assert resolve_region(SHAPE, roi="1,1,4,4").provenance["frame"]["index_base"] == 1


# ── the session-bound wrapper ────────────────────────────────────────


@pytest.fixture()
def clean_project():
    project.clear()
    yield project
    project.clear()


def test_the_params_wrapper_reads_the_session_region_sets(clean_project) -> None:
    clean_project.replace_regions(sets_with(region_of(Part(rect(2, 3, 5, 6)))), ())
    got = resolve_region_params(SHAPE, {"region": "s1/r1", "roi": ""})
    assert resolved_pixels(got) == selected_pixels(2, 3, 5, 6)


def test_the_params_wrapper_falls_back_to_the_roi_param(clean_project) -> None:
    got = resolve_region_params(SHAPE, {"region": "", "roi": "2,3,5,6"})
    assert got.rect == (2, 3, 5, 6)
    assert got.mask is None


def test_the_params_wrapper_treats_absent_params_as_the_whole_image(
    clean_project,
) -> None:
    """An op that has not declared a `region` param must keep working."""
    got = resolve_region_params(SHAPE, {})
    assert got.rect == (1, 1, 8, 8)
    assert got.provenance["source"] == "whole-image"
