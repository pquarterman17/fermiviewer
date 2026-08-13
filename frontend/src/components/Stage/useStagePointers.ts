// Pointer-interaction handlers for Stage.tsx (pan / marquee / capture /
// grain-edit / readout), split out in the repo-health #33 decomposition.
// Bodies moved verbatim; the only change is threading an explicit
// StagePointersCtx instead of closing over component state directly —
// Stage.tsx builds the ctx and calls this hook every render (matching how
// these handlers were already recreated each render as plain consts, same
// pattern as the stageFinalizers.ts split).
//
// The gesture RULES no longer live here (MAIN_PLAN item 1): each "given the
// mode, the point and the pending capture, what should happen?" branch is a
// pure function in pointerDecisions.ts returning a described action, and the
// grain-map click mode is in stageGrainEdit.ts. What is left needs the
// closure — refs, pointer capture, applying an action to state.

import { useRef, type RefObject } from "react";

import { applyFilter } from "../../lib/api";
import { screenToImage, viewForRect, type Size } from "../../lib/geometry";
import { loadPrefs } from "../../lib/prefs";
import { useBrowseScale } from "../../store/browseScale";
import {
  useViewer,
  type CaptureMode,
  type Measure,
  type View,
} from "../../store/viewer";
import {
  clickCaptureAction,
  cropRectFromPoints,
  fixedZoomCorners,
  imagePointToPixel,
  measuresInRect,
  pendingAfterMove,
  polyFinishAction,
  spansMinRegion,
  type CaptureAction,
  type PendingMeasure,
} from "./pointerDecisions";
import {
  appendLassoPoint,
  finishLasso,
  startLasso,
  type LassoCapture,
} from "./regionCapture";
import { grainClickAction, runGrainEdit } from "./stageGrainEdit";
import { runFitAndReseed } from "./stageScaleLock";
import { buildCtxTarget, type CtxTarget } from "./StageCtxMenu";
import { CLICKS, type Pt } from "./stageUtils";

/** Release pointer capture, tolerating a capture the browser has already
 *  dropped — the guarded form every early return in onPointerUp needs. */
function releaseCapture(e: React.PointerEvent) {
  try {
    e.currentTarget.releasePointerCapture(e.pointerId);
  } catch {
    // capture may already be gone; ignore
  }
}

export interface StagePointersCtx {
  // refs (stable identity; mutated directly, not via setState)
  wrapRef: RefObject<HTMLDivElement | null>;
  scaleBarRef: RefObject<HTMLDivElement>;
  dragRef: RefObject<{ last: Pt } | null>;
  specnavRef: RefObject<boolean>;
  fourdnavRef: RefObject<boolean>;
  paintingRef: RefObject<boolean>;

  // per-render values
  view: View | null;
  imgSize: Size | null;
  vp: Size;
  activeId: string | null;
  captureMode: CaptureMode;
  panTool: boolean;
  spaceHeld: boolean;
  paintActive: boolean;
  grainMode: "off" | "merge" | "split";
  isGrainMap: boolean;
  fixedZoomW: number;
  fixedZoomH: number;
  pending: PendingMeasure | null;
  marquee: { a: Pt; b: Pt } | null;
  grainPending: Pt | null;

  // stable setters / store actions
  setCaptureMode: (mode: CaptureMode) => void;
  setStatus: (msg: string) => void;
  setPanning: (v: boolean) => void;
  setCursor: (p: Pt | null) => void;
  setSpecnavPixel: (pixel: [number, number]) => void;
  setFourdNavPixel: (pixel: [number, number]) => void;
  setMarquee: (m: { a: Pt; b: Pt } | null) => void;
  setPending: (p: PendingMeasure | null) => void;
  setGrainPending: (p: Pt | null) => void;
  setStageCtx: (target: CtxTarget | null) => void;
  startStroke: (pt: [number, number]) => void;
  addPoint: (pt: [number, number]) => void;
  apply: (v: View) => void;
  finalizeMeasure: (kind: Measure["kind"], ptsImg: Pt[]) => void;
  finalizeCalibration: (ptsImg: Pt[]) => void;
  finalizeBoxProfile: (a: Pt, b: Pt) => void;
}

