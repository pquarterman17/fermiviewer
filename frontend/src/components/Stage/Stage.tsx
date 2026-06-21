// Central stage (handoff §4/§9): WebGL render with client-side window/
// level/γ/LUT, pan / wheel-zoom / box-zoom, measurement capture modes
// (distance · profile · angle · ROI), dock plot, radial-menu trigger.

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type RefObject,
} from "react";

import { GLRenderer } from "../../gl/render";
import {
  fetchData16,
  grainsEdit,
  measurePolyline,
  measureProfile,
  measureRoi,
  type Raster16,
} from "../../lib/api";
import { buildLabelLut, buildLut } from "../../lib/colormaps";
import { autoWindow } from "../../lib/display";
import {
  boxProfileLine,
  fitView,
  imageToScreen,
  screenToImage,
  viewForRect,
  zoomAbout,
  type Size,
} from "../../lib/geometry";
import { loadPrefs } from "../../lib/prefs";
import { applyFilter } from "../../lib/api";
import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { useScribble } from "../../store/scribble";
import { rasterValue, useStageInfo } from "../../store/stage";
import {
  DEFAULT_DISPLAY,
  useViewer,
  type Measure,
  type View,
} from "../../store/viewer";
import CaptureBanner from "./CaptureBanner";
import DockPlot from "./DockPlot";
import MeasureOverlay from "./MeasureOverlay";
import Minimap from "./Minimap";
import ScaleBarOverlay from "./ScaleBarOverlay";
import ScribbleOverlay from "./ScribbleOverlay";
import {
  ScaleBarCtxMenu,
  buildCtxTarget,
  type CtxTarget,
} from "./StageCtxMenu";

export interface StageHandle {
  fit: () => void;
  actualSize: () => void;
  zoomBy: (factor: number) => void;
  nudge: (dx: number, dy: number) => void;
}

interface Pt {
  x: number;
  y: number;
}

const WHEEL_K = 0.0015;
/** Apply a display intensity transform to a normalized-u16 raster
 *  (log: log1p rescale; equalize: 4096-bin CDF mapping). */
function transformU16(
  data: Uint16Array,
  mode: "linear" | "log" | "equalize",
): Uint16Array {
  if (mode === "linear") return data;
  const out = new Uint16Array(data.length);
  if (mode === "log") {
    const k = 65535 / Math.log1p(65535);
    for (let i = 0; i < data.length; i++) {
      out[i] = Math.round(Math.log1p(data[i]) * k);
    }
    return out;
  }
  // equalize: histogram → CDF → remap
  const BINS = 4096;
  const hist = new Float64Array(BINS);
  for (let i = 0; i < data.length; i++) hist[data[i] >> 4]++;
  const cdf = new Float64Array(BINS);
  let acc = 0;
  for (let b = 0; b < BINS; b++) {
    acc += hist[b];
    cdf[b] = acc;
  }
  const lo = cdf.find((v) => v > 0) ?? 0;
  const span = acc - lo || 1;
  const lut = new Uint16Array(BINS);
  for (let b = 0; b < BINS; b++) {
    lut[b] = Math.round(((cdf[b] - lo) / span) * 65535);
  }
  for (let i = 0; i < data.length; i++) out[i] = lut[data[i] >> 4];
  return out;
}

const CLICKS: Record<string, number> = {
  distance: 2,
  profile: 2,
  angle: 3,
  polyline: Infinity, // vertices accumulate; double-click finishes
  text: 1,
  arrow: 2,
  box: 2,
  circle: 2,
  calibrate: 2, // two-click line (snaps H/V) used to set the pixel size
};

/** Snap point b to a horizontal/vertical line through a (whichever axis the
 *  drag favours); `free` (Shift held) returns b unchanged. Used by the
 *  calibration line so a flat baked scale bar is easy to trace precisely. */
function snapHV(a: Pt, b: Pt, free: boolean): Pt {
  if (free) return b;
  return Math.abs(b.x - a.x) >= Math.abs(b.y - a.y)
    ? { x: b.x, y: a.y }
    : { x: a.x, y: b.y };
}

