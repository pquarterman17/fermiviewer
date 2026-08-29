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

## Stacked delivery

- **4B-1:** typed transport, atomic server bridge, project/workspace restore.
- **4B-2:** region manager, set/class organization, selection and visibility.
- **4B-3:** precise stage drawing/editing and explicit conversion from legacy
  ROI/measure geometry, including holes, exclusions and disconnected parts.
- **4B-4:** mask previews, integration polish, accessibility and live QA.

Analysis endpoints do not consume the live section until 4C. When they do,
they must rasterize through `calc.regions.rasterize`; the manager never derives
a bounding box as a substitute for the authored mask.
