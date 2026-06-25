// Side-by-side compare (MATLAB parity, generalized to an N-pane grid): each
// pane is independently scrollable through its bound group's images (or every
// loaded image when unbound). Click a pane to focus it (cyan border) — the
// focused pane is what the ←/→ keys and ◀ ▶ buttons drive, so the others stay
// frozen; Tab cycles focus through the grid. Each pane has its own image +
// group dropdown, measurement overlay, scale bar, and contrast/colormap.
//
// Zoom is LINKED by default — wheel-zoom one pane and every other pane matches
// its magnification (each keeps its own pan, so you can compare the same zoom
// at different regions). The 🔗 toggle unlocks it. Pan + fit are per-pane.

import { useEffect, useRef, useState } from "react";

import { GLRenderer } from "../../gl/render";
import { fetchData16 } from "../../lib/api";
import { buildLut } from "../../lib/colormaps";
import { fitView, zoomAbout, type Size } from "../../lib/geometry";
import { groupMembers } from "../../lib/groups";
import { nextGridViews, type ViewChange } from "../../lib/sbsView";
import { DEFAULT_DISPLAY, useViewer, type View } from "../../store/viewer";
import MeasureOverlay from "./MeasureOverlay";
import ScaleBarOverlay from "./ScaleBarOverlay";

const WHEEL_K = 0.0015;