const Stage = forwardRef<StageHandle>(function Stage(_props, handle) {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const storedView = useViewer((s) =>
    s.activeId ? (s.views[s.activeId] ?? null) : null,
  );
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const setView = useViewer((s) => s.setView);
  const setDisplay = useViewer((s) => s.setDisplay);
  const stackFrame = useViewer((s) =>
    s.activeId ? (s.stackFrames[s.activeId] ?? 0) : 0,
  );
  const setStackFrame = useViewer((s) => s.setStackFrame);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const fixedZoomW = useViewer((s) => s.fixedZoomW);
  const fixedZoomH = useViewer((s) => s.fixedZoomH);
  const panTool = useViewer((s) => s.panTool);
  const addMeasure = useViewer((s) => s.addMeasure);
  const setRoiStats = useViewer((s) => s.setRoiStats);
  const setStatus = useViewer((s) => s.setStatus);
  const setCursor = useStageInfo((s) => s.setCursor);
  const setZoom = useStageInfo((s) => s.setZoom);
  const setRaster = useStageInfo((s) => s.setRaster);
  const setProfile = useStageInfo((s) => s.setProfile);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scaleBarRef = useRef<HTMLDivElement>(null) as RefObject<HTMLDivElement>;
  const glRef = useRef<GLRenderer | null>(null);
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const [imgSize, setImgSize] = useState<Size | null>(null);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [panning, setPanning] = useState(false);
  const [marquee, setMarquee] = useState<{ a: Pt; b: Pt } | null>(null);
  const [stageCtx, setStageCtx] = useState<CtxTarget | null>(null);
  const [grainMode, setGrainMode] = useState<"off" | "merge" | "split">("off");
  const [grainPending, setGrainPending] = useState<Pt | null>(null);
  // trained grain mode: paint class scribbles directly on this image
  const scribbleActive = useScribble((s) => s.active);
  const scribbleImageId = useScribble((s) => s.imageId);
  const startStroke = useScribble((s) => s.startStroke);
  const addPoint = useScribble((s) => s.addPoint);
  const paintingRef = useRef(false);
  const [nFrames, setNFrames] = useState<number | null>(null);
  // in-progress click-capture (image-space pts; last pt tracks cursor)
  const [pending, setPending] = useState<{
    kind: Measure["kind"];
    pts: Pt[];
  } | null>(null);
  const dragRef = useRef<{ last: Pt } | null>(null);
  const rasterRef = useRef<Raster16 | null>(null);

  const rasterless = meta?.kind === "spectrum";
  // a grain-label map (tagged by the grain analysis) is interactively
  // editable on the stage — click grains to merge/split
  const isGrainMap = Boolean(meta?.meta?.["grain_labels"]);
  // true while the trained-mode paint panel is open on THIS image
  const paintActive = scribbleActive && scribbleImageId === activeId;
  const view: View | null = imgSize && (storedView ?? fitView(imgSize, vp));

  // ── renderer lifecycle ──
  useEffect(() => {
    if (!canvasRef.current) return;
    let gl: GLRenderer;
    try {
      gl = new GLRenderer(canvasRef.current);
    } catch (err) {
      // A dead/unsupported GPU context must not take the whole app down —
      // degrade to a status message; the rest of the UI stays usable.
      useViewer
        .getState()
        .setStatus(`GPU image rendering unavailable: ${(err as Error).message}`);
      return;
    }
    glRef.current = gl;
    return () => {
      gl.dispose();
      glRef.current = null;
    };
  }, []);

  // ── viewport tracking ──
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setVp({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // ── load active image (raw uint16 → GPU) ──
  // Depends on stackFrame so re-fetches when frame index changes.
  useEffect(() => {
    setImgSize(null);
    setPending(null);
    setProfile(null);
    rasterRef.current = null;
    setRaster(null);
    if (!activeId || rasterless) {
      glRef.current?.clear();
      return;
    }
    const isStack = meta?.kind === "spectrum_image";
    const frameArg = isStack ? stackFrame : undefined;
    let alive = true;
    fetchData16(activeId, frameArg)
      .then((r) => {
        if (!alive || !glRef.current) return;
        glRef.current.setImage16(r.data, r.w, r.h);
        rasterRef.current = r;
        setRaster(r);
        setNFrames(r.nFrames);
        setImgSize({ w: r.w, h: r.h });
        // honor DM-saved display window on first load (checklist I)
        const st = useViewer.getState();
        if (!st.display[activeId] && st.images[activeId]) {
          const m = st.images[activeId].meta;
          const dl = m["display_low"];
          const dh = m["display_high"];
          const dg = m["display_gamma"];
          const di = m["display_inverted"];
          // these are one-time seeds on first display, not user actions —
          // mark them silent so they fold into the "Opened" history step
          // (WS4d) instead of logging a spurious "Contrast"/"Invert"
          if (typeof dl === "number" && typeof dh === "number" && dh > dl) {
            const span = r.vmax - r.vmin || 1;
            setDisplay(
              activeId,
              {
                lo: Math.max(0, (dl - r.vmin) / span),
                hi: Math.min(1, (dh - r.vmin) / span),
                gamma: typeof dg === "number" && dg > 0 ? dg : 1,
                invert: di === true,
              },
              { silent: true },
            );
          } else if (di === true) {
            setDisplay(activeId, { invert: true }, { silent: true });
          } else {
            // no embedded display window — auto-contrast on open if enabled
            // in Preferences (otherwise leave the full 0–1 range)
            const prefs = loadPrefs();
            if (prefs.autoContrastOnOpen) {
              setDisplay(
                activeId,
                autoWindow(r, prefs.autoLoPct, prefs.autoHiPct),
                { silent: true },
              );
            }
          }
        }
      })
      .catch((e: Error) => {
        if (alive) setStatus(`load failed: ${e.message}`);
      });
    return () => {
      alive = false;
    };
  }, [activeId, rasterless, stackFrame, meta?.kind, setDisplay, setProfile, setRaster, setStatus]);

  // ── colormap LUT upload ──
  useEffect(() => {
    const gl = glRef.current;
    if (!gl) return;
    if (display.cmap === "label") {
      // discrete per-grain palette sized to this map's max label id
      const vmax = rasterRef.current?.vmax ?? 1;
      gl.setLut(buildLabelLut(Math.round(vmax) + 1));
    } else {
      gl.setLut(buildLut(display.cmap));
    }
  }, [display.cmap, imgSize]);

  // grain/label maps display with a discrete per-grain palette by default
  // (a continuous LUT makes 50+ grains look like one colour family). Only
  // auto-applies on a fresh/default cmap — never overrides a manual pick.
  useEffect(() => {
    if (!isGrainMap || !activeId) return;
    const cur = useViewer.getState().display[activeId]?.cmap;
    if (cur === undefined || cur === "gray") {
      setDisplay(activeId, { cmap: "label" }, { silent: true });
    }
  }, [isGrainMap, activeId, setDisplay]);

  // ── intensity transform (checklist I): re-upload a transformed
  //    texture; the raw raster stays untouched for readouts ──
  useEffect(() => {
    const r = rasterRef.current;
    if (!glRef.current || !r) return;
    glRef.current.setImage16(
      transformU16(r.data, display.transform),
      r.w,
      r.h,
    );
  }, [display.transform, imgSize]);

  // ── draw on any view / window / size change ──
  useEffect(() => {
    if (!glRef.current || vp.w === 0) return;
    glRef.current.draw(
      view ?? { z: 1, px: 0.5, py: 0.5 },
      vp,
      window.devicePixelRatio || 1,
      {
        lo: display.lo,
        hi: display.hi,
        gamma: display.gamma,
        invert: display.invert,
      },
    );
  }, [view, vp, imgSize, display]);

  useEffect(() => {
    setZoom(view ? view.z : null);
  }, [view, setZoom]);

  // ── space-hold pan (handoff §9) ──
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat) {
        const t = e.target as HTMLElement;
        if (t.tagName !== "INPUT" && t.tagName !== "TEXTAREA") {
          e.preventDefault();
          setSpaceHeld(true);
        }
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space") setSpaceHeld(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, []);

  // ── stack frame keyboard navigation ( , / . ) ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      if (!activeId || !nFrames || nFrames < 2) return;
      if (e.key === "," || e.key === "<") {
        e.preventDefault();
        setStackFrame(activeId, Math.max(0, stackFrame - 1));
      } else if (e.key === "." || e.key === ">") {
        e.preventDefault();
        setStackFrame(activeId, Math.min(nFrames - 1, stackFrame + 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeId, nFrames, stackFrame, setStackFrame]);

  // ── cancel any in-progress capture when the mode changes (incl. Esc) ──
  // Clearing BOTH pending click-points and the marquee on every captureMode
  // change prevents (a) stale points from one click-tool corrupting the
  // next measure, and (b) an Esc mid-marquee leaving a marquee that fires a
  // spurious selection on the eventual pointer-up.
  useEffect(() => {
    setPending(null);
    setMarquee(null);
  }, [captureMode]);

  // grain editor applies only to a grain-label map; leave it when the
  // active image isn't one, and drop a half-finished merge on any change
  useEffect(() => {
    if (!isGrainMap) setGrainMode("off");
  }, [isGrainMap]);
  useEffect(() => {
    setGrainPending(null);
  }, [activeId, grainMode]);

  const apply = useCallback(
    (v: View) => {
      if (activeId) setView(activeId, v);
    },
    [activeId, setView],
  );

  // ── imperative API for menu / keyboard (App owns the key map) ──
  useImperativeHandle(
    handle,
    () => ({
      fit: () => {
        if (imgSize) apply(fitView(imgSize, vp));
      },
      actualSize: () => {
        if (view) apply({ ...view, z: 1 });
      },
      zoomBy: (factor) => {
        if (view && imgSize) {
          apply(zoomAbout(view, factor, vp.w / 2, vp.h / 2, imgSize, vp));
        }
      },
      nudge: (dx, dy) => {
        if (view && imgSize) {
          apply({
            ...view,
            px: view.px - dx / (view.z * imgSize.w),
            py: view.py - dy / (view.z * imgSize.h),
          });
        }
      },
    }),
    [imgSize, vp, view, apply],
  );

  // ── wheel zoom about cursor (native listener: needs preventDefault) ──
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (!view || !imgSize) return;
      const r = el.getBoundingClientRect();
      apply(
        zoomAbout(
          view,
          Math.exp(-e.deltaY * WHEEL_K),
          e.clientX - r.left,
          e.clientY - r.top,
          imgSize,
          vp,
        ),
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [view, imgSize, vp, apply]);

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

  const finalizeMeasure = (kind: Measure["kind"], ptsImg: Pt[]) => {
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
    const width = useViewer.getState().profileWidth;
    const reduce = useViewer.getState().profileReduce;
    if (kind === "profile") {
      measureProfile(activeId, ptsImg[0], ptsImg[1], width, null, reduce)
        .then((r) => setProfile({ ...r, measureId: mid }))
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "polyline") {
      measurePolyline(activeId, ptsImg, width, reduce)
        .then((r) => setProfile({ ...r, measureId: mid }))
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "roi" || kind === "ellipse") {
      measureRoi(activeId, ptsImg[0], ptsImg[1],
                 kind === "ellipse" ? "ellipse" : "rect")
        .then((r) => setRoiStats(mid, r))
        .catch((e: Error) => setStatus(e.message));
    }
  };

  /** Calibration line: a plain distance measure, drawn with H/V snap and
   *  left SELECTED so the inspector's Calibration card can turn it into a
   *  pixel size. It vanishes once the user sets its real length there. */
  const finalizeCalibration = (ptsImg: Pt[]) => {
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
    setStatus("calibration line drawn — set its real length in the Calibration card");
  };

  /** Box profile (user request 2026-06-09): drag a box → profile runs
   *  along its LONG axis, ⊥-averaged across the short axis for more
   *  signal. Stored as a profile measure with a per-measure width. */
  const finalizeBoxProfile = (a: Pt, b: Pt) => {
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
    const tilt = useViewer.getState().tilts[activeId] ?? null;
    const reduce = useViewer.getState().profileReduce;
    measureProfile(activeId, p0, p1, width, tilt, reduce)
      .then((r) => {
        setProfile({ ...r, measureId: mid });
        setStatus(`profile integrated over ${width} px`);
      })
      .catch((e: Error) => setStatus(e.message));
  };

  const runGrainEdit = (op: "merge" | "split", points: [number, number][]) => {
    if (!activeId) return;
    const startId = activeId;
    setStatus(op === "merge" ? "merging grains…" : "splitting grain…");
    grainsEdit(startId, op, points)
      .then((r) => {
        const s = useViewer.getState();
        s.ingestDerived([r.labels]);
        // only swap the view if the user is still on the map they edited —
        // a slow edit must not yank them back after they navigate away
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
          kind: captureMode === "calibrate"
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

  const cls = [
    "fvd-stage",
    captureMode === "fixed-zoom" ? "box-zoom" : captureMode !== "none" ? "box-zoom" : "",
    panning ? "panning" : panTool || spaceHeld ? "pan-ready" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // screen-space marker for the first grain picked in a pending merge
  const grainMarkPos =
    isGrainMap && grainMode === "merge" && grainPending && view && imgSize
      ? imageToScreen(grainPending.x, grainPending.y, view, imgSize, vp)
      : null;

  return (
    <div
      ref={wrapRef}
      className={cls}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={() => setCursor(null)}
      onDoubleClick={onDoubleClick}
      onContextMenu={onContextMenu}
    >
      <canvas ref={canvasRef} />

      {captureMode !== "none" && captureMode !== "fixed-zoom" && (
        <CaptureBanner
          mode={captureMode}
          pending={pending}
          onCancel={() => setCaptureMode("none")}
        />
      )}

      {!activeId && (
        <div className="fvd-stage-empty">Open an image — File → Open…</div>
      )}
      {rasterless && (
        <div className="fvd-stage-empty">
          1-D spectrum — plot view arrives with the EELS workshop
        </div>
      )}

      {marquee && (
        <div
          className="fvd-marquee"
          style={{
            left: Math.min(marquee.a.x, marquee.b.x),
            top: Math.min(marquee.a.y, marquee.b.y),
            width: Math.abs(marquee.b.x - marquee.a.x),
            height: Math.abs(marquee.b.y - marquee.a.y),
          }}
        />
      )}

      {activeId && !rasterless && imgSize && view && (
        <>
          <MeasureOverlay
            imageId={activeId}
            pixelSize={meta?.pixel_size ?? null}
            pixelUnit={meta?.pixel_unit ?? "px"}
            view={view}
            img={imgSize}
            vp={vp}
            pending={pending}
          />
          <FloatTools />
          {paintActive && <ScribbleOverlay view={view} img={imgSize} vp={vp} />}
          {isGrainMap && (
            <GrainEditBar
              mode={grainMode}
              setMode={setGrainMode}
              pending={grainPending}
            />
          )}
          {grainMarkPos && (
            <div
              className="fvd-grain-mark"
              style={{ left: grainMarkPos.x, top: grainMarkPos.y }}
            />
          )}
          <Minimap
            imageId={activeId}
            view={view}
            img={imgSize}
            vp={vp}
            onNavigate={apply}
          />
          <ZoomChip
            onZoom={(f) => {
              if (view && imgSize) {
                apply(zoomAbout(view, f, vp.w / 2, vp.h / 2, imgSize, vp));
              }
            }}
          />
          <Readout />
          {meta?.pixel_size != null && (
            <ScaleBarOverlay
              imageId={activeId}
              pixelSize={meta.pixel_size}
              unit={meta.pixel_unit}
              view={view}
              img={imgSize}
              vp={vp}
              barRef={scaleBarRef}
            />
          )}
          <DockPlot />
        </>
      )}

      {captureMode === "fixed-zoom" && (
        <FixedZoomBadge w={fixedZoomW} h={fixedZoomH} />
      )}
      {nFrames && nFrames > 1 && activeId && (
        <StackStepper
          imageId={activeId}
          frame={stackFrame}
          total={nFrames}
          onStep={(delta) => {
            const next = Math.min(nFrames - 1, Math.max(0, stackFrame + delta));
            setStackFrame(activeId, next);
          }}
        />
      )}
      {stageCtx?.kind === "scalebar" && (
        <ScaleBarCtxMenu
          x={stageCtx.x}
          y={stageCtx.y}
          onClose={() => setStageCtx(null)}
        />
      )}
    </div>
  );
});

export default Stage;

function FloatTools() {
  const activeId = useViewer((s) => s.activeId);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const panTool = useViewer((s) => s.panTool);
  const setPanTool = useViewer((s) => s.setPanTool);
  const deleteLastAnnotation = useViewer((s) => s.deleteLastAnnotation);
  const resetToOriginal = useViewer((s) => s.resetToOriginal);
  // show delete-last only when there are annotations/measures to delete
  const hasMeasures = useViewer((s) =>
    activeId ? (s.measures[activeId] ?? []).length > 0 : false,
  );
  // show reset-to-original only when the active image is derived
  const isDerived = useViewer((s) =>
    activeId
      ? typeof s.images[activeId]?.meta["derived_from"] === "string"
      : false,
  );

  const mode = (m: typeof captureMode) => () =>
    setCaptureMode(captureMode === m ? "none" : m);

  // prototype toolbar groups: transforms · capture/zoom · crop
  const transforms: [string, string, () => void][] = [
    ["⟲", "Rotate 90° CCW", () => applyGeometry("rotate270")],
    ["⟳", "Rotate 90° CW", () => applyGeometry("rotate90")],
    ["⬌", "Flip horizontal", () => applyGeometry("fliph")],
    ["⬍", "Flip vertical", () => applyGeometry("flipv")],
  ];
  const tools: [string, string, boolean, () => void][] = [
    ["✥", "Hand tool  H", panTool, () => setPanTool(!panTool)],
    ["⬚", "Box zoom  Z", captureMode === "zoom", mode("zoom")],
    ["⊞", "Fixed Size Zoom  F", captureMode === "fixed-zoom", mode("fixed-zoom")],
    ["↔", "Distance  D", captureMode === "distance", mode("distance")],
    ["∿", "Line profile  L", captureMode === "profile", mode("profile")],
    ["⧈", "Box profile (integrated)  B", captureMode === "box-profile", mode("box-profile")],
    ["⌇", "Polyline  P", captureMode === "polyline", mode("polyline")],
    ["∠", "Angle  G", captureMode === "angle", mode("angle")],
    ["▭", "ROI stats  R", captureMode === "roi", mode("roi")],
    ["📏", "Calibrate scale", captureMode === "calibrate", mode("calibrate")],
  ];

  // split a "Label  KEY" toolbar title into [label, shortcut] for the hover
  // tooltip (titles without a trailing 2-space + token return [title, null])
  const splitTip = (s: string): [string, string | null] => {
    const m = /^(.*?)\s{2,}(\S.*)$/.exec(s);
    return m ? [m[1], m[2]] : [s, null];
  };

  return (
    <div
      className="fvd-glass fvd-float-tools"
      onPointerDown={(e) => e.stopPropagation()}
    >
      {transforms.map(([glyph, title, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className="fvd-tool-btn"
            data-tip={label}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            {glyph}
          </button>
        );
      })}
      <span className="fvd-tool-sep" />
      {tools.map(([glyph, title, active, onClick]) => {
        const [label, hint] = splitTip(title);
        return (
          <button
            key={title}
            className={`fvd-tool-btn${active ? " active" : ""}`}
            data-tip={label}
            data-tip-key={hint ?? undefined}
            onClick={onClick}
          >
            {glyph}
          </button>
        );
      })}
      <span className="fvd-tool-sep" />
      <button
        className="fvd-tool-btn"
        data-tip="Crop to ROI"
        onClick={() => cropToRoi()}
      >
        ✂
      </button>
      <button
        className={`fvd-tool-btn${captureMode === "crop-save" ? " active" : ""}`}
        data-tip="Save Cropped Region"
        onClick={mode("crop-save")}
      >
        ⊡
      </button>
      <span className="fvd-tool-sep" />
      {hasMeasures && (
        <button
          className="fvd-tool-btn"
          data-tip="Delete last annotation"
          onClick={() => { if (activeId) deleteLastAnnotation(activeId); }}
        >
          ⌫
        </button>
      )}
      {isDerived && (
        <button
          className="fvd-tool-btn"
          data-tip="Reset to original pixels"
          onClick={() => { if (activeId) resetToOriginal(activeId); }}
        >
          ⟳₀
        </button>
      )}
    </div>
  );
}

function GrainEditBar({
  mode,
  setMode,
  pending,
}: {
  mode: "off" | "merge" | "split";
  setMode: (m: "off" | "merge" | "split") => void;
  pending: Pt | null;
}) {
  const hint =
    mode === "merge"
      ? pending
        ? "click the 2nd grain"
        : "click the 1st grain"
      : mode === "split"
        ? "click a grain to split"
        : "";
  return (
    <div
      className="fvd-glass fvd-grain-edit"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <span className="lbl">Grains</span>
      <div className="fvd-seg">
        <button
          className={`fvd-seg-btn${mode === "merge" ? " active" : ""}`}
          title="Merge — click two grains"
          onClick={() => setMode(mode === "merge" ? "off" : "merge")}
        >
          Merge
        </button>
        <button
          className={`fvd-seg-btn${mode === "split" ? " active" : ""}`}
          title="Split — click a grain"
          onClick={() => setMode(mode === "split" ? "off" : "split")}
        >
          Split
        </button>
      </div>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function ZoomChip({ onZoom }: { onZoom: (f: number) => void }) {
  const zoom = useStageInfo((s) => s.zoom);
  if (zoom === null) return null;
  return (
    <div className="fvd-glass fvd-zoom-chip">
      <button className="fvd-icon-btn" onClick={() => onZoom(0.8)}>
        ⊖
      </button>
      <span>{Math.round(zoom * 100)} %</span>
      <button className="fvd-icon-btn" onClick={() => onZoom(1.25)}>
        ⊕
      </button>
    </div>
  );
}

function Readout() {
  const cursor = useStageInfo((s) => s.cursor);
  const raster = useStageInfo((s) => s.raster);
  if (!cursor) return null;
  const v = rasterValue(raster, cursor.x, cursor.y);
  return (
    <div className="fvd-glass fvd-readout">
      {Math.floor(cursor.x)}, {Math.floor(cursor.y)}
      {v !== null && ` · ${Number(v.toPrecision(5))}`}
    </div>
  );
}

// ── Fixed-size zoom badge (item #41 A2) ──────────────────────────────

function FixedZoomBadge({ w, h }: { w: number; h: number }) {
  const setFixedZoomDims = useViewer((s) => s.setFixedZoomDims);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const [wStr, setWStr] = useState(String(w));
  const [hStr, setHStr] = useState(String(h));

  const apply = () => {
    const nw = Math.max(1, parseInt(wStr) || w);
    const nh = Math.max(1, parseInt(hStr) || h);
    setFixedZoomDims(nw, nh);
  };

  return (
    <div className="fvd-glass fvd-fixed-zoom-badge">
      <span>Fixed Zoom</span>
      <input
        value={wStr}
        style={{ width: 44 }}
        onChange={(e) => setWStr(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            apply();
            e.stopPropagation();
          }
        }}
        placeholder="W"
        aria-label="Width in pixels"
      />
      <span>×</span>
      <input
        value={hStr}
        style={{ width: 44 }}
        onChange={(e) => setHStr(e.target.value)}
        onBlur={apply}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            apply();
            e.stopPropagation();
          }
        }}
        placeholder="H"
        aria-label="Height in pixels"
      />
      <span className="fvd-text-faint">px — click to place</span>
      <button
        className="fvd-icon-btn"
        title="Cancel"
        onClick={() => setCaptureMode("none")}
      >
        ✕
      </button>
    </div>
  );
}

// ── Stack frame stepper overlay (item #40 / D11) ─────────────────────

function StackStepper({
  imageId: _imageId,
  frame,
  total,
  onStep,
}: {
  imageId: string;
  frame: number;
  total: number;
  onStep: (delta: number) => void;
}) {
  return (
    <div className="fvd-glass fvd-stack-stepper">
      <button
        className="fvd-icon-btn"
        disabled={frame <= 0}
        onClick={(e) => {
          e.stopPropagation();
          onStep(-1);
        }}
        title="Previous frame  ,"
      >
        ◀
      </button>
      <span className="fvd-stack-label">
        {frame + 1} / {total}
      </span>
      <button
        className="fvd-icon-btn"
        disabled={frame >= total - 1}
        onClick={(e) => {
          e.stopPropagation();
          onStep(1);
        }}
        title="Next frame  ."
      >
        ▶
      </button>
    </div>
  );
}
