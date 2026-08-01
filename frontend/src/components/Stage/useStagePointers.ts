// Pointer-interaction handlers for Stage.tsx (pan / marquee / capture /
// grain-edit / readout), split out in the repo-health #33 decomposition.
// Bodies moved verbatim; the only change is threading an explicit
// StagePointersCtx instead of closing over component state directly —
// Stage.tsx builds the ctx and calls this hook every render (matching how
// these handlers were already recreated each render as plain consts, same
// pattern as the stageFinalizers.ts split).

import type { RefObject } from "react";

import { applyFilter, grainsEdit } from "../../lib/api";
import {
  fitView,
  screenToImage,
  viewForRect,
  type Size,
} from "../../lib/geometry";
import { replaceCrossSectionGrainsAfterEdit } from "../../store/crossSection";
import {
  useViewer,
  type CaptureMode,
  type Measure,
  type View,
} from "../../store/viewer";
import { buildCtxTarget, type CtxTarget } from "./StageCtxMenu";
import { CLICKS, snapHV, type Pt } from "./stageUtils";

export interface StagePointersCtx {
  // refs (stable identity; mutated directly, not via setState)
  wrapRef: RefObject<HTMLDivElement | null>;
  scaleBarRef: RefObject<HTMLDivElement>;
  dragRef: RefObject<{ last: Pt } | null>;
  specnavRef: RefObject<boolean>;
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
  pending: { kind: Measure["kind"]; pts: Pt[] } | null;
  marquee: { a: Pt; b: Pt } | null;
  grainPending: Pt | null;

  // stable setters / store actions
  setCaptureMode: (mode: CaptureMode) => void;
  setStatus: (msg: string) => void;
  setPanning: (v: boolean) => void;
  setCursor: (p: Pt | null) => void;
  setSpecnavPixel: (pixel: [number, number]) => void;
  setMarquee: (m: { a: Pt; b: Pt } | null) => void;
  setPending: (p: { kind: Measure["kind"]; pts: Pt[] } | null) => void;
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

  // image-space point → 1-based [row, col] pixel, clamped to the image (#10)
  const pixelAt = (ip: Pt): [number, number] => [
    Math.min(imgSize!.h, Math.max(1, Math.floor(ip.y) + 1)),
    Math.min(imgSize!.w, Math.max(1, Math.floor(ip.x) + 1)),
  ];

  const runGrainEdit = (op: "merge" | "split", points: [number, number][]) => {
    if (!activeId) return;
    const startId = activeId;
    setStatus(op === "merge" ? "merging grains…" : "splitting grain…");
    grainsEdit(startId, op, points)
      .then((r) => {
        const s = useViewer.getState();
        s.ingestDerived([r.labels]);
        replaceCrossSectionGrainsAfterEdit(r);
        if (s.activeId === startId) s.setActive(r.labels.id);
        setStatus(
          `${r.n_grains} grains` +
            (r.astm_grain_size != null
              ? ` · ASTM G ${r.astm_grain_size.toFixed(1)}`
              : ""),
        );
      })
      .catch((e: Error) => setStatus(`grain edit: ${e.message}`));
  };

  const handleGrainClick = (ip: Pt) => {
    if (!imgSize) return;
    // snap to a valid 0-based pixel index; a click at the exact w/h edge
    // would otherwise be out of bounds server-side (→ 422 on a real click)
    const cp = {
      x: Math.min(imgSize.w - 1, Math.max(0, Math.floor(ip.x))),
      y: Math.min(imgSize.h - 1, Math.max(0, Math.floor(ip.y))),
    };
    if (grainMode === "split") {
      runGrainEdit("split", [[cp.x, cp.y]]);
    } else if (grainPending) {
      runGrainEdit("merge", [
        [grainPending.x, grainPending.y],
        [cp.x, cp.y],
      ]);
      setGrainPending(null);
    } else {
      setGrainPending(cp);
    }
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
      handleGrainClick(toImage(p));
      return;
    }

    if (captureMode === "fixed-zoom" && imgSize) {
      // A2: click places a fixed W×H box centred at the cursor, then zooms
      const ip = toImage(p);
      const hw = fixedZoomW / 2;
      const hh = fixedZoomH / 2;
      const a = { x: ip.x - hw, y: ip.y - hh };
      const b = { x: ip.x + hw, y: ip.y + hh };
      apply(viewForRect(a, b, imgSize, vp));
      setCaptureMode("none");
      return;
    }

