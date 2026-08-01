// finalizeMeasure / finalizeCalibration / finalizeBoxProfile factories,
// split out of Stage.tsx in the repo-health #33 decomposition. Bodies moved
// verbatim; the only change is threading an explicit FinalizerCtx instead of
// closing over component state directly — Stage.tsx builds the ctx each
// render (as these closures already were, being plain non-memoized consts)
// and the pointer-handler call sites are unchanged.

import {
  measurePolyline,
  measureProfile,
  measureRoi,
  type RoiStats,
} from "../../lib/api";
import { boxProfileLine, type Size } from "../../lib/geometry";
import type { ActiveProfile } from "../../store/stage";
import { useViewer, type CaptureMode, type Measure } from "../../store/viewer";
import type { Pt } from "./stageUtils";

export interface FinalizerCtx {
  activeId: string | null;
  imgSize: Size | null;
  setCaptureMode: (mode: CaptureMode) => void;
  addMeasure: (imageId: string, m: Omit<Measure, "id">) => string;
  setProfile: (p: ActiveProfile | null) => void;
  setStatus: (msg: string) => void;
  setRoiStats: (measureId: string, stats: RoiStats) => void;
}

export function makeFinalizeMeasure(ctx: FinalizerCtx) {
  const {
    activeId,
    imgSize,
    setCaptureMode,
    addMeasure,
    setProfile,
    setStatus,
    setRoiStats,
  } = ctx;
  return (kind: Measure["kind"], ptsImg: Pt[]) => {
    if (!activeId || !imgSize) return;
    const pts = ptsImg.map((p) => ({ x: p.x / imgSize.w, y: p.y / imgSize.h }));
    let text: string | undefined;
    if (
      kind === "text" ||
      kind === "arrow" ||
      kind === "box" ||
      kind === "circle"
    ) {
      text =
        window.prompt(
          kind === "text" ? "Annotation text:" : "Label (optional):",
        ) ?? undefined;
      if (kind === "text" && !text) {
        setCaptureMode("none");
        return; // text annotation without text is nothing
      }
    }
    const mid = addMeasure(activeId, { kind, pts, text });
    setCaptureMode("none");
    // a slow response must not overwrite the dock plot/ROI stats once the
    // user has navigated to a different image (matches runGrainEdit below)
    const startId = activeId;
    const width = useViewer.getState().profileWidth;
    const reduce = useViewer.getState().profileReduce;
    if (kind === "profile") {
      measureProfile(activeId, ptsImg[0], ptsImg[1], width, null, reduce)
        .then((r) => {
          if (useViewer.getState().activeId === startId)
            setProfile({ ...r, measureId: mid });
        })
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "polyline") {
      measurePolyline(activeId, ptsImg, width, reduce)
        .then((r) => {
          if (useViewer.getState().activeId === startId)
            setProfile({ ...r, measureId: mid });
        })
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "roi" || kind === "ellipse") {
      measureRoi(
        activeId,
        ptsImg[0],
        ptsImg[1],
        kind === "ellipse" ? "ellipse" : "rect",
      )
        .then((r) => {
          if (useViewer.getState().activeId === startId) setRoiStats(mid, r);
        })
        .catch((e: Error) => setStatus(e.message));
    }
  };
}

/** Calibration line: a plain distance measure, drawn with H/V snap and
 *  left SELECTED so the inspector's Calibration card can turn it into a
 *  pixel size. It vanishes once the user sets its real length there. */
export function makeFinalizeCalibration(ctx: FinalizerCtx) {
  const { activeId, imgSize, setCaptureMode, addMeasure, setStatus } = ctx;
  return (ptsImg: Pt[]) => {
    if (!activeId || !imgSize) {
      setCaptureMode("none");
      return;
    }
    // reject a zero/near-zero line (same-pixel clicks, or H/V snap collapse)
    // so we never leave an invisible, un-calibratable phantom measure
    if (Math.hypot(ptsImg[1].x - ptsImg[0].x, ptsImg[1].y - ptsImg[0].y) < 1) {
      setStatus("calibration line too short — click two distinct points");
      setCaptureMode("none");
      return;
    }
    const pts = ptsImg.map((p) => ({ x: p.x / imgSize.w, y: p.y / imgSize.h }));
    const mid = addMeasure(activeId, { kind: "distance", pts });
    setCaptureMode("none");
    useViewer.getState().setSelectedMeasure(mid);
    setStatus(
      "calibration line drawn — set its real length in the Calibration card",
    );
  };
}

/** Box profile (user request 2026-06-09): drag a box → profile runs
 *  along its LONG axis, ⊥-averaged across the short axis for more
 *  signal. Stored as a profile measure with a per-measure width. */
export function makeFinalizeBoxProfile(ctx: FinalizerCtx) {
  const { activeId, imgSize, setCaptureMode, addMeasure, setProfile, setStatus } =
    ctx;
  return (a: Pt, b: Pt) => {
    if (!activeId || !imgSize) {
      setCaptureMode("none");
      return;
    }
    const line = boxProfileLine(a, b);
    if (!line) {
      setCaptureMode("none");
      return;
    }
    const { p0, p1, width } = line;
    const pts = [p0, p1].map((p) => ({
      x: p.x / imgSize.w,
      y: p.y / imgSize.h,
    }));
    const mid = addMeasure(activeId, { kind: "profile", pts, width });
    setCaptureMode("none");
    // don't apply a slow response after the user has switched images
    const startId = activeId;
    const tilt = useViewer.getState().tilts[activeId] ?? null;
    const reduce = useViewer.getState().profileReduce;
    measureProfile(activeId, p0, p1, width, tilt, reduce)
      .then((r) => {
        if (useViewer.getState().activeId !== startId) return;
        setProfile({ ...r, measureId: mid });
        setStatus(`profile integrated over ${width} px`);
      })
      .catch((e: Error) => setStatus(e.message));
  };
}
