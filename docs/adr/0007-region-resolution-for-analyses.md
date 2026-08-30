# ADR 0007 — One resolver turns a region reference into pixels, and reports a rectangle beside the mask

**Status:** Accepted
**Date:** 2026-08-30
**Module:** `src/fermiviewer/region_resolve.py`
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 4 (stack item 4C, prerequisite for waves 1–5)
**Builds on:** ADR 0005 (operation-result conventions), ADR 0006 (project regions section)

## Context

ADR 0006 gave the app named region sets that survive a reopen, and 4A gave
it exact rasterization. Nothing consumes either. Item 4's fourth box —
"make spectrum integration, statistics, segmentation, particles, grains,
layers, and batch recipes consume the same contract" — is the migration,
and it touches every analysis in the repo.

Today each consumer interprets its own scope:

* The op catalogues parse the frozen `"r1,c1,r2,c2"` string through
  `ops/_parsing.parse_roi_param`, which hard-errors on a typo rather than
  falling back to the whole image.
* `routes/images.py` bypasses that entirely, taking loose
  `row0/col0/row1/col1` query params into `calc.raster.region_sum_spectrum`.
* `calc/roi.py` owns the clamp and embed rules, 1-based inclusive.
* None of them can name a region from the ADR 0006 workspace at all.

Migrating them one at a time, each deciding independently what an id
means, which frame its numbers are in, and what to do when a region is
empty or was drawn on a different image, would reproduce exactly the
divergence ADR 0003 recorded for rasters and 4A recorded for ROI
spellings — nine dialects, arrived at one reasonable local decision at a
time.

A second constraint comes from the existing metadata. The repo's
`"convention"` field is free text appearing at 16 sites with at least ten
mutually incompatible kinds of claim: coordinate frames
(`"(row, col), 1-based"`, `"normalized (x, y) in [0, 1]"`), label
encodings (`"0 = background; values are grain labels"`), and value
semantics (`"1 = defect-line pixel"`, `"null = invalid pixel"`). A
consumer holding one cannot tell which of the three it has.

## Decision

### 1. One resolver, at the app layer

`region_resolve.resolve_region` is the single place a region reference
becomes pixels. It accepts a named reference (`"set_id"` or
`"set_id/region_id"`), the frozen `roi` string, or nothing (the whole
image), and returns a `ResolvedRegion`.

It lives at the top level rather than in `calc/`, for the same reason as
`result_capture.py`: resolving an id needs the server-carried session,
which the pure layers may not import. The geometry stays pure — the
rasterization is `calc.region_mask`'s and is not duplicated.

### 2. Every result carries a rectangle, so migration is gradual

`ResolvedRegion.rect` is always present, as the 1-based inclusive
`RectRoi` every bbox-shaped analysis in the repo already speaks. A
consumer can therefore adopt the resolver without changing anything
downstream, which is what makes "preserve existing APIs" achievable
rather than aspirational.

### 3. `mask is None` means "the selection IS its bounding box"

This is the load-bearing invariant. `mask` is `None` exactly when every
pixel of `rect` is selected, and an array otherwise.

The alternative — always returning a mask — was rejected because it makes
adoption *unsafe in the quiet direction*. A consumer that slices `rect`
and ignores the mask would be silently wrong for every non-rectangular
region, and nothing about its code would look wrong. Under this
invariant, that same consumer is exactly correct whenever `mask is None`,
and the field it is ignoring is precisely the signal that it must not.

It also keeps the fast path fast: a rectangle stays a slice, so adopting
the resolver never forces a multi-gigabyte cube through a boolean mask
that would select all of it anyway.

`cropped_mask()` is the counterpart for consumers that already slice to
the ROI: it always returns an array of the slice's shape, all-True for a
plain rectangle, so they need not branch on `None` themselves.

### 4. Provenance names the frame structurally

`ResolvedRegion.provenance` carries a typed `frame`
(`axis_order`, `index_base`, `bounds`, `origin`) rather than a
`convention` string. Emitting one more free-text string would end 4C with
an eleventh dialect rather than one fewer. The frame describes `rect`
only: `mask` is a NumPy array and is 0-based by construction, so the two
are never reported under one label.

A fresh `dict` is handed out per call — the module-level `REFERENCE_FRAME`
is shared, and returning it directly would let one consumer's edit rewrite
the frame for every later call.

### 5. Ambiguity and emptiness are refused, not resolved

* Passing **both** a `region` and a `roi` raises. A caller sending two
  different scopes has a bug; a precedence rule would hide it.
* A reference selecting **no pixels** raises, matching
  `region_mask.bounding_box`. Widening to the whole image would turn a
  mis-drawn region into a silent full-image analysis.
* An **empty set** raises rather than resolving to an empty union.
* A **half-empty reference** (`"s1/"`) raises unless a set is literally
  named that way: an id cannot be empty, so no split of it names anything.

