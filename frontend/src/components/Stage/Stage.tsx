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
  measurePolyline,
  measureProfile,
  measureRoi,
  type Raster16,
} from "../../lib/api";
import { buildLut } from "../../lib/colormaps";
import {
  boxProfileLine,
  fitView,
  niceScaleLength,
  screenToImage,
  viewForRect,
  zoomAbout,
  type Size,
} from "../../lib/geometry";
import { applyGeometry, cropToRoi } from "../../lib/stageOps";
import { rasterValue, useStageInfo } from "../../store/stage";
import {
  DEFAULT_DISPLAY,
  useViewer,
  type Measure,
  type View,
} from "../../store/viewer";
import CaptureBanner from "./CaptureBanner";
import ColorbarChip from "./ColorbarChip";
import DockPlot from "./DockPlot";
import MeasureOverlay from "./MeasureOverlay";
import Minimap from "./Minimap";
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
};

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
  const [nFrames, setNFrames] = useState<number | null>(null);
  // in-progress click-capture (image-space pts; last pt tracks cursor)
  const [pending, setPending] = useState<{
    kind: Measure["kind"];
    pts: Pt[];
  } | null>(null);
  const dragRef = useRef<{ last: Pt } | null>(null);
  const rasterRef = useRef<Raster16 | null>(null);

  const rasterless = meta?.kind === "spectrum";
  const view: View | null = imgSize && (storedView ?? fitView(imgSize, vp));

  // ── renderer lifecycle ──
  useEffect(() => {
    if (!canvasRef.current) return;
    const gl = new GLRenderer(canvasRef.current);
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
          if (typeof dl === "number" && typeof dh === "number" && dh > dl) {
            const span = r.vmax - r.vmin || 1;
            setDisplay(activeId, {
              lo: Math.max(0, (dl - r.vmin) / span),
              hi: Math.min(1, (dh - r.vmin) / span),
              gamma: typeof dg === "number" && dg > 0 ? dg : 1,
              invert: di === true,
            });
          } else if (di === true) {
            setDisplay(activeId, { invert: true });
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
    glRef.current?.setLut(buildLut(display.cmap));
  }, [display.cmap, imgSize]);

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
      (captureMode === "none" && e.shiftKey) // marquee measure-select
    ) {
      setMarquee({ a: p, b: p });
      e.currentTarget.setPointerCapture(e.pointerId);
    } else if (captureMode in CLICKS) {
      const ip = toImage(p);
      const need = CLICKS[captureMode];
      const cur = pending?.pts ?? [];
      // replace the live cursor point with the committed click
      const committed = pending ? [...cur.slice(0, -1), ip] : [ip];
      if (committed.length >= need) {
        finalizeMeasure(captureMode as Measure["kind"], committed);
        setPending(null);
      } else {
        setPending({
          kind: captureMode as Measure["kind"],
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
      const ip = toImage(p);
      setPending({
        kind: pending.kind,
        pts: [...pending.pts.slice(0, -1), ip],
      });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
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
          <Minimap
            imageId={activeId}
            view={view}
            img={imgSize}
            vp={vp}
            onNavigate={apply}
          />
          <ColorbarChip />
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
              z={view.z}
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
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const panTool = useViewer((s) => s.panTool);
  const setPanTool = useViewer((s) => s.setPanTool);

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
  ];

  return (
    <div
      className="fvd-glass fvd-float-tools"
      onPointerDown={(e) => e.stopPropagation()}
    >
      {transforms.map(([glyph, title, onClick]) => (
        <button
          key={title}
          className="fvd-tool-btn"
          title={title}
          onClick={onClick}
        >
          {glyph}
        </button>
      ))}
      <span className="fvd-tool-sep" />
      {tools.map(([glyph, title, active, onClick]) => (
        <button
          key={title}
          className={`fvd-tool-btn${active ? " active" : ""}`}
          title={title}
          onClick={onClick}
        >
          {glyph}
        </button>
      ))}
      <span className="fvd-tool-sep" />
      <button
        className="fvd-tool-btn"
        title="Crop to ROI"
        onClick={() => cropToRoi()}
      >
        ✂
      </button>
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

function ScaleBarOverlay({
  imageId,
  pixelSize,
  unit,
  z,
  vp,
  barRef,
}: {
  imageId: string;
  pixelSize: number;
  unit: string;
  z: number;
  vp: Size;
  barRef: RefObject<HTMLDivElement>;
}) {
  // Scale bar is white by default, independent of the measurement
  // overlay colour (they used to share s.overlay.color, so picking a
  // measurement colour tinted the bar — decoupled per user request).
  const color = "#ffffff";
  const visible = useViewer((s) => s.scaleBarVisible);
  const sbState = useViewer((s) => s.scaleBars[imageId]);
  const setScaleBar = useViewer((s) => s.setScaleBar);
  const dragRef = useRef<{ startX: number; startY: number; x0: number; y0: number } | null>(null);

  if (!visible) return null;

  // position defaults: bottom-left (2% / 92% of viewport)
  const normX = sbState?.x ?? 0.02;
  const normY = sbState?.y ?? 0.92;
  const leftPx = normX * vp.w;
  const topPx = normY * vp.h;

  // size
  const autoPhys = niceScaleLength((120 * pixelSize) / z);
  const phys = sbState?.lengthPhys ?? autoPhys;
  const widthPx = (phys / pixelSize) * z;
  const thickness = sbState?.thickness ?? Math.max(2, Math.round(vp.h / 80));
  // default 20 (user request 2026-06-09 — readable at presentation size)
  const fontSize = sbState?.fontSize ?? 20;
  const label = phys >= 1
    ? `${Number(phys.toPrecision(3))} ${unit}`
    : fmtSub(phys, unit);

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    dragRef.current = { startX: e.clientX, startY: e.clientY, x0: normX, y0: normY };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current || vp.w === 0 || vp.h === 0) return;
    const dx = (e.clientX - dragRef.current.startX) / vp.w;
    const dy = (e.clientY - dragRef.current.startY) / vp.h;
    const nx = Math.min(0.98, Math.max(0, dragRef.current.x0 + dx));
    const ny = Math.min(0.98, Math.max(0, dragRef.current.y0 + dy));
    setScaleBar(imageId, { x: nx, y: ny });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
  };

  return (
    <div
      ref={barRef}
      className="fvd-scalebar fvd-scalebar-drag"
      style={{ color, left: leftPx, top: topPx, fontSize }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className="bar" style={{ width: widthPx, height: thickness }} />
      <div className="label">{label}</div>
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

/** Render sub-unit lengths in the next unit down (0.5 nm → 500 pm style). */
function fmtSub(phys: number, unit: string): string {
  // step down through the first sub-unit that lands ≥ 1; Å preferred
  // over pm for sub-nm lengths (EM convention)
  const chains: Record<string, [string, number][]> = {
    µm: [
      ["nm", 1e3],
      ["Å", 1e4],
    ],
    um: [
      ["nm", 1e3],
      ["Å", 1e4],
    ],
    nm: [
      ["Å", 10],
      ["pm", 1e3],
    ],
  };
  for (const [u, f] of chains[unit] ?? []) {
    if (phys * f >= 1) {
      return `${Number((phys * f).toPrecision(3))} ${u}`;
    }
  }
  return `${Number(phys.toPrecision(3))} ${unit}`;
}
