# Analysis Regions workspace

The **Analysis Regions** inspector card is the user-facing editor for the
canonical region section defined by [ADR 0006](adr/0006-project-regions-section.md).
It is intentionally separate from two older image annotations:

| Surface | Purpose | Coordinates | Persistence |
| --- | --- | --- | --- |
| Analysis Regions | Exact, reusable masks consumed by analyses | 0-based `[row, col]`, inclusive | Typed `regions` manifest section |
| Saved ROIs | Quick rectangle/ellipse bookmarks | normalized `[x, y]` | legacy opaque `ui_state.savedRois` |
| Region Measurements | Area readout and CSV for polygon/lasso annotations | normalized `[x, y]` | typed `measures` section |

Keeping these labels explicit prevents a visually similar annotation from
silently becoming an analysis mask with a different coordinate convention.
Legacy conversion is an explicit 4B flow, not an implicit reinterpretation.

## Information architecture

A project owns a class vocabulary and any number of region sets. Each set is
bound to one image and owns ordered regions. A region may contain:

- one or more included parts (disconnected islands);
- excluded parts that subtract from the accumulated mask;
- holes attached to an individual shape;
- a class id and free-form metadata.

The manager filters its set selector to the active image and reports how many
sets live on other images. It never drops or rewrites those off-image sets.
The selected set exposes naming, duplication, visibility and deletion. Region
rows expose the same core organization plus class assignment and a compact
geometry summary, for example `2 parts · 1 exclusion · 3 holes`.

Classes are project-wide because the same vocabulary should label regions on
different images consistently. Removing a class keeps every region and only
clears the removed assignment.

## Mutation and failure behavior

The browser edits a complete typed `ProjectRegions` value and publishes it
through `POST /api/region-sets/replace`. The server parses the whole document
into `calc.regions` geometry and validates duplicate ids before atomically
replacing the project session. The Zustand store adopts only the accepted
response. A 422 therefore leaves both the server and the visible browser state
unchanged; there is no partial region edit to repair.

Project saves still do not echo geometry in `client_state`. The server carries
the accepted workspace into every later `.fvp` save, matching results and
unavailable-image preservation.

## Converting to and from label maps

A segmentation produces a label map; correcting one by hand means it has to
become regions, be edited, and become a label map again. Two routes do that,
and `calc/region_convert.py` is the conversion itself.

`POST /api/region-sets/from-labels` traces a session label map into one region
per distinct non-zero value. A label keeps its identity when its pixels do
not touch — a disconnected label is one region with several parts, not several
regions — and holes attach to the outline that encloses them. The set comes
back in manifest form and is **not** added to the workspace: `/replace` stays
the single path that writes the live section, so the caller merges the set into
the document it already holds and publishes that.

`POST /api/region-sets/to-labels` is the return trip. It rasterizes a named set
into a label map sized to the given image and registers it as a derived session
image, tagged `region_source` so an edited map can be told from a segmenter's
own output.

By default each region keeps the label value it was traced from, so the loop
preserves a sparse map rather than renumbering it. That value rides in region
`meta` under `label_value` rather than being parsed back out of the id, because
an id is a name and a caller may rename a region. A region a user *drew* has no
source value and takes the smallest positive number no traced region claims.
`values` overrides all of this per region id, and must be a real JSON integer —
`true`, `"2"` and `2.0` are refused rather than coerced.

Label values are bounded by the registration format: a session map is float64,
which represents integers exactly only up to 2^53, so anything larger is
refused rather than silently rounded into a neighbouring label. **Both**
directions enforce that one range — `from-labels` on the values it reads and
`to-labels` on the map it produces — so every region the first hands out is one
the second will take back. An integer-typed label map is bounded on the same
values despite needing no conversion.

Calling `from-labels` is an assertion that the image *is* a label map. Nothing
in the values can confirm that: an ordinary uint8/uint16 micrograph is
whole-valued and real, so it converts into one region per distinct intensity.
The checks below reject what cannot be a label map, not what merely is not one,
and the UI offering the conversion owns the assertion.

Within that, the conversion is lossless in both directions and refuses rather
than guesses anywhere it cannot be:

* an image whose values are not whole numbers is not a label map, and tracing
  one would return a region per grey level;
* a label map must be real numeric or boolean. Complex is refused by dtype
  rather than by value, because `1+1j` is finite and equals its own rounding —
  only the cast to integers would notice, by discarding the imaginary part and
  calling the pixel label 1;
* two regions covering one pixel, sharing an id, or sharing a value are all
  refused, because a label map cannot hold either claim and any rule for
  picking a winner would be invisible in the array that came back;
* a set bound to another image cannot be written into this one's labels
  (ADR 0007 §6).

The price of lossless is size: an outline keeps a vertex per boundary step,
so 150 grains at 512×512 trace to roughly 32,000 vertices. `calc/contours.py`
is the simplifying tracer for the UI's draw assist and is deliberately not
what these routes use.

## Previewing scope before running anything

`POST /api/regions/preview` answers "how much will this analyse?" without
analysing it. Give it an `image_id` and either a `region_ref`
(`"set_id"` or `"set_id/region_id"`) or a frozen `roi` string; neither
previews the whole image, which is what an unscoped run reads and is the
thing worth comparing a region against.

It reports `pixel_count` — the pixels the region *selects*, which is also the
area in px² — alongside `image_pixels` and their `fraction`, the clamped
1-based `rect` with its `bbox_pixels`, and `exact_mask`, which says whether
the selection is narrower than that box.