`RegionReferenceError` subclasses `ValueError` so the catalogues' existing
`except (ValueError, TypeError)` handlers map it to their 422 without each
one learning a new exception type.

### 5a. A reference with slashes is disambiguated, never guessed

`fvp-v2.schema.json` constrains set and region ids only to be non-empty
strings, so a slash is ordinary data and can appear on **either** side of
a `"set_id/region_id"` reference. The reference is therefore ambiguous in
general, and choosing a separator is not a fix — it only decides which
side is silently crippled. Splitting on the last separator (the first
implementation) privileges the set id and leaves a region id containing a
slash permanently unreachable, reported as an unknown set; splitting on
the first does the reverse.

So `_candidate_parses` offers every split, and `_resolve_reference` keeps
only the readings that name something that exists:

* exactly one resolves → use it, which makes a slash on either side work;
* none resolve → the existing unknown-set / unknown-region errors;
* **more than one resolves → refuse as ambiguous**, naming both readings.

The refusal is the point. A set `"a/b"` alongside a set `"a"` holding a
region `"b/r1"` makes `"a/b/r1"` genuinely mean two different selections
covering different pixels, so answering with either is a wrong answer
rather than an arbitrary one. A refusal the user fixes by renaming costs
less than a number silently computed over the wrong region.

### 6. A region drawn on another image is refused

Checked only when both the set and the caller name an image. A set
without an `image_id` is unbound by design (ADR 0006), and a caller that
passes none is not claiming anything to contradict. Where both are known,
a mismatch would report numbers from the wrong specimen, so it is an
error rather than a warning.

### 7. A whole-set reference unions its regions

Several regions drawn separately are one selection, which is what lets a
two-piece specimen be analyzed at once — the same reasoning that makes
disjoint `include` parts one region in 4A.

### 8. An op takes GEOMETRY; only a caller may take a name

`ops/registry.py` already draws this line for datasets: auxiliary inputs
arrive already-resolved because "the caller owns the session store, so the
pure layer never looks an id up". A region reference is an id, so the same
line applies — and `tests/test_repo_integrity.py`'s pure-layer guard would
NOT catch a breach, since `FORBIDDEN_IN_PURE` names the server stack, not
session coupling.

So `ops/_region_param.REGION_PARAM` carries the canonical geometry inline,
as an ordinary list-shaped `OpParam` validated by the same machinery as
every other parameter. `run()` does not change.

That is the whole mechanism, not a stopgap. A recipe runner owns the
session, so **naming is a caller concern**: the runner resolves a symbolic
reference and substitutes the resolved geometry into this param before
dispatch. The op still never sees an id, and the recorded params still
carry the resolved values ADR 0005 requires — so a result replays
identically on a machine with no project at all.

A dataset cannot work this way, which is why `inputs` is a separate
channel: an auxiliary image is large and not JSON. Geometry is small and
JSON-native, so it belongs in params. The asymmetry is a consequence of
what the payload is, not an inconsistency.

`calc.region_mask.mask_and_rect` holds §3's `mask is None` invariant, now
shared by the named path and the geometry param, so the rule has one
definition rather than one per consumer.

## Consequences

* Each 4C wave adopts a region by declaring a `region` param and calling
  the resolver. It gains exact masks, id resolution, image binding and
  provenance at once, and none of it is re-decided per consumer.
* Consumers that cannot yet mask still improve: they get id resolution
  and a correct bounding box, and the `mask is None` invariant tells them
  when the box is the whole truth.
* The resolver is a chokepoint, so a defect in it is a defect everywhere.
  That is the trade being made deliberately, and it is why the suite is
  mutation-checked rather than merely green.
* `"convention"` is not removed from existing outputs by this ADR. The
  resolver simply declines to add to it; collapsing the existing 16 sites
  is separate work.

## Verification

`tests/test_region_resolve.py`. Expectations come from outside the code
under test: `selected_pixels` builds the expected pixel set from the
written definition of an inclusive rectangle rather than from `rasterize`,
and the parity tests take their expected answer from
`calc.raster.region_sum_spectrum`, the pre-4C rectangle path, so the
roadmap's "compare exact-mask results against the legacy rectangular
path" is asserted for the resolver itself in both directions: a rectangle
must reproduce the legacy sum exactly, and a non-rectangular region must
*not* — otherwise the exact mask would be decorative.

The suite is mutation-checked. Twenty-two deliberate mutants each turn it
red: inverting the `mask is None` invariant in both directions,
off-by-ones in the bbox and the 1-based conversion, replacing the region
union with last-wins, removing each refusal individually, and sharing the
frame dict. The slash handling is covered in both directions — reverting
to either a last-separator or a first-separator split fails, as does
accepting the ambiguous reference instead of refusing it, dropping the
whole-string candidate, admitting empty halves as splits, or letting a
duplicate set id resolve to the last rather than the first.
