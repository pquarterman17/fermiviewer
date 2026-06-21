// Side-by-side compare (MATLAB parity): two panes, each independently
// scrollable through the loaded images. Click a pane to focus it (cyan
// border) — the focused pane is what the ←/→ keys and ◀ ▶ buttons drive,
// so the other pane stays frozen. Each pane has its own image dropdown,
// scale bar, contrast/colormap, and (optionally linked) pan/zoom.

import { useEffect, useRef, useState } from "react";

import { GLRenderer } from "../../gl/render";
import { fetchData16 } from "../../lib/api";
import { buildLut } from "../../lib/colormaps";
import { fitView, zoomAbout, type Size } from "../../lib/geometry";
import {
  DEFAULT_DISPLAY,
  useViewer,
  type SbsPane as Pane,
  type View,
} from "../../store/viewer";
import ScaleBarOverlay from "./ScaleBarOverlay";

const WHEEL_K = 0.0015;

export default function SideBySideStage() {
  const sbsLeft = useViewer((s) => s.sbsLeft);
  const sbsRight = useViewer((s) => s.sbsRight);
  const sbsActive = useViewer((s) => s.sbsActive);
  const sbsLinked = useViewer((s) => s.sbsLinked);
  const setSbsLinked = useViewer((s) => s.setSbsLinked);
  const exitCompare = useViewer((s) => s.exitCompare);

  // Per-pane view. When linked, an update to one pane writes BOTH so the
  // two stay in lock-step; when unlinked each keeps its own transform.
  const [viewL, setViewL] = useState<View | null>(null);
  const [viewR, setViewR] = useState<View | null>(null);

  const applyView = (pane: Pane, v: View) => {
    if (sbsLinked) {
      setViewL(v);
      setViewR(v);
    } else if (pane === "L") {
      setViewL(v);
    } else {
      setViewR(v);
    }
  };

  if (!sbsLeft || !sbsRight) {
    return (
      <div className="fvd-stage fvd-compare sidebyside">
        <div className="fvd-stage-empty">Side-by-side needs an open image.</div>
      </div>
    );
  }

  return (
    <div className="fvd-stage fvd-compare sidebyside">
      <SbsPaneView
        id={sbsLeft}
        pane="L"
        active={sbsActive === "L"}
        view={viewL}
        onView={(v) => applyView("L", v)}
      />
      <SbsPaneView
        id={sbsRight}
        pane="R"
        active={sbsActive === "R"}
        view={viewR}
        onView={(v) => applyView("R", v)}
      />
      <div className="fvd-glass fvd-compare-chip">
        Side-by-side
        <button
          className={`fvd-icon-btn${sbsLinked ? " active" : ""}`}
          title={sbsLinked ? "Zoom/pan linked — click to unlink" : "Zoom/pan independent — click to link"}
          onClick={() => setSbsLinked(!sbsLinked)}
        >
          {sbsLinked ? "🔗" : "⛓️‍💥"}
        </button>
        <button className="fvd-icon-btn" title="Exit compare  Esc" onClick={exitCompare}>
          ✕
        </button>
      </div>
    </div>
  );
}

