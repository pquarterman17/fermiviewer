// Central stage (handoff §4/§9): WebGL image render with pan / wheel-zoom
// about cursor / box-zoom marquee / fit / 100 %, floating glass tool-bar,
// zoom chip, cursor readout and scale bar.

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";

import { GLRenderer } from "../../gl/render";
import { renderUrl } from "../../lib/api";
import {
  clampZoom,
  fitView,
  niceScaleLength,
  screenToImage,
  viewForRect,
  zoomAbout,
  type Size,
} from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import { useViewer, type View } from "../../store/viewer";

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

const Stage = forwardRef<StageHandle>(function Stage(_props, handle) {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const storedView = useViewer((s) =>
    s.activeId ? (s.views[s.activeId] ?? null) : null,
  );
  const setView = useViewer((s) => s.setView);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const panTool = useViewer((s) => s.panTool);
  const setPanTool = useViewer((s) => s.setPanTool);
  const setStatus = useViewer((s) => s.setStatus);
  const setCursor = useStageInfo((s) => s.setCursor);
  const setZoom = useStageInfo((s) => s.setZoom);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<GLRenderer | null>(null);
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const [imgSize, setImgSize] = useState<Size | null>(null);
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [panning, setPanning] = useState(false);
  const [marquee, setMarquee] = useState<{ a: Pt; b: Pt } | null>(null);
  const dragRef = useRef<{ last: Pt } | null>(null);

  const rasterless = meta?.kind === "spectrum";
  const view: View | null =
    imgSize && (storedView ?? fitView(imgSize, vp));

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

  // ── load active image into the texture ──
  useEffect(() => {
    setImgSize(null);
    if (!activeId || rasterless) {
      glRef.current?.clear();
      return;
    }
    let alive = true;
    const img = new Image();
    img.onload = () => {
      if (!alive || !glRef.current) return;
      glRef.current.setImage(img);
      setImgSize({ w: img.naturalWidth, h: img.naturalHeight });
    };
    img.onerror = () => {
      if (alive) setStatus(`failed to render image ${activeId}`);
    };
    img.src = renderUrl(activeId);
    return () => {
      alive = false;
    };
  }, [activeId, rasterless, setStatus]);

  // ── draw on any view / size change ──
  useEffect(() => {
    if (!glRef.current || vp.w === 0) return;
    glRef.current.draw(
      view ?? { z: 1, px: 0.5, py: 0.5 },
      vp,
      window.devicePixelRatio || 1,
    );
  }, [view, vp, imgSize]);

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

  // ── pointer: pan / marquee / readout ──
  const local = (e: React.PointerEvent): Pt => {
    const r = wrapRef.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
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
    } else if (e.button === 0 && captureMode === "zoom") {
      setMarquee({ a: p, b: p });
      e.currentTarget.setPointerCapture(e.pointerId);
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
        z: view.z,
        px: view.px - (p.x - last.x) / (view.z * imgSize.w),
        py: view.py - (p.y - last.y) / (view.z * imgSize.h),
      });
      dragRef.current = { last: p };
    } else if (marquee) {
      setMarquee({ a: marquee.a, b: p });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    if (dragRef.current) {
      dragRef.current = null;
      setPanning(false);
    } else if (marquee && view && imgSize) {
      const a = screenToImage(marquee.a.x, marquee.a.y, view, imgSize, vp);
      const b = screenToImage(marquee.b.x, marquee.b.y, view, imgSize, vp);
      apply(viewForRect(a, b, imgSize, vp));
      setMarquee(null);
      setCaptureMode("none");
    }
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const onDoubleClick = () => {
    if (imgSize) apply(fitView(imgSize, vp));
  };

  const cls = [
    "fvd-stage",
    captureMode === "zoom" ? "box-zoom" : "",
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

      {activeId && !rasterless && (
        <>
          <FloatTools
            panTool={panTool}
            boxZoom={captureMode === "zoom"}
            onPan={() => setPanTool(!panTool)}
            onBoxZoom={() =>
              setCaptureMode(captureMode === "zoom" ? "none" : "zoom")
            }
            onZoom={(f) => {
              if (view && imgSize) {
                apply(
                  zoomAbout(
                    { ...view, z: clampZoom(view.z) },
                    f,
                    vp.w / 2,
                    vp.h / 2,
                    imgSize,
                    vp,
                  ),
                );
              }
            }}
            onFit={() => imgSize && apply(fitView(imgSize, vp))}
            onActual={() => view && apply({ ...view, z: 1 })}
          />
          <ZoomChip />
          <Readout />
          {meta?.pixel_size != null && view && (
            <ScaleBar
              pixelSize={meta.pixel_size}
              unit={meta.pixel_unit}
              z={view.z}
            />
          )}
        </>
      )}
    </div>
  );
});

export default Stage;

function FloatTools(props: {
  panTool: boolean;
  boxZoom: boolean;
  onPan: () => void;
  onBoxZoom: () => void;
  onZoom: (f: number) => void;
  onFit: () => void;
  onActual: () => void;
}) {
  return (
    <div className="fvd-glass fvd-float-tools">
      <button
        className={`fvd-tool-btn${props.panTool ? " active" : ""}`}
        title="Hand tool  H"
        onClick={props.onPan}
      >
        ✥
      </button>
      <button
        className={`fvd-tool-btn${props.boxZoom ? " active" : ""}`}
        title="Box zoom  Z"
        onClick={props.onBoxZoom}
      >
        ⬚
      </button>
      <button
        className="fvd-tool-btn"
        title="Zoom in  +"
        onClick={() => props.onZoom(1.25)}
      >
        +
      </button>
      <button
        className="fvd-tool-btn"
        title="Zoom out  −"
        onClick={() => props.onZoom(0.8)}
      >
        −
      </button>
      <button className="fvd-tool-btn" title="Fit  F" onClick={props.onFit}>
        ⤢
      </button>
      <button
        className="fvd-tool-btn"
        title="Actual size  1"
        onClick={props.onActual}
        style={{ width: 34 }}
      >
        1:1
      </button>
    </div>
  );
}

function ZoomChip() {
  const zoom = useStageInfo((s) => s.zoom);
  if (zoom === null) return null;
  return (
    <div className="fvd-glass fvd-zoom-chip">{Math.round(zoom * 100)} %</div>
  );
}

function Readout() {
  const cursor = useStageInfo((s) => s.cursor);
  if (!cursor) return null;
  return (
    <div className="fvd-glass fvd-readout">
      {Math.floor(cursor.x)}, {Math.floor(cursor.y)} px
    </div>
  );
}

function ScaleBar({
  pixelSize,
  unit,
  z,
}: {
  pixelSize: number;
  unit: string;
  z: number;
}) {
  // largest nice physical length that fits in ~120 css px
  const phys = niceScaleLength((120 * pixelSize) / z);
  const widthPx = (phys / pixelSize) * z;
  const label =
    phys >= 1 ? `${Number(phys.toPrecision(3))} ${unit}` : fmtSub(phys, unit);
  return (
    <div className="fvd-scalebar">
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
