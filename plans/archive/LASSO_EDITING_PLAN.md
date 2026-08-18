# Lasso Editing

Fixes the lasso-measure adjustment experience, driven by an owner report
with a screenshot (2026-08-16): a hand-traced lasso around a ~circular
particle produced hundreds of vertices rendered as a "fur" of bar-glyph
handles, and every attempted vertex drag produced a needle-thin spike
instead of a reshape — one vertex among ~300 spaced 2px apart cannot
move a curve; its planted neighbours turn the drag into a spike.

Root cause (verified in code): `lassoSimplifyPx` is mislabeled — it is a
capture STEP filter (`appendLassoPoint` drops points closer than the
pref to the previous point), not simplification. `finishLasso` stores
the raw filtered stroke. Meanwhile the backend already runs true
Douglas–Peucker with an explicit "manageable for hand-correction" target
(`calc/contours.py::_simplify`, 2px/200-vertex) for detected regions —
hand-drawn lassos are the one path that never gets it.

**Status:** COMPLETE 2026-08-16, same day — all five items shipped in
three waves exactly as planned (A+D parallel, B+C parallel, E), every
item on its assigned model tier (4× sonnet, 1× haiku; fable wrote zero
implementation). MeasureOverlay GRADUATED off the legacy-cap list
entirely (533→472, pin removed per the store/viewer.ts idiom) rather
than merely shrinking. Two spec corrections surfaced by implementers and
absorbed: stored Measure.pts are normalized [0,1] (item C round-trips
through image px — the plan's literal formula would have been a units
bug), and polygon/lasso labels are pure render-derived functions of pts
(no async refresh path exists to fire). Measured headline: a 600-point
traced circle closes to 16 vertices at 2.55% area drift.
**Parent:** MAIN_PLAN.md
**Created:** 2026-08-16

---

## Conventions (normative — pre-decided, do not re-decide)

1. **The stored points ARE the measurement.** Simplification always
   mutates the stored `pts` through the normal measure-update path,
   never display-only — a rendered shape that disagrees with the
   measured area is the silent-divergence bug class this repo keeps
   fighting. Area labels must refresh through the existing
   post-edit-analysis path.
2. **Spike preservation is a feature, not a bug.** Douglas–Peucker
   keeps any deviation > ε. A deliberate spike survives simplification
   (as ~3 vertices); removing it is the DELETE affordance's job. Tests
   pin this.
3. **ε semantics are SCREEN pixels**, converted to image space by the
   zoom at the moment of application (`pref / view.z`) — the
   "consistent at any zoom" principle already documented in
   `regionCapture.ts`. Retroactive simplify uses the CURRENT zoom, so
   zooming in first gives gentler simplification; the menu title says
   so.
4. **Capture stays fine, simplify at close.** `appendLassoPoint`'s step
   filter becomes a FIXED 1 screen-px (fidelity floor for the RDP
   input); the `lassoSimplifyPx` pref drives ONLY the close-time
   simplification — after which the pref finally does what its name
   says. `MAX_LASSO_POINTS` (2000) stays as the hard cap.
5. **Lasso only at capture.** Click-placed polygons are not simplified
   at close — the user placed each vertex deliberately. Retroactive
   Simplify (user-invoked) applies to both lasso and polygon kinds.
6. **Editing gestures preserve existing muscle memory.** Plain drag on
   a measure body still translates; plain drag on a handle still moves
   that vertex. New gestures are additive: alt+drag on an EDGE inserts
   a vertex at the grab point and drags it in the same gesture;
   "Delete vertex" joins the existing right-click measure context menu
   (the mark-as-hole idiom). Delete is disabled at ≤ 3 vertices — a
   polygon must stay a polygon.
7. **Handle glyphs:** polygon/lasso vertices render as small circles
   (constant screen size, like all handles); the perpendicular-bar
   `EndpointGlyph` remains for line/arrow/angle endpoints, where its
   direction cue is meaningful. Handle VISIBILITY semantics are
   unchanged in this campaign (a selected-only policy is a possible
   follow-up, deliberately out of scope — it would change behaviour for
   every measure kind).