function SbsPaneView({
  id,
  pane,
  active,
  view,
  onView,
}: {
  id: string;
  pane: Pane;
  active: boolean;
  view: View | null;
  onView: (v: View) => void;
}) {
  const images = useViewer((s) => s.images);
  const meta = images[id];
  const order = useViewer((s) => s.order);
  const display = useViewer((s) => s.display[id] ?? DEFAULT_DISPLAY);
  const setStatus = useViewer((s) => s.setStatus);
  const setSbsPane = useViewer((s) => s.setSbsPane);
  const stepSbs = useViewer((s) => s.stepSbs);
  const setSbsActive = useViewer((s) => s.setSbsActive);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const barRef = useRef<HTMLDivElement>(null) as React.RefObject<HTMLDivElement>;
  const glRef = useRef<GLRenderer | null>(null);
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const [loaded, setLoaded] = useState(false);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

  // raster dims from meta ([h, w] or [h, w, ch] for SI cubes)
  const img: Size = meta
    ? { w: meta.shape[1] ?? 1, h: meta.shape[0] ?? 1 }
    : { w: 1, h: 1 };
  const effView = view ?? fitView(img, vp);
  const idx = order.indexOf(id);

  useEffect(() => {
    if (!canvasRef.current) return;
    let gl: GLRenderer;
    try {
      gl = new GLRenderer(canvasRef.current);
    } catch (err) {
      setStatus(`GPU image rendering unavailable: ${(err as Error).message}`);
      return;
    }
    glRef.current = gl;
    return () => {
      gl.dispose();
      glRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setVp({ w: el.clientWidth, h: el.clientHeight });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // (re)load whenever the pane's image changes
  useEffect(() => {
    let alive = true;
    setLoaded(false);
    fetchData16(id)
      .then((r) => {
        if (!alive || !glRef.current) return;
        glRef.current.setImage16(r.data, r.w, r.h);
        setLoaded(true);
      })
      .catch((e: Error) => setStatus(`compare load failed: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [id, setStatus]);

  useEffect(() => {
    glRef.current?.setLut(buildLut(display.cmap));
  }, [display.cmap, loaded]);

  useEffect(() => {
    if (!glRef.current || vp.w === 0 || !loaded) return;
    glRef.current.draw(effView, vp, window.devicePixelRatio || 1, {
      lo: display.lo,
      hi: display.hi,
      gamma: display.gamma,
      invert: display.invert,
    });
  }, [effView, vp, display, loaded]);

  // wheel zoom about the cursor (native listener: needs preventDefault)
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      onView(
        zoomAbout(
          effView,
          Math.exp(-e.deltaY * WHEEL_K),
          e.clientX - r.left,
          e.clientY - r.top,
          img,
          vp,
        ),
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [effView, vp, img, onView]);

  const onPointerDown = (e: React.PointerEvent) => {
    setSbsActive(pane); // clicking a pane focuses it (freezes the other)
    if (e.button !== 0 && e.button !== 1) return;
    dragRef.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.x;
    const dy = e.clientY - dragRef.current.y;
    dragRef.current = { x: e.clientX, y: e.clientY };
    onView({
      ...effView,
      px: effView.px - dx / (effView.z * img.w),
      py: effView.py - dy / (effView.z * img.h),
    });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const cls = ["fvd-compare-panel", "sbs", active ? "active" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls}>
      <div className="fvd-sbs-bar">
        <button
          className="fvd-icon-btn"
          title="Previous image"
          onClick={() => stepSbs(pane, -1)}
        >
          ◀
        </button>
        <select
          className="fvd-sbs-select"
          value={id}
          title={meta?.name}
          onChange={(e) => setSbsPane(pane, e.target.value)}
        >
          {order.map((oid, i) => (
            <option key={oid} value={oid}>
              {i + 1}/{order.length} · {images[oid]?.name ?? oid}
            </option>
          ))}
        </select>
        <button
          className="fvd-icon-btn"
          title="Next image"
          onClick={() => stepSbs(pane, 1)}
        >
          ▶
        </button>
      </div>
      <div
        ref={wrapRef}
        className="fvd-sbs-canvas-wrap"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onDoubleClick={() => onView(fitView(img, vp))}
      >
        <canvas ref={canvasRef} />
        {meta?.pixel_size != null && vp.w > 0 && (
          <ScaleBarOverlay
            imageId={id}
            pixelSize={meta.pixel_size}
            unit={meta.pixel_unit}
            view={effView}
            img={img}
            vp={vp}
            barRef={barRef}
          />
        )}
        <div className="fvd-glass fvd-panel-label">
          {idx >= 0 ? `${idx + 1}/${order.length}` : ""} · {meta?.name ?? id}
        </div>
      </div>
    </div>
  );
}
