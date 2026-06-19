// Compare mode (handoff §4 Inspector · Compare, §9): the stage splits
// into N linked panels. One shared {z,px,py} drives every panel, so
// zoom/pan linkage is inherent. Split = side-by-side grid; Flicker =
// timed A/B/… visibility cycle; Subtract = stacked canvases with CSS
// mix-blend-mode: difference.

import { useEffect, useRef, useState } from "react";

import { GLRenderer } from "../../gl/render";
import { fetchData16 } from "../../lib/api";
import { buildLut } from "../../lib/colormaps";
import { fitView, zoomAbout, type Size } from "../../lib/geometry";
import {
  DEFAULT_DISPLAY,
  useViewer,
  type View,
} from "../../store/viewer";

const WHEEL_K = 0.0015;

export default function CompareStage() {
  const compareSet = useViewer((s) => s.compareSet) ?? [];
  const compareMode = useViewer((s) => s.compareMode);
  const compareFlickerMs = useViewer((s) => s.compareFlickerMs);
  const compareAB = useViewer((s) => s.compareAB);
  const images = useViewer((s) => s.images);
  const exitCompare = useViewer((s) => s.exitCompare);

  const [view, setView] = useState<View | null>(null);
  const [vp, setVp] = useState<Size>({ w: 0, h: 0 });
  const [tick, setTick] = useState(0);

  const first = images[compareSet[0]];
  // raster dims from meta ([h, w] or [h, w, ch] for SI cubes)
  const img: Size = first
    ? { w: first.shape[1] ?? 1, h: first.shape[0] ?? 1 }
    : { w: 1, h: 1 };

  const effView = view ?? fitView(img, vp);

  // flicker cycle — restarts when mode or interval changes
  useEffect(() => {
    if (compareMode !== "flicker") return;
    const t = window.setInterval(() => setTick((x) => x + 1), compareFlickerMs);
    return () => window.clearInterval(t);
  }, [compareMode, compareFlickerMs]);

  // Determine which images are visible.  When an explicit A/B pair is set,
  // flicker alternates between exactly those two; otherwise cycle the full set.
  const activeSet =
    compareAB !== null
      ? [
          compareSet[compareAB[0]] ?? compareSet[0],
          compareSet[compareAB[1]] ?? compareSet[1],
        ].filter(Boolean)
      : compareSet;

  const stacked = compareMode !== "split";
  const visibleIdx = tick % Math.max(1, activeSet.length);

  // When Tab key is pressed in flicker mode, advance the visible slot
  // (audit #15 active-panel focus + Tab-switch).
  useEffect(() => {
    if (compareMode !== "flicker") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Tab") {
        e.preventDefault();
        setTick((x) => x + 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [compareMode]);

  return (
    <div
      className={`fvd-stage fvd-compare ${compareMode}`}
      style={
        compareMode === "split"
          ? { gridTemplateColumns: `repeat(${activeSet.length}, 1fr)` }
          : undefined
      }
    >
      {activeSet.map((id, i) => (
        <ComparePanel
          key={id}
          id={id}
          name={images[id]?.name ?? id}
          view={effView}
          setView={setView}
          img={img}
          stacked={stacked}
          blend={compareMode === "subtract" && i > 0}
          hidden={compareMode === "flicker" && i !== visibleIdx}
          reportVp={i === 0 ? setVp : undefined}
        />
      ))}
      <div className="fvd-glass fvd-compare-chip">
        {compareMode === "flicker"
          ? `Flicker — ${images[activeSet[visibleIdx]]?.name ?? ""}`
          : compareMode === "subtract"
            ? "Subtract (difference)"
            : `Compare ${activeSet.length}`}
        <button
          className="fvd-icon-btn"
          title="Exit compare  Esc"
          onClick={exitCompare}
        >
          ✕
        </button>
      </div>
    </div>
  );
}

function ComparePanel({
  id,
  name,
  view,
  setView,
  img,
  stacked,
  blend,
  hidden,
  reportVp,
}: {
  id: string;
  name: string;
  view: View;
  setView: (v: View) => void;
  img: Size;
  stacked: boolean;
  blend: boolean;
  hidden: boolean;
  reportVp?: (vp: Size) => void;
}) {
  const display = useViewer((s) => s.display[id] ?? DEFAULT_DISPLAY);
  const setStatus = useViewer((s) => s.setStatus);

  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const glRef = useRef<GLRenderer | null>(null);
  const [vp, setVpLocal] = useState<Size>({ w: 0, h: 0 });
  const [loaded, setLoaded] = useState(false);
  const dragRef = useRef<{ x: number; y: number } | null>(null);

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
      const size = { w: el.clientWidth, h: el.clientHeight };
      setVpLocal(size);
      reportVp?.(size);
    });
    ro.observe(el);
    return () => ro.disconnect();
    // reportVp identity is stable enough (parent setState)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    glRef.current.draw(view, vp, window.devicePixelRatio || 1, {
      lo: display.lo,
      hi: display.hi,
      gamma: display.gamma,
      invert: display.invert,
    });
  }, [view, vp, display, loaded]);

  // ── linked pan/zoom (writes the shared view) ──
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      setView(
        zoomAbout(
          view,
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
  }, [view, vp, img, setView]);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    dragRef.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.x;
    const dy = e.clientY - dragRef.current.y;
    dragRef.current = { x: e.clientX, y: e.clientY };
    setView({
      ...view,
      px: view.px - dx / (view.z * img.w),
      py: view.py - dy / (view.z * img.h),
    });
  };

  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const onDoubleClick = () => setView(fitView(img, vp));

  const cls = [
    "fvd-compare-panel",
    stacked ? "stacked" : "",
    blend ? "blend" : "",
    hidden ? "hidden" : "",
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
      onDoubleClick={onDoubleClick}
    >
      <canvas ref={canvasRef} />
      {!stacked && <div className="fvd-glass fvd-panel-label">{name}</div>}
    </div>
  );
}