Those are two different answers on purpose. ADR 0007 §9 splits them: a
reducing analysis (spectra, statistics) reads exactly the selected pixels,
while a neighbourhood-based one — a watershed basin, a texture feature, a
gradient — reads the bounding-box crop for context and only clips its
*labels* to the selection. So `pixel_count` is what may carry a result and
`bbox_pixels` is what informs it; neither alone is "what will be read". An irregular region is where
those differ: a 10×20 rect with a 4×4 bite is 184 pixels inside a 200-pixel
box, and a preview showing only the box would overstate the work by the size
of the hole.

`area_calibrated` is the physical area, or **null** when the image has no
pixel size — never the pixel count wearing an area's name, since the same
number would silently mean px² or nm². `unit` is the *length* unit, matching
`/regions/propose`, so the area is in `unit²`.

That area **assumes square pixels** (`n × pixel_size²`, from the second
spatial axis). On an anisotropic scan — 0.5 nm rows against 2.0 nm columns —
it is four times too large. Every consumer in the tree makes the same
assumption, so the preview agrees with the analyses it previews; correcting
it is roadmap item 5's per-axis calibration work, not something this endpoint
should do alone.

The preview resolves through the same `resolve_region` the analyses use, so
it inherits their refusals exactly: an empty selection, two scopes at once,
and a set drawn on another image are all rejected here as they would be at
run time. That is deliberate — a preview that disagreed with the run would
be worse than no preview.

## Selection and visibility

Selection and visibility are presentation, not scientific data. They persist
under `ui_state.regionUi` and do not alter the canonical shapes. Hidden regions
use an opaque key made from both set id and region id, because ADR 0006 only
requires region ids to be unique *inside their set*. Using a bare region id
would incorrectly hide same-named regions in unrelated sets.

Every project/workspace restore sanitizes this UI state against the canonical
section. Deleting a selected set or region immediately clears stale selection
and visibility keys after the server accepts the new section.

## Drawing and editing workflow

The workspace reuses the stage's mature annotation rails instead of adding a
second, subtly different vertex editor. **Polygon**, **Lasso**, **Rectangle**
and **Ellipse** in the Drawing source panel start those tools directly. The
selected drawing remains an annotation until the user chooses one of these
explicit conversions:

- **New region** creates a region whose first part includes the drawing.
- **Disconnected part** appends the drawing as another inclusion in the
  selected region.
- **Exclusion** appends it as a subtraction from the selected region.
- **Replace** replaces one ordered part from the selected drawing.

For a hole, draw an inner polygon or lasso and use its stage context menu's
**Mark as hole** command. The existing measure editor attaches the inner ring
to its host; conversion then copies the outer and every hole together.

Parts are displayed in their authored order because order changes the mask:
an inclusion after an exclusion can add pixels back. Rows can be reordered and
every part after the first can switch between Include and Exclude. The first
part is locked to Include, matching `calc.regions.Region`'s invariant.

**Edit on stage** copies a representable part back to the annotation rails.
After moving vertices, inserting/deleting vertices, simplifying a lasso or
editing holes, **Replace** publishes the selected drawing back into that part.
Polygon holes and plain rectangle/ellipse bounds round-trip exactly. A true
canonical circle or a bounded shape that itself carries polygon holes is not
offered for stage editing: the annotation model cannot represent either
without changing its rasterized mask, so refusing a lossy conversion is the
safe behavior.

The conversion is deliberately stated and tested once:

```text
annotation (x, y), normalized 0–1
    → canonical [row = y × height, col = x × width], 0-based float
```

The reverse divides column by width and row by height. No rounding, clamping
or 1-based offset is introduced; exact server rasterization remains the
authority for pixel membership.

## On-stage preview and refresh behavior

Visible analysis regions are drawn over their source image in their class
color. The selected region has a stronger boundary; inclusions use a light
fill and exclusions use a hatched, dashed treatment so compound masks remain
legible over both dark and light microscopy images. Set and region visibility
buttons affect only this presentation layer and never rewrite geometry.

The preview reads canonical row/column coordinates directly. Polygon holes
use SVG's even-odd fill rule. Rectangle and ellipse bounds extend half a pixel
around their inclusive endpoint centers to match the backend rasterizer's
pixel-footprint convention; circle bounds are true disc boundaries and receive
no expansion.

Region sets are carried by the live backend session even when the user opened
loose images rather than a project. Browser refresh reloads region sets in
parallel with the image list. This hydration is read-only. Until it succeeds,
the manager fails closed and offers a retry; whole-workspace replacement is
blocked so a transient GET failure cannot turn an empty client baseline into
deletion of server-carried regions.

Saved rectangle and ellipse bookmarks have a direct **Convert to analysis
region** action. Conversion creates an image-bound set when needed, records
the saved ROI id as provenance, and selects the new canonical region. Recall
the bookmark first only when its annotation geometry needs adjustment.

## Stacked delivery

- **4B-1:** typed transport, atomic server bridge, project/workspace restore.
- **4B-2:** region manager, set/class organization, selection and visibility.
- **4B-3:** precise stage drawing/editing and explicit conversion from legacy
  ROI/measure geometry, including holes, exclusions and disconnected parts.
- **4B-4:** mask previews, integration polish, accessibility and live QA.

Analysis endpoints do not consume the live section until 4C. When they do,
they must rasterize through `calc.regions.rasterize`; the manager never derives
a bounding box as a substitute for the authored mask.
