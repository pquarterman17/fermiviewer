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
import { type Raster16 } from "../../lib/api";
import { buildLabelLut, buildLut } from "../../lib/colormaps";
import { imageToScreen, zoomAbout, type Size } from "../../lib/geometry";
import { useBrowseScale } from "../../store/browseScale";
import { useScribble } from "../../store/scribble";
import { useStageInfo } from "../../store/stage";
import {
  DEFAULT_DISPLAY,
  useViewer,
  type Measure,
  type View,
} from "../../store/viewer";
import CaptureBanner from "./CaptureBanner";
import DockPlot from "./DockPlot";
import EmptyStage from "./EmptyStage";
import { FloatTools, ZoomChip } from "./FloatTools";
import FourDProbeMarker from "./FourDProbeMarker";
import LayersOverlay from "./LayersOverlay";
import MaskPreviewOverlay from "./MaskPreviewOverlay";
import MeasureOverlay from "./MeasureOverlay";
import RegionOverlay from "./RegionOverlay";
import Minimap from "./Minimap";
import ScaleBarOverlay from "./ScaleBarOverlay";
import ScaleLockChip from "./ScaleLockChip";
import ScribbleOverlay from "./ScribbleOverlay";
import SpectrumProbeMarker from "./SpectrumProbeMarker";
import { ScaleBarCtxMenu, type CtxTarget } from "./StageCtxMenu";
import {
  FixedZoomBadge,
  GrainEditBar,
  Readout,
  StackStepper,
} from "./StageChrome";
import {
  makeFinalizeBoxProfile,
  makeFinalizeCalibration,
  makeFinalizeMeasure,
  type FinalizerCtx,
} from "./stageFinalizers";
import { defaultStageView, fitAndReseedScale } from "./stageScaleLock";
import { transformU16, WHEEL_K, type Pt } from "./stageUtils";
import { useStageImageLoad } from "./useStageImageLoad";
import { useStagePointers, type StagePointersCtx } from "./useStagePointers";

export interface StageHandle {
  fit: () => void;
  actualSize: () => void;
  zoomBy: (factor: number) => void;
  nudge: (dx: number, dy: number) => void;
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
  // -1 = the energy SUM view (the sensible cube overview). Defaulting to a
  // channel index showed channel 0 (~0 keV, empty for EDS) as a black stage
  // while the filmstrip's summed /render looked fine.
  const stackFrame = useViewer((s) =>
    s.activeId ? (s.stackFrames[s.activeId] ?? -1) : -1,
  );
  const setStackFrame = useViewer((s) => s.setStackFrame);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const setSpecnavPixel = useViewer((s) => s.setSpecnavPixel);
  const specnavPixel = useViewer((s) => s.specnavPixel);
  const setFourdNavPixel = useViewer((s) => s.setFourdNavPixel);
  const fourdNavPixel = useViewer((s) => s.fourdNavPixel);
  const fixedZoomW = useViewer((s) => s.fixedZoomW);
  const fixedZoomH = useViewer((s) => s.fixedZoomH);
  const panTool = useViewer((s) => s.panTool);
  const addMeasure = useViewer((s) => s.addMeasure);
  const setRoiStats = useViewer((s) => s.setRoiStats);
  const setStatus = useViewer((s) => s.setStatus);
  const setCursor = useStageInfo((s) => s.setCursor);
  const setZoom = useStageInfo((s) => s.setZoom);
  const setProfile = useStageInfo((s) => s.setProfile);
  // constant-physical-scale lock (item 8) — global, not per-image
  const scaleLocked = useBrowseScale((s) => s.locked);
  const lockedScale = useBrowseScale((s) => s.scale);
  const reseedScale = useBrowseScale((s) => s.reseed);

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
  const specnavRef = useRef(false); // dragging in specnav mode (#10)
  const fourdnavRef = useRef(false); // dragging in fourdnav mode (#14)
  const rasterRef = useRef<Raster16 | null>(null);