8. **Ratchet:** `MeasureOverlay.tsx` is pinned at 562
   (`tests/test_repo_integrity.py:48`) and currently 533 lines. The
   extraction item must land MeasureOverlay meaningfully below its
   current size and LOWER the pin to the new size in the same commit —
   pins only move down.

## Frozen contract

```ts
// frontend/src/lib/simplifyRing.ts  (new, pure — no component imports)
/** Douglas–Peucker for a CLOSED ring. epsilon in IMAGE px (caller
 *  converts from screen px). Anchors: the two mutually-farthest ring
 *  points (found from the extremes), each half simplified
 *  independently, halves rejoined. Result always has >= 3 vertices;
 *  if simplification would collapse below 3, the ORIGINAL ring is
 *  returned unchanged (mirrors calc/contours.py::_simplify's
 *  degenerate fallback). epsilon <= 0 returns the input unchanged. */
export function simplifyRing(
  pts: { x: number; y: number }[],
  epsilon: number,
): { x: number; y: number }[];
```

Consumers: `finishLasso` (Wave 2, item B), the "Simplify outline"
context-menu action (Wave 2, item C). Neither re-implements any part of
the algorithm.

## Items, ownership, and model assignment

Cheapest safe model per item; fable does zero implementation.

| Item | Scope (owned files) | Model | Why this tier |
|---|---|---|---|
| **A. `simplifyRing` library** | `lib/simplifyRing.ts` (new) + test | sonnet | Closed-ring anchoring and degenerate fallbacks are easy to get subtly wrong; mutation-testing discipline required |
| **D. Handle extraction + vertex edit** | `Stage/MeasureOverlay.tsx`, new `Stage/MeasureVertexLayer.tsx` (or similar), `test_repo_integrity.py` pin, colocated tests; `store/measures` actions if vertex insert/delete need them | sonnet | Touches a pinned-ratchet file and gesture code; the riskiest item |
| **B. Capture wiring** | `Stage/regionCapture.ts`, `Stage/useStagePointers.ts` (441/500), `overlays/PrefsWindow.tsx` label, tests | sonnet | Small diff but it changes what gets STORED as a measurement — Convention 1 territory |
| **C. Retroactive "Simplify outline"** | context-menu addition in the post-D overlay/extracted layer + tests | sonnet | Store-update + undo + area-refresh plumbing |
| **E. Round handles for ring vertices** | the extracted vertex layer only + test | **haiku** | Genuinely mechanical after D: swap glyph component for two measure kinds, per Convention 7 |
| Orchestration, merges, gates, PR, critical review | — | fable | The only fable-necessary work |

## Waves (successive, parallel within a wave)

- **Wave 1 (parallel):** A + D — file-disjoint.
- **Wave 2 (parallel, after Wave-1 merge):** B + C — B owns capture
  files, C owns the (now-extracted) menu/vertex layer; disjoint.
- **Wave 3:** E (haiku) on the extracted layer.
- Integrator gates between every merge: scoped tests + `tsc`, full
  frontend suite at wave boundaries; backend untouched throughout
  (verify empty diff, backend gate stands from the released tree).

## Verification requirements (all items)

- Every behaviour pinned by a test seen RED first (mutation-verified);
  agents report the mutation per test.
- A-specific pins: collinear-point removal; spike (> ε) preservation;
  ≥3-vertex guarantee incl. the return-original fallback; ε=0
  passthrough; area drift of a dense synthetic circle at ε=2 bounded
  (|ΔA|/A small, stated in the test).
- B-specific pins: a dense synthetic lasso stroke closes to a small
  vertex count (assert the STORE, not the render); polygon tool
  untouched; step filter is 1px fixed; pref drives ε only.
- C-specific pins: undo restores the pre-simplify pts; area label
  refresh fires; menu title carries the zoom note (Convention 3).
- D-specific pins: alt+edge-drag inserts at grab point and drags in one
  gesture; plain body drag still translates (regression); delete
  disabled at 3 vertices; the ratchet pin is LOWERED and
  `test_repo_integrity` passes.

## Completed

(nothing yet)
