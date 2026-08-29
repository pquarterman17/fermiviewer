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
use SVG's even-odd fill rule, and bounded shapes extend half a pixel around
their inclusive endpoint centers to match the backend rasterizer's pixel
footprint convention.

Region sets are carried by the live backend session even when the user opened
loose images rather than a project. Browser refresh reloads region sets in
parallel with the image list. This hydration is read-only: it does not issue a
replace request or accidentally rewrite the workspace during startup.

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