    // #10 specnav: click (or drag) the main image → publish the picked 1-based
    // pixel; the open EELS/EDS workshop watches it and refreshes its spectrum.
    if (captureMode === "specnav" && imgSize) {
      setSpecnavPixel(pixelAt(toImage(p)));
      specnavRef.current = true;
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
    } else if (captureMode in CLICKS) {
      let ip = toImage(p);
      const need = CLICKS[captureMode];
      const cur = pending?.pts ?? [];
      // calibration line snaps H/V (Shift = free) so a flat bar traces cleanly
      if (captureMode === "calibrate" && cur.length >= 1) {
        ip = snapHV(cur[0], ip, e.shiftKey);
      }
      // replace the live cursor point with the committed click
      const committed = pending ? [...cur.slice(0, -1), ip] : [ip];
      if (committed.length >= need) {
        if (captureMode === "calibrate") finalizeCalibration(committed);
        else finalizeMeasure(captureMode as Measure["kind"], committed);
        setPending(null);
      } else {
        setPending({
          // preview the calibration line as a plain distance line
          kind:
            captureMode === "calibrate"
              ? "distance"
              : (captureMode as Measure["kind"]),
          pts: [...committed, ip],
        });
      }
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
      setSpecnavPixel(pixelAt(toImage(p)));
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
    } else if (marquee) {
      setMarquee({ a: marquee.a, b: p });
    } else if (pending && view && imgSize) {
      let ip = toImage(p);
      if (captureMode === "calibrate" && pending.pts.length >= 1) {
        ip = snapHV(pending.pts[0], ip, e.shiftKey);
      }
      setPending({
        kind: pending.kind,
        pts: [...pending.pts.slice(0, -1), ip],
      });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (paintingRef.current) {
      paintingRef.current = false;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        // capture may already be gone; ignore
      }
      return;
    }
    if (specnavRef.current) {
      specnavRef.current = false;
      try {
        e.currentTarget.releasePointerCapture(e.pointerId);
      } catch {
        // capture may already be gone; ignore
      }
      return;
    }
    if (dragRef.current) {
      dragRef.current = null;
      setPanning(false);
    } else if (marquee && view && imgSize) {
      const a = screenToImage(marquee.a.x, marquee.a.y, view, imgSize, vp);
      const b = screenToImage(marquee.b.x, marquee.b.y, view, imgSize, vp);
      if (captureMode === "roi" || captureMode === "ellipse") {
        const w = Math.abs(b.x - a.x);
        const h = Math.abs(b.y - a.y);
        if (w >= 2 && h >= 2) {
          finalizeMeasure(captureMode, [
            toImage(marquee.a),
            toImage(marquee.b),
          ]);
        } else {
          setCaptureMode("none");
        }
      } else if (captureMode === "box-profile") {
        finalizeBoxProfile(toImage(marquee.a), toImage(marquee.b));
      } else if (captureMode === "crop-save") {
        // Save Cropped Region (audit #16): drag a box → register the cropped
        // area as a new derived image (same as Crop to ROI but marquee-driven
        // and does NOT navigate away — the original stays active).
        const ia = toImage(marquee.a);
        const ib = toImage(marquee.b);
        const w2 = Math.abs(ib.x - ia.x);
        const h2 = Math.abs(ib.y - ia.y);
        if (w2 >= 2 && h2 >= 2 && activeId && imgSize) {
          const px = (v: number, n: number) =>
            Math.min(n, Math.max(1, Math.round(v + 0.5)));
          applyFilter(activeId, "crop", {
            row0: px(Math.min(ia.y, ib.y), imgSize.h),
            col0: px(Math.min(ia.x, ib.x), imgSize.w),
            row1: px(Math.max(ia.y, ib.y), imgSize.h),
            col1: px(Math.max(ia.x, ib.x), imgSize.w),
          })
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
        const x0 = Math.min(a.x, b.x) / imgSize.w;
        const x1 = Math.max(a.x, b.x) / imgSize.w;
        const y0 = Math.min(a.y, b.y) / imgSize.h;
        const y1 = Math.max(a.y, b.y) / imgSize.h;
        const hits = (s.measures[activeId ?? ""] ?? [])
          .filter((m) =>
            m.pts.some(
              (p2) => p2.x >= x0 && p2.x <= x1 && p2.y >= y0 && p2.y <= y1,
            ),
          )
          .map((m) => m.id);
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
    if (pending?.kind === "polyline") {
      // the double-click's two pointerdowns committed a duplicate
      // vertex + a live cursor point — drop both
      const committed = pending.pts.slice(0, -2);
      if (committed.length >= 2) finalizeMeasure("polyline", committed);
      else setCaptureMode("none");
      setPending(null);
      return;
    }
    if (!pending && imgSize) apply(fitView(imgSize, vp));
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
    pixelAt,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onDoubleClick,
    onContextMenu,
  };
}
