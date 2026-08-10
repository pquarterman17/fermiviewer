// Constant-physical-scale lock wiring for Stage.tsx (plan item 8,
// PROJECT_WORKFLOW_PLAN.md). Paging through a series with `fitView`'s
// per-image default zoom lets a feature change on-screen size frame to
// frame — jarring when images differ in pixel size. The math itself
// (`resolveScaleView` / `physicalScale`) shipped in PR #126
// (lib/geometry.ts); this module is just the two call sites Stage.tsx
// needs, broken out so they're unit-testable without mounting the
// GL-backed component (canvas/WebGL, fetch, ResizeObserver).

import {
  fitView,
  physicalScale,
  resolveScaleView,
  type Size,
} from "../../lib/geometry";
import type { View } from "../../store/viewer";

/** The view Stage falls back to when the active image has no stored
 *  view. `storedView` always wins outright — an image the user has
 *  already framed is never overridden by the lock, which is what keeps
 *  enabling the lock from jumping the current view. Only a *fresh*
 *  image (no stored view, e.g. just stepped onto) resolves the lock:
 *  locked + calibrated holds the physical scale, otherwise `fitView`,
 *  exactly as the no-lock path has always behaved. */
export function defaultStageView(
  storedView: View | null,
  imgSize: Size | null,
  vp: Size,
  pixelSize: number | null,
  lock: { locked: boolean; scale: number | null },
): View | null {
  if (!imgSize) return null;
  return (
    storedView ??
    resolveScaleView(
      lock.locked ? lock.scale : null,
      pixelSize,
      imgSize,
      vp,
      { px: 0.5, py: 0.5 },
    )
  );
}

/** Fit view plus the browse-scale value to reseed with it (null when the
 *  lock is off or the image is uncalibrated). "Fit" is a deliberate
 *  reframe, so — unlike ordinary pan/zoom, which leaves the lock alone —
 *  it RE-SEEDS the lock rather than leaving it pointing at a scale the
 *  user just abandoned; the next image then matches what was just
 *  fitted instead of the stale pre-fit scale. */
export function fitAndReseedScale(
  imgSize: Size,
  vp: Size,
  pixelSize: number | null,
  locked: boolean,
): { view: View; reseedTo: number | null } {
  const view = fitView(imgSize, vp);
  const calibrated =
    pixelSize != null && Number.isFinite(pixelSize) && pixelSize > 0;
  return {
    view,
    reseedTo: locked && calibrated ? physicalScale(view, pixelSize) : null,
  };
}

/** Runs one fit-and-reseed cycle: computes the fitted view via
 *  fitAndReseedScale, applies it, then reseeds the lock only when the fit
 *  produced one (never on an uncalibrated image or while unlocked). Every
 *  double-click-to-fit call site outside Stage.tsx (which inlines the same
 *  two lines in its imperative `fit()`) — CompareStage.tsx,
 *  SideBySideStage.tsx, useStagePointers.ts's onDoubleClick (item 9's
 *  booked defect) — shares this so the sequencing can't drift between
 *  them. */
export function runFitAndReseed(
  imgSize: Size,
  vp: Size,
  pixelSize: number | null,
  locked: boolean,
  applyView: (v: View) => void,
  reseedScale: (scale: number) => void,
): void {
  const { view, reseedTo } = fitAndReseedScale(imgSize, vp, pixelSize, locked);
  applyView(view);
  if (reseedTo != null) reseedScale(reseedTo);
}