export default function SideBySideStage() {
  const sbsPanes = useViewer((s) => s.sbsPanes);
  const sbsRows = useViewer((s) => s.sbsRows);
  const sbsCols = useViewer((s) => s.sbsCols);
  const sbsActive = useViewer((s) => s.sbsActive);
  const sbsLinked = useViewer((s) => s.sbsLinked);
  const setSbsLinked = useViewer((s) => s.setSbsLinked);
  const exitCompare = useViewer((s) => s.exitCompare);

  // Per-pane views, indexed parallel to sbsPanes. A ref mirrors the state so
  // the coupling math always reads the latest values regardless of render
  // timing. Both are kept length-synced to the pane count.
  const [views, setViews] = useState<(View | null)[]>([]);
  const viewsRef = useRef<(View | null)[]>([]);

  useEffect(() => {
    // grow/shrink the view arrays to match the grid (preserve by index)
    const n = sbsPanes.length;
    const next = Array.from({ length: n }, (_, i) => viewsRef.current[i] ?? null);
    viewsRef.current = next;
    setViews(next);
  }, [sbsPanes.length]);

  const applyView = (idx: number, v: View, kind: ViewChange) => {
    const next = nextGridViews(idx, v, kind, viewsRef.current, sbsLinked);
    viewsRef.current = next;
    setViews(next);
  };

  const anyImage = sbsPanes.some((p) => p.imageId);
  if (!anyImage) {
    return (
      <div className="fvd-stage fvd-compare grid sidebyside">
        <div className="fvd-stage-empty">Side-by-side needs an open image.</div>
      </div>
    );
  }

  return (
    <div
      className="fvd-stage fvd-compare grid sidebyside"
      style={{
        gridTemplateColumns: `repeat(${sbsCols}, 1fr)`,
        gridTemplateRows: `repeat(${sbsRows}, 1fr)`,
      }}
    >
      {sbsPanes.map((pane, idx) => (
        <SbsPaneView
          key={idx}
          idx={idx}
          paneImageId={pane.imageId}
          groupId={pane.groupId}
          active={sbsActive === idx}
          view={views[idx] ?? null}
          onView={(v, kind) => applyView(idx, v, kind)}
        />
      ))}
      <div className="fvd-glass fvd-compare-chip">
        Side-by-side
        <button
          className={`fvd-icon-btn${sbsLinked ? " active" : ""}`}
          title={
            sbsLinked
              ? "Zoom linked — click to unlock"
              : "Zoom independent — click to link"
          }
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
  idx,
  paneImageId,
  groupId,
  active,
  view,
  onView,
}: {
  idx: number;
  paneImageId: string | null;
  groupId: string | null;
  active: boolean;
  view: View | null;
  onView: (v: View, kind: ViewChange) => void;
}) {
  const images = useViewer((s) => s.images);
  const order = useViewer((s) => s.order);
  const imageGroups = useViewer((s) => s.imageGroups);
  const id = paneImageId;
  const meta = id ? images[id] : undefined;
  const display = useViewer((s) =>
    id ? (s.display[id] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const setPaneImage = useViewer((s) => s.setPaneImage);
  const setPaneGroup = useViewer((s) => s.setPaneGroup);
  const stepPane = useViewer((s) => s.stepPane);
  const setActivePane = useViewer((s) => s.setActivePane);

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
  // the image list this pane scrolls: its bound group's live members, or all
  const members = groupMembers(imageGroups, images, order, groupId);
  const idxInMembers = id ? members.indexOf(id) : -1;

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
    if (!id) {
      setLoaded(false);
      glRef.current?.clear();
      return;
    }
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
    if (!el || !id) return;
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
        "zoom",
      );
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [effView, vp, img, onView, id]);

  const onPointerDown = (e: React.PointerEvent) => {
    setActivePane(idx); // clicking a pane focuses it (freezes the others)
    if (!id || (e.button !== 0 && e.button !== 1)) return;
    dragRef.current = { x: e.clientX, y: e.clientY };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.x;
    const dy = e.clientY - dragRef.current.y;
    dragRef.current = { x: e.clientX, y: e.clientY };
    onView(
      {
        ...effView,
        px: effView.px - dx / (effView.z * img.w),
        py: effView.py - dy / (effView.z * img.h),
      },
      "pan",
    );
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const cls = ["fvd-compare-panel", "sbs", active ? "active" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls} onPointerDownCapture={() => setActivePane(idx)}>
      <div className="fvd-sbs-bar">
        <select
          className="fvd-sbs-group"
          value={groupId ?? ""}
          title="Bind a named group to this pane"
          onChange={(e) => setPaneGroup(idx, e.target.value || null)}
        >
          <option value="">All images</option>
          {imageGroups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <button
          className="fvd-icon-btn"
          title="Previous image"
          disabled={members.length === 0}
          onClick={() => stepPane(idx, -1)}
        >
          ◀
        </button>
        <select
          className="fvd-sbs-select"
          value={id ?? ""}
          title={meta?.name}
          disabled={members.length === 0}
          onChange={(e) => setPaneImage(idx, e.target.value)}
        >
          {id && idxInMembers === -1 && (
            // current image isn't in the bound group — keep it selectable
            <option value={id}>{meta?.name ?? id}</option>
          )}
          {members.map((mid, i) => (
            <option key={mid} value={mid}>
              {i + 1}/{members.length} · {images[mid]?.name ?? mid}
            </option>
          ))}
        </select>
        <button
          className="fvd-icon-btn"
          title="Next image"
          disabled={members.length === 0}
          onClick={() => stepPane(idx, 1)}
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
        onDoubleClick={() => id && onView(fitView(img, vp), "fit")}
      >
        <canvas ref={canvasRef} />
        {!id && <div className="fvd-stage-empty">Pick an image</div>}
        {id && vp.w > 0 && (
          <MeasureOverlay
            imageId={id}
            pixelSize={meta?.pixel_size ?? null}
            pixelUnit={meta?.pixel_unit ?? "px"}
            view={effView}
            img={img}
            vp={vp}
            pending={null}
          />
        )}
        {id && meta?.pixel_size != null && vp.w > 0 && (
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
        {id && (
          <div className="fvd-glass fvd-panel-label">
            {idxInMembers >= 0 ? `${idxInMembers + 1}/${members.length}` : ""} ·{" "}
            {meta?.name ?? id}
          </div>
        )}
      </div>
    </div>
  );
}