  const rasterless = meta?.kind === "spectrum";
  // a grain-label map (tagged by the grain analysis) is interactively
  // editable on the stage — click grains to merge/split
  const isGrainMap = Boolean(meta?.meta?.["grain_labels"]);
  // true while the trained-mode paint panel is open on THIS image
  const paintActive = scribbleActive && scribbleImageId === activeId;
  const view: View | null = defaultStageView(
    storedView,
    imgSize,
    vp,
    meta?.pixel_size ?? null,
    { locked: scaleLocked, scale: lockedScale },
  );

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
        .setStatus(
          `GPU image rendering unavailable: ${(err as Error).message}`,
        );
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
  // Owns the fetch, the GPU upload and the first-load display seeding; it
  // re-fetches when the stack frame index changes.
  useStageImageLoad({
    glRef,
    rasterRef,
    setImgSize,
    setPending,
    setNFrames,
  });

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
    glRef.current.setImage16(transformU16(r.data, display.transform), r.w, r.h);
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
        setStackFrame(activeId, Math.max(-1, stackFrame - 1)); // -1 = sum
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
        if (!imgSize) return;
        const { view: v, reseedTo } = fitAndReseedScale(
          imgSize,
          vp,
          meta?.pixel_size ?? null,
          scaleLocked,
        );
        apply(v);
        if (reseedTo != null) reseedScale(reseedTo);
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
    [imgSize, vp, view, apply, meta?.pixel_size, scaleLocked, reseedScale],
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

  const finalizerCtx: FinalizerCtx = {
    activeId,
    imgSize,
    setCaptureMode,
    addMeasure,
    setProfile,
    setStatus,
    setRoiStats,
  };
  const finalizeMeasure = makeFinalizeMeasure(finalizerCtx);
  const finalizeCalibration = makeFinalizeCalibration(finalizerCtx);
  const finalizeBoxProfile = makeFinalizeBoxProfile(finalizerCtx);

  const pointersCtx: StagePointersCtx = {
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
  };
  const {
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onDoubleClick,
    onContextMenu,
  } = useStagePointers(pointersCtx);

  const cls = [
    "fvd-stage",
    captureMode === "fixed-zoom"
      ? "box-zoom"
      : captureMode !== "none"
        ? "box-zoom"
        : "",
    panning ? "panning" : panTool || spaceHeld ? "pan-ready" : "",
  ]
    .filter(Boolean)
    .join(" ");

  // screen-space marker for the first grain picked in a pending merge
  const grainMarkPos =
    isGrainMap && grainMode === "merge" && grainPending && view && imgSize
      ? imageToScreen(grainPending.x, grainPending.y, view, imgSize, vp)
      : null;

  // screen-space crosshair for the specnav-picked pixel (#10); the 1-based
  // [row, col] pixel's centre is at image coords (col − 0.5, row − 0.5)
  const specnavMarkPos =
    captureMode === "specnav" && specnavPixel && view && imgSize
      ? imageToScreen(
          specnavPixel[1] - 0.5,
          specnavPixel[0] - 0.5,
          view,
          imgSize,
          vp,
        )
      : null;

  // screen-space crosshair for the fourdnav-picked pixel (#14) — same
  // convention as specnavMarkPos above, for the 4D-STEM probe instead.
  const fourdNavMarkPos =
    captureMode === "fourdnav" && fourdNavPixel && view && imgSize
      ? imageToScreen(fourdNavPixel[1] - 0.5, fourdNavPixel[0] - 0.5, view, imgSize, vp)
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

      {!activeId && <EmptyStage />}
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
          <RegionOverlay imageId={activeId} view={view} img={imgSize} vp={vp} />
          <MaskPreviewOverlay imageId={activeId} view={view} img={imgSize} vp={vp} />
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
          <LayersOverlay imageId={activeId} view={view} img={imgSize} vp={vp} />
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
          {specnavMarkPos && specnavPixel && (
            <SpectrumProbeMarker position={specnavMarkPos} pixel={specnavPixel} viewport={vp} />
          )}
          {fourdNavMarkPos && fourdNavPixel && (
            <FourDProbeMarker position={fourdNavMarkPos} pixel={fourdNavPixel} viewport={vp} />
          )}
          <Minimap
            imageId={activeId}
            view={view}
            img={imgSize}
            vp={vp}
            onNavigate={apply}
          />
          <ScaleLockChip />
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
            const next = Math.min(
              nFrames - 1,
              Math.max(-1, stackFrame + delta),
            );
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
