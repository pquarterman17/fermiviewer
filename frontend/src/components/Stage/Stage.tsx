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
import ColorbarChip from "./ColorbarChip";
import DockPlot from "./DockPlot";
import MeasureOverlay from "./MeasureOverlay";
import Minimap from "./Minimap";
import {
  ScaleBarCtxMenu,
  EmptyAreaCtxMenu,
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
const MEASURE_KINDS = ["distance", "profile", "angle", "roi"] as const;
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
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
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
  // in-progress click-capture (image-space pts; last pt tracks cursor)
  const [pending, setPending] = useState<{
    kind: Measure["kind"];
    pts: Pt[];
  } | null>(null);
  const dragRef = useRef<{ last: Pt } | null>(null);
  const rasterRef = useRef<Raster16 | null>(null);

  const rasterless = meta?.kind === "spectrum";
  const view: View | null = imgSize && (storedView ?? fitView(imgSize, vp));
  const isMeasureMode = (MEASURE_KINDS as readonly string[]).includes(
    captureMode,
  );

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
    let alive = true;
    fetchData16(activeId)
      .then((r) => {
        if (!alive || !glRef.current) return;
        glRef.current.setImage16(r.data, r.w, r.h);
        rasterRef.current = r;
        setRaster(r);
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
  }, [activeId, rasterless, setDisplay, setProfile, setRaster, setStatus]);

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

  // ── cancel pending capture when mode changes / esc ──
  useEffect(() => {
    if (!isMeasureMode) setPending(null);
  }, [isMeasureMode, captureMode]);

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
    if (kind === "profile") {
      measureProfile(activeId, ptsImg[0], ptsImg[1], width)
        .then((r) => setProfile({ ...r, measureId: mid }))
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "polyline") {
      measurePolyline(activeId, ptsImg, width)
        .then((r) => setProfile({ ...r, measureId: mid }))
        .catch((e: Error) => setStatus(e.message));
    } else if (kind === "roi" || kind === "ellipse") {
      measureRoi(activeId, ptsImg[0], ptsImg[1],
                 kind === "ellipse" ? "ellipse" : "rect")
        .then((r) => setRoiStats(mid, r))
        .catch((e: Error) => setStatus(e.message));
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

    if (
      captureMode === "zoom" ||
      captureMode === "roi" ||
      captureMode === "ellipse" ||
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
    if (target.kind === "measure" && target.measureId) {
      // delegate to MeasureOverlay's own ctx menu by selecting the measure
      // and synthesising a contextmenu event — instead, just open the
      // radial which is harmless, OR re-use our empty handler.
      // The measure's own onContextMenu handler (inside MeasureOverlay)
      // fires first because it stopPropagates — so this branch only runs
      // when the click missed all measure handles/labels. Treat as empty.
      setStageCtx({ kind: "empty", x: target.x, y: target.y });
    } else {
      setStageCtx(target);
    }
  };

  const cls = [
    "fvd-stage",
    captureMode !== "none" ? "box-zoom" : "",
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
              pixelSize={meta.pixel_size}
              unit={meta.pixel_unit}
              z={view.z}
              barRef={scaleBarRef}
            />
          )}
          <DockPlot />
        </>
      )}

      {stageCtx?.kind === "scalebar" && (
        <ScaleBarCtxMenu
          x={stageCtx.x}
          y={stageCtx.y}
          onClose={() => setStageCtx(null)}
        />
      )}
      {stageCtx?.kind === "empty" && (
        <EmptyAreaCtxMenu
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
    ["↔", "Distance  D", captureMode === "distance", mode("distance")],
    ["∿", "Line profile  L", captureMode === "profile", mode("profile")],
    ["⌇", "Polyline  P", captureMode === "polyline", mode("polyline")],
    ["∠", "Angle  G", captureMode === "angle", mode("angle")],
    ["▭", "ROI stats  R", captureMode === "roi", mode("roi")],
  ];

  return (
    <div className="fvd-glass fvd-float-tools">
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
  pixelSize,
  unit,
  z,
  barRef,
}: {
  pixelSize: number;
  unit: string;
  z: number;
  barRef: RefObject<HTMLDivElement>;
}) {
  const color = useViewer((s) => s.overlay.color);
  const visible = useViewer((s) => s.scaleBarVisible);
  const phys = niceScaleLength((120 * pixelSize) / z);
  const widthPx = (phys / pixelSize) * z;
  const label =
    phys >= 1 ? `${Number(phys.toPrecision(3))} ${unit}` : fmtSub(phys, unit);
  if (!visible) return null;
  return (
    <div ref={barRef} className="fvd-scalebar" style={{ color }}>
      <div className="bar" style={{ width: widthPx }} />
      <div className="label">{label}</div>
    </div>
  );
}

/** Render sub-unit lengths in the next unit down (0.5 nm → 500 pm style). */
function fmtSub(phys: number, unit: string): string {
  const down: Record<string, [string, number]> = {
    µm: ["nm", 1e3],
    um: ["nm", 1e3],
    nm: ["pm", 1e3],
  };
  const d = down[unit];
  if (d && phys * d[1] >= 1) {
    return `${Number((phys * d[1]).toPrecision(3))} ${d[0]}`;
  }
  return `${Number(phys.toPrecision(3))} ${unit}`;
}