export function useStagePointers(ctx: StagePointersCtx) {
  const {
    wrapRef,
    scaleBarRef,
    dragRef,
    specnavRef,
    fourdnavRef,
    paintingRef,
    view,
    imgSize,
    vp,
    activeId,
    captureMode,
    panTool,
    spaceHeld,
    paintActive,
    grainMode,
    isGrainMap,
    fixedZoomW,
    fixedZoomH,
    pending,
    marquee,
    grainPending,
    setCaptureMode,
    setStatus,
    setPanning,
    setCursor,
    setSpecnavPixel,
    setFourdNavPixel,
    setMarquee,
    setPending,
    setGrainPending,
    setStageCtx,
    startStroke,
    addPoint,
    apply,
    finalizeMeasure,
    finalizeCalibration,
    finalizeBoxProfile,
  } = ctx;

  // lasso: local capture accumulator (regionCapture.ts) — no ctx ref needed
  // since only this hook's own pointer handlers touch it.
  const lassoRef = useRef<LassoCapture | null>(null);
  // #17: simplify tolerance (screen px), cached per-drag (avoids per-move reads)
  const lassoTolRef = useRef(2);

  // ── pointer: pan / marquee / capture / readout ──
  const local = (e: React.PointerEvent | React.MouseEvent): Pt => {
    const r = wrapRef.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const toImage = (p: Pt): Pt => {
    const ip = screenToImage(p.x, p.y, view!, imgSize!, vp);
    return {
      x: Math.min(imgSize!.w, Math.max(0, ip.x)),
      y: Math.min(imgSize!.h, Math.max(0, ip.y)),
    };
  };
  // Apply one decided CaptureAction (pointerDecisions.ts). The finalizers
  // clear captureMode themselves, so only the cancel path resets it here.
  const runCaptureAction = (act: CaptureAction) => {
    if (act.kind === "pending") {
      setPending(act.pending);
      return;
    }
    if (act.kind === "measure") finalizeMeasure(act.measure, act.pts);
    else if (act.kind === "calibration") finalizeCalibration(act.pts);
    else setCaptureMode("none");
    setPending(null);
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (!view || !imgSize) return;
    const p = local(e);
    const panStart =
      e.button === 1 || (e.button === 0 && (panTool || spaceHeld));
    if (panStart) {
      dragRef.current = { last: p };
      setPanning(true);
      e.currentTarget.setPointerCapture(e.pointerId);
      e.preventDefault();
      return;
    }
    if (e.button !== 0) return;

    // trained mode: drag paints a class scribble onto the source image
    if (paintActive) {
      const ip = toImage(p);
      startStroke([Math.floor(ip.x), Math.floor(ip.y)]);
      paintingRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }

    // grain editor intercepts plain clicks on a grain-label map
    if (grainMode !== "off" && isGrainMap) {
      const ip = toImage(p);
      const act = grainClickAction(ip, imgSize, grainMode, grainPending);
      if (act.kind === "pick") setGrainPending(act.at);
      else {
        runGrainEdit(activeId, act.op, act.points, setStatus);
        // the second click of a merge consumes the remembered first pick
        if (act.op === "merge") setGrainPending(null);
      }
      return;
    }

    if (captureMode === "fixed-zoom" && imgSize) {
      // A2: click places a fixed W×H box centred at the cursor, then zooms
      const [a, b] = fixedZoomCorners(toImage(p), fixedZoomW, fixedZoomH);
      apply(viewForRect(a, b, imgSize, vp));
      setCaptureMode("none");
      return;
    }

    // #10 specnav: click (or drag) the main image → publish the picked 1-based
    // pixel; the open EELS/EDS workshop watches it and refreshes its spectrum.
    if (captureMode === "specnav" && imgSize) {
      setSpecnavPixel(imagePointToPixel(toImage(p), imgSize));
      specnavRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
    // #14 fourdnav: same as specnav, but for the 4D-STEM probe — click (or
    // drag) the nav image on the main Stage to move the probed scan
    // position (the open FourD workshop watches the published pixel).
    if (captureMode === "fourdnav" && imgSize) {
      setFourdNavPixel(imagePointToPixel(toImage(p), imgSize));
      fourdnavRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
    if (
      captureMode === "zoom" ||
      captureMode === "roi" ||
      captureMode === "ellipse" ||
      captureMode === "box-profile" ||
      captureMode === "crop-save" ||
      (captureMode === "none" && e.shiftKey) // marquee measure-select
    ) {
      setMarquee({ a: p, b: p });
      e.currentTarget.setPointerCapture(e.pointerId);
    } else if (captureMode === "lasso") {
      // freehand region: pointermove appends points while the button is
      // held (onPointerMove below, via regionCapture.ts) — no click
      // accumulation, unlike the click-counted modes just below.
      const ip = toImage(p);
      lassoTolRef.current = loadPrefs().lassoSimplifyPx;
      lassoRef.current = startLasso(ip);
      setPending({ kind: "lasso", pts: [ip] });
      e.currentTarget.setPointerCapture(e.pointerId);
    } else if (captureMode in CLICKS) {
      const ip = toImage(p);
      runCaptureAction(
        clickCaptureAction(captureMode, pending, ip, e.shiftKey, view.z),
      );
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = local(e);
    if (view && imgSize) {
      const ip = screenToImage(p.x, p.y, view, imgSize, vp);
      const inside =
        ip.x >= 0 && ip.y >= 0 && ip.x < imgSize.w && ip.y < imgSize.h;
      setCursor(inside ? ip : null);
    }
    if (paintingRef.current && view && imgSize) {
      const ip = toImage(p);
      addPoint([Math.floor(ip.x), Math.floor(ip.y)]);
      return;
    }
    // specnav drag: keep publishing the pixel under the cursor (#10)
    if (specnavRef.current && view && imgSize) {
      setSpecnavPixel(imagePointToPixel(toImage(p), imgSize));
      return;
    }
    // fourdnav drag: same, for the 4D-STEM probe pixel (#14)
    if (fourdnavRef.current && view && imgSize) {
      setFourdNavPixel(imagePointToPixel(toImage(p), imgSize));
      return;
    }
    if (dragRef.current && view && imgSize) {
      const { last } = dragRef.current;
      apply({
        ...view,
        px: view.px - (p.x - last.x) / (view.z * imgSize.w),
        py: view.py - (p.y - last.y) / (view.z * imgSize.h),
      });
      dragRef.current = { last: p };
    } else if (lassoRef.current && view && imgSize) {
      if (captureMode !== "lasso") {
        // tool was cancelled mid-drag (e.g. Escape) — stop accumulating
        lassoRef.current = null;
      } else {
        const ip = toImage(p);
        const tol = lassoTolRef.current / view.z;
        lassoRef.current = appendLassoPoint(lassoRef.current, ip, tol);
        setPending({ kind: "lasso", pts: lassoRef.current.pts });
      }
    } else if (marquee) {
      setMarquee({ a: marquee.a, b: p });
    } else if (pending && view && imgSize) {
      const ip = toImage(p);
      setPending(pendingAfterMove(pending, captureMode, ip, e.shiftKey));
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (paintingRef.current) {
      paintingRef.current = false;
      releaseCapture(e);
      return;
    }
    if (specnavRef.current) {
      specnavRef.current = false;
      releaseCapture(e);
      return;
    }
    if (fourdnavRef.current) {
      fourdnavRef.current = false;
      releaseCapture(e);
      return;
    }
    if (lassoRef.current) {
      const cap = lassoRef.current;
      lassoRef.current = null;
      setPending(null);
      releaseCapture(e);
      if (captureMode === "lasso") {
        const pts = finishLasso(cap);
        if (pts) finalizeMeasure("lasso", pts);
        else setCaptureMode("none");
      }
      return;
    }
    if (dragRef.current) {
      dragRef.current = null;
      setPanning(false);
    } else if (marquee && view && imgSize) {
      const a = screenToImage(marquee.a.x, marquee.a.y, view, imgSize, vp);
      const b = screenToImage(marquee.b.x, marquee.b.y, view, imgSize, vp);
      // ia/ib are the same corners CLAMPED into the image; a/b stay raw for
      // the min-span test and the zoom rect, exactly as before the split
      const ia = toImage(marquee.a);
      const ib = toImage(marquee.b);
      if (captureMode === "roi" || captureMode === "ellipse") {
        if (spansMinRegion(a, b)) finalizeMeasure(captureMode, [ia, ib]);
        else setCaptureMode("none");
      } else if (captureMode === "box-profile") {
        finalizeBoxProfile(ia, ib);
      } else if (captureMode === "crop-save") {
        // Save Cropped Region (audit #16): drag a box → register the cropped
        // area as a new derived image (same as Crop to ROI but marquee-driven
        // and does NOT navigate away — the original stays active).
        const rect = cropRectFromPoints(ia, ib, imgSize);
        if (rect && activeId) {
          applyFilter(activeId, "crop", rect)
            .then((m) => {
              useViewer.getState().ingestDerived([m]);
              setStatus(`cropped region saved → ${m.name}`);
            })
            .catch((e: Error) => setStatus(`crop-save: ${e.message}`));
        }
        setCaptureMode("none");
      } else if (captureMode === "none") {
        // shift-drag marquee: select every measure with a point inside
        const s = useViewer.getState();
        const hits = measuresInRect(
          s.measures[activeId ?? ""] ?? [],
          a,
          b,
          imgSize,
        );
        s.setSelectedMulti(hits);
        if (hits.length) setStatus(`${hits.length} measures selected`);
      } else {
        apply(viewForRect(a, b, imgSize, vp));
        setCaptureMode("none");
      }
      setMarquee(null);
    }
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const onDoubleClick = () => {
    if (pending?.kind === "polyline" || pending?.kind === "polygon") {
      runCaptureAction(polyFinishAction(pending));
      return;
    }
    // #9: fit-to-window also re-seeds the browse-scale lock (Stage.tsx parity)
    if (!pending && imgSize) {
      const pixelSize = activeId
        ? useViewer.getState().images[activeId]?.pixel_size ?? null
        : null;
      const { locked, reseed } = useBrowseScale.getState();
      runFitAndReseed(imgSize, vp, pixelSize, locked, apply, reseed);
    }
  };

  const onContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    // right-click during an active drag stays inert
    if (dragRef.current) return;
    const measures = activeId
      ? (useViewer.getState().measures[activeId] ?? [])
      : [];
    const target = buildCtxTarget(
      e,
      scaleBarRef.current,
      measures,
      imgSize,
      view,
      vp,
    );
    if (target.kind === "scalebar") {
      // the scale bar keeps its dedicated quick menu (hide / length / reset)
      setStageCtx(target);
    } else {
      // empty area — or a missed measure handle, since MeasureOverlay's own
      // onContextMenu stopPropagates on real hits — opens the radial capture
      // ring directly, restoring the original right-click behaviour.
      useViewer.getState().setRadial({ x: target.x, y: target.y });
    }
  };

  return {
    local,
    toImage,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onDoubleClick,
    onContextMenu,
  };
}
