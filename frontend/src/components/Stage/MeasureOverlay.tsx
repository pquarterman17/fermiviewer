// Redraggable measurement overlay (handoff §4/§9): distance / profile /
// angle / ROI rendered at wrap level — handles stay constant-size at any
// zoom; labels live-update in calibrated units.

import { useRef, useState } from "react";

import { imageToScreen, type Size } from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import {
  OVERLAY_FONT_PX,
  useViewer,
  type Measure,
  type View,
} from "../../store/viewer";
import { ClosedShapeGlyph, closedShapeLabelAnchor } from "./closedShapeGlyph";
import MeasureCtxMenu from "./MeasureCtxMenu";
import { measureLabel } from "./measureGlyphs";
import { useVertexEditing, VertexHandles } from "./MeasureVertexLayer";
import { useMeasureRefresh } from "./useMeasureRefresh";

// stable empty result — a fresh [] per snapshot makes zustand's
// useSyncExternalStore loop forever (React #185, the black-screen bug)
const NO_MEASURES: Measure[] = [];

interface Props {
  imageId: string;
  pixelSize: number | null;
  pixelUnit: string;
  view: View;
  img: Size;
  vp: Size;
  /** in-progress capture preview (image-space points) */
  pending: { kind: Measure["kind"]; pts: { x: number; y: number }[] } | null;
}

export default function MeasureOverlay({
  imageId,
  pixelSize,
  pixelUnit,
  view,
  img,
  vp,
  pending,
}: Props) {
  const measures = useViewer((s) => s.measures[imageId] ?? NO_MEASURES);
  const selected = useViewer((s) => s.selectedMeasure);
  const overlay = useViewer((s) => s.overlay);
  const tilt = useViewer((s) => s.tilts[imageId] ?? null);
  const roiStats = useViewer((s) => s.roiStats);
  const updateMeasure = useViewer((s) => s.updateMeasure);
  const setSelected = useViewer((s) => s.setSelectedMeasure);
  const setRoiStats = useViewer((s) => s.setRoiStats);
  const setProfile = useStageInfo((s) => s.setProfile);
  const setStatus = useViewer((s) => s.setStatus);

  const labelDragRef = useRef<{
    mid: string;
    startX: number;
    startY: number;
    dx0: number;
    dy0: number;
  } | null>(null);
  const pushUndo = useViewer((s) => s.pushUndo);
  const setMeasureStyle = useViewer((s) => s.setMeasureStyle);
  const selectedMulti = useViewer((s) => s.selectedMulti);
  const [ctxMenu, setCtxMenu] = useState<{
    mid: string;
    x: number;
    y: number;
    /** which vertex was right-clicked (handle context-menu path only) —
     *  gates the "Delete vertex" item (MeasureCtxMenu.tsx). */
    vertexIndex?: number;
  } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const toScreen = (p: { x: number; y: number }) =>
    imageToScreen(p.x * img.w, p.y * img.h, view, img, vp);

  const globalFont = OVERLAY_FONT_PX[overlay.size];
  const color = overlay.color;
  // configurable line thickness (falls back for overlays persisted before
  // lineWidth existed); selected measures render one step thicker.
  const baseSw = overlay.lineWidth ?? 2.5;
  const defaultEndSymbol = overlay.endSymbol ?? "bar";

  // post-edit analysis refresh (on handle release)
  const refresh = useMeasureRefresh({
    imageId,
    img,
    tilt,
    setProfile,
    setStatus,
    setRoiStats,
  });

  // Vertex/handle drag mechanics (handle drag, whole-body translate, and
  // alt+edge-drag insert) live in MeasureVertexLayer.tsx — extracted to
  // stay under the frontend size ratchet (lasso-editing plan, item D).
  const {
    onHandleDown,
    onHandleMove,
    onHandleUp,
    onBodyDown,
    onVertexContextMenu,
  } = useVertexEditing({
      imageId,
      measures,
      view,
      img,
      vp,
      svgRef,
      updateMeasure,
      setSelected,
      pushUndo,
      refresh,
      openMenu: (e, mid, vertexIndex) =>
        setCtxMenu({ mid, x: e.clientX, y: e.clientY, vertexIndex }),
    });

  const renderMeasure = (m: Measure, isPending = false) => {
    const pts = m.pts.map(toScreen);
    const sel = m.id === selected || selectedMulti.includes(m.id);
    const stroke = isPending
      ? "var(--capture)"
      : sel
        ? "var(--accent)"
        : (m.color ?? color);
    const sw = sel ? baseSw + 1 : baseSw;
    // per-annotation font size (audit #12) overrides global overlay size
    const font = m.fontSize ?? globalFont;
    // body-drag starter (audit #12): mousedown on the shape interior
    // translates all points together instead of dragging a corner. On a
    // polygon/lasso, alt turns this into an edge-insert-and-drag instead
    // (item D step 3) — see useVertexEditing's onBodyDown.
    const bodyDown = isPending
      ? undefined
      : (e: React.PointerEvent) => onBodyDown(e, m, pts);
    const common = {
      stroke,
      strokeWidth: sw,
      fill: "none",
      style: { cursor: "default" },
      onPointerDown: isPending
        ? undefined
        : (e: React.PointerEvent) => {
            e.stopPropagation();
            setSelected(m.id);
          },
      onContextMenu: isPending
        ? undefined
        : (e: React.MouseEvent) => {
            e.preventDefault();
            e.stopPropagation();
            setSelected(m.id);
            setCtxMenu({ mid: m.id, x: e.clientX, y: e.clientY });
          },
      pointerEvents: (isPending ? "none" : "stroke") as "none" | "stroke",
    };
    // Fat, transparent hit layer so thin line measures (distance, profile,
    // angle…) are easy to click/right-click — the visible stroke is ~1.5px,
    // which made every non-selected line measure effectively undeletable.
    const hit = { ...common, stroke: "transparent", strokeWidth: 12 };

    let shape: React.ReactNode = null;
    let labelAt = pts[0];
    if (m.kind === "text" && pts.length >= 1) {
      shape = null; // pure caption — the <text> below carries it
      labelAt = { x: pts[0].x + 6, y: pts[0].y - 6 };
    } else if (m.kind === "arrow" && pts.length === 2) {
      const [a, b] = pts;
      const ang = Math.atan2(b.y - a.y, b.x - a.x);
      const head = 9;
      const wing = (da: number) =>
        `${b.x - head * Math.cos(ang + da)},${b.y - head * Math.sin(ang + da)}`;
      shape = (
        <>
          <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} {...common} />
          <polyline
            points={`${wing(-0.45)} ${b.x},${b.y} ${wing(0.45)}`}
            {...common}
          />
        </>
      );
      labelAt = { x: a.x + 8, y: a.y - 8 };
    } else if (m.kind === "box" && pts.length === 2) {
      const x = Math.min(pts[0].x, pts[1].x);
      const y = Math.min(pts[0].y, pts[1].y);
      // transparent fill enables body-drag (audit #12): clicking the interior
      // translates all points; corners still move individual handles below.
      shape = (
        <rect
          x={x}
          y={y}
          width={Math.abs(pts[1].x - pts[0].x)}
          height={Math.abs(pts[1].y - pts[0].y)}
          {...common}
          fill="transparent"
          pointerEvents={isPending ? "none" : "all"}
          style={{ cursor: isPending ? "default" : "move" }}
          onPointerDown={bodyDown}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
        />
      );
      labelAt = { x, y: y - 6 };
    } else if (
      (m.kind === "ellipse" || m.kind === "circle") &&
      pts.length === 2
    ) {
      const cx = (pts[0].x + pts[1].x) / 2;
      const cy = (pts[0].y + pts[1].y) / 2;
      shape = (
        <ellipse
          cx={cx}
          cy={cy}
          rx={Math.abs(pts[1].x - pts[0].x) / 2}
          ry={Math.abs(pts[1].y - pts[0].y) / 2}
          {...common}
          fill="transparent"
          pointerEvents={isPending ? "none" : "all"}
          style={{ cursor: isPending ? "default" : "move" }}
          onPointerDown={bodyDown}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
        />
      );
      labelAt = {
        x: Math.min(pts[0].x, pts[1].x),
        y: Math.min(pts[0].y, pts[1].y) - 6,
      };
    } else if (m.kind === "roi" && pts.length === 2) {
      const x = Math.min(pts[0].x, pts[1].x);
      const y = Math.min(pts[0].y, pts[1].y);
      shape = (
        <rect
          x={x}
          y={y}
          width={Math.abs(pts[1].x - pts[0].x)}
          height={Math.abs(pts[1].y - pts[0].y)}
          {...common}
        />
      );
      labelAt = { x, y: y - 6 };
    } else if (m.kind === "angle" && pts.length === 3) {
      shape = (
        <polyline
          points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
          {...common}
        />
      );
      labelAt = { x: pts[1].x + 10, y: pts[1].y - 10 };
    } else if (m.kind === "polyline" && pts.length >= 2) {
      shape = (
        <polyline
          points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
          strokeDasharray="6 4"
          {...common}
        />
      );
      const last = pts[pts.length - 1];
      labelAt = { x: last.x + 10, y: last.y - 10 };
    } else if ((m.kind === "polygon" || m.kind === "lasso") && pts.length >= 2) {
      // plan item 4: render enclosed holes as a void in the shape, not a
      // silent subtraction only visible in the label
      const holes = !isPending && m.holes?.length
        ? m.holes.map((h) => h.map(toScreen))
        : undefined;
      shape = (
        <ClosedShapeGlyph
          pts={pts}
          holes={holes}
          stroke={stroke}
          strokeWidth={sw}
          isPending={isPending}
          onBodyDown={bodyDown}
          onHandleMove={onHandleMove}
          onHandleUp={onHandleUp}
          title="alt-drag an edge to add a point"
          onContextMenu={common.onContextMenu}
        />
      );
      labelAt = isPending ? pts[pts.length - 1] : closedShapeLabelAnchor(pts);
    } else if (pts.length >= 2) {
      // box profiles (m.width set): show the averaging BOX, with the
      // dashed centerline marking where the profile runs (user request
      // 2026-06-09 — a bare line after drawing a box was confusing)
      let outline = null;
      if (m.kind === "profile" && m.width != null) {
        // screen px per image px (uniform zoom)
        const o = imageToScreen(0, 0, view, img, vp);
        const u = imageToScreen(1, 0, view, img, vp);
        const pxScale = Math.hypot(u.x - o.x, u.y - o.y);
        const ang = Math.atan2(pts[1].y - pts[0].y, pts[1].x - pts[0].x);
        const half = (m.width / 2) * pxScale;
        const ox = -Math.sin(ang) * half;
        const oy = Math.cos(ang) * half;
        outline = (
          <polygon
            points={`${pts[0].x + ox},${pts[0].y + oy} ${pts[1].x + ox},${pts[1].y + oy} ${pts[1].x - ox},${pts[1].y - oy} ${pts[0].x - ox},${pts[0].y - oy}`}
            {...common}
          />
        );
      }
      shape = (
        <>
          {outline}
          <line
            x1={pts[0].x}
            y1={pts[0].y}
            x2={pts[1].x}
            y2={pts[1].y}
            strokeDasharray={m.kind === "profile" ? "6 4" : undefined}
            {...common}
          />
        </>
      );
      labelAt = {
        x: (pts[0].x + pts[1].x) / 2 + 8,
        y: (pts[0].y + pts[1].y) / 2 - 8,
      };
    }

    // transparent fat-stroke twin of the shape, carrying the same select /
    // context-menu handlers, so the whole measure is an easy click target
    let hitShape: React.ReactNode = null;
    if (!isPending && pts.length >= 2) {
      if (m.kind === "box" || m.kind === "roi") {
        hitShape = (
          <rect
            x={Math.min(pts[0].x, pts[1].x)}
            y={Math.min(pts[0].y, pts[1].y)}
            width={Math.abs(pts[1].x - pts[0].x)}
            height={Math.abs(pts[1].y - pts[0].y)}
            {...hit}
          />
        );
      } else if (m.kind === "ellipse" || m.kind === "circle") {
        hitShape = (
          <ellipse
            cx={(pts[0].x + pts[1].x) / 2}
            cy={(pts[0].y + pts[1].y) / 2}
            rx={Math.abs(pts[1].x - pts[0].x) / 2}
            ry={Math.abs(pts[1].y - pts[0].y) / 2}
            {...hit}
          />
        );
      } else {
        hitShape = (
          <polyline
            points={pts.map((p) => `${p.x},${p.y}`).join(" ")}
            {...hit}
          />
        );
      }
    }

    return (
      <g key={m.id}>
        {hitShape}
        {shape}
        {(m.pts.length >= 2 || m.kind === "text") && (
          <text
            x={labelAt.x + (m.labelDx ?? 0)}
            y={labelAt.y + (m.labelDy ?? 0)}
            fill={isPending ? "var(--capture)" : (m.color ?? color)}
            fontSize={font}
            fontFamily="var(--font-mono)"
            paintOrder="stroke"
            stroke="rgba(0,0,0,0.75)"
            strokeWidth={3}
            pointerEvents={isPending ? "none" : "all"}
            style={{ cursor: isPending ? "default" : "move" }}
            onPointerDown={
              isPending
                ? undefined
                : (e) => {
                    e.stopPropagation();
                    // select on label click too — for text annotations the
                    // label is the ONLY hit target (no line/shape/hit layer),
                    // so without this they can't be selected and Del would
                    // fall through to closing the image instead of deleting.
                    setSelected(m.id);
                    labelDragRef.current = {
                      mid: m.id,
                      startX: e.clientX,
                      startY: e.clientY,
                      dx0: m.labelDx ?? 0,
                      dy0: m.labelDy ?? 0,
                    };
                    (e.target as Element).setPointerCapture(e.pointerId);
                  }
            }
            onPointerMove={(e) => {
              const d = labelDragRef.current;
              if (!d || d.mid !== m.id) return;
              setMeasureStyle(imageId, m.id, {
                labelDx: d.dx0 + e.clientX - d.startX,
                labelDy: d.dy0 + e.clientY - d.startY,
              });
            }}
            onPointerUp={(e) => {
              labelDragRef.current = null;
              (e.target as Element).releasePointerCapture(e.pointerId);
            }}
            onContextMenu={
              isPending
                ? undefined
                : (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    setSelected(m.id);
                    setCtxMenu({ mid: m.id, x: e.clientX, y: e.clientY });
                  }
            }
          >
            {measureLabel(m, { img, pixelSize, pixelUnit, tilt, roiStats })}
          </text>
        )}
        {!isPending && (
          <VertexHandles
            pts={pts}
            mid={m.id}
            sel={sel}
            color={color}
            defaultEndSymbol={defaultEndSymbol}
            endSymbol={m.endSymbol}
            onHandleDown={onHandleDown}
            onHandleMove={onHandleMove}
            onHandleUp={onHandleUp}
            onVertexContextMenu={onVertexContextMenu}
          />
        )}
      </g>
    );
  };

  return (
    <>
      <svg
        ref={svgRef}
        className="fvd-measure-layer"
        width={vp.w}
        height={vp.h}
      >
        {measures.map((m) => renderMeasure(m))}
        {pending &&
          pending.pts.length >= 2 &&
          renderMeasure(
            {
              id: "__pending__",
              kind: pending.kind,
              pts: pending.pts.map((p) => ({ x: p.x / img.w, y: p.y / img.h })),
            },
            true,
          )}
      </svg>
      {ctxMenu && (
        <MeasureCtxMenu
          imageId={imageId}
          measures={measures}
          at={ctxMenu}
          defaultEndSymbol={defaultEndSymbol}
          globalFont={globalFont}
          view={view}
          img={img}
          onClose={() => setCtxMenu(null)}
        />
      )}
    </>
  );
}
