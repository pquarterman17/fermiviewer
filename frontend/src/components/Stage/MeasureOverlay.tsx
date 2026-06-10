// Redraggable measurement overlay (handoff §4/§9): distance / profile /
// angle / ROI rendered at wrap level — handles stay constant-size at any
// zoom; labels live-update in calibrated units.

import { useRef, useState } from "react";

import { measurePolyline, measureProfile, measureRoi } from "../../lib/api";
import {
  imageToScreen,
  physAngle,
  screenToImage,
  tiltDist,
  type Size,
} from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import {
  useViewer,
  type EndSymbol,
  type Measure,
  type View,
} from "../../store/viewer";

const FONT_PX = { S: 10, M: 12, L: 15, XL: 19 } as const;
const HANDLE_R = 5;

/** SVG glyph for an endpoint handle. The hit-circle (transparent, R=8)
 *  is always rendered so draggability is consistent regardless of glyph.
 *  `angle` (radians) is the adjacent-segment direction — used by the
 *  "bar" glyph, a dimension-style tick drawn perpendicular to the line. */
function EndpointGlyph({
  cx,
  cy,
  sym,
  stroke,
  angle = 0,
}: {
  cx: number;
  cy: number;
  sym: EndSymbol;
  stroke: string;
  angle?: number;
}) {
  const r = HANDLE_R;
  const bl = r + 2; // bar half-length
  const px = -Math.sin(angle); // unit perpendicular
  const py = Math.cos(angle);
  const vis =
    sym === "bar" ? (
      <line
        x1={cx + bl * px}
        y1={cy + bl * py}
        x2={cx - bl * px}
        y2={cy - bl * py}
        stroke={stroke}
        strokeWidth={1.5}
      />
    ) : sym === "circle" ? (
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="var(--surface-0)"
        stroke={stroke}
        strokeWidth={1.5}
      />
    ) : sym === "square" ? (
      <rect
        x={cx - r}
        y={cy - r}
        width={r * 2}
        height={r * 2}
        fill="var(--surface-0)"
        stroke={stroke}
        strokeWidth={1.5}
      />
    ) : sym === "cross" ? (
      <>
        <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} stroke={stroke} strokeWidth={1.5} />
        <line x1={cx + r} y1={cy - r} x2={cx - r} y2={cy + r} stroke={stroke} strokeWidth={1.5} />
      </>
    ) : null; /* "none" → invisible; hit circle still captures events */
  return (
    <>
      {vis}
      {/* transparent hit target — always present for drag capture */}
      <circle cx={cx} cy={cy} r={r + 3} fill="transparent" stroke="none" />
    </>
  );
}

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

  const dragRef = useRef<{
    mid: string;
    pt: number;
    before: Measure["pts"];
  } | null>(null);
  const labelDragRef = useRef<{
    mid: string;
    startX: number;
    startY: number;
    dx0: number;
    dy0: number;
  } | null>(null);
  const pushUndo = useViewer((s) => s.pushUndo);
  const setMeasureStyle = useViewer((s) => s.setMeasureStyle);
  const removeMeasure = useViewer((s) => s.removeMeasure);
  const selectedMulti = useViewer((s) => s.selectedMulti);
  const [ctxMenu, setCtxMenu] = useState<{
    mid: string;
    x: number;
    y: number;
  } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const toScreen = (p: { x: number; y: number }) =>
    imageToScreen(p.x * img.w, p.y * img.h, view, img, vp);
  const toImagePx = (m: Measure) =>
    m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));

  const font = FONT_PX[overlay.size];
  const color = overlay.color;
  const defaultEndSymbol = overlay.endSymbol ?? "bar";

  // ── post-edit analysis refresh (on handle release) ──
  const refresh = (m: Measure) => {
    const px = toImagePx(m);
    // box-profile measures carry their own ⊥ width (the box's short axis)
    const width = m.width ?? useViewer.getState().profileWidth;
    if (m.kind === "profile") {
      measureProfile(imageId, px[0], px[1], width, tilt)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "polyline") {
      measurePolyline(imageId, px, width)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "roi" || m.kind === "ellipse") {
      measureRoi(imageId, px[0], px[1],
                 m.kind === "ellipse" ? "ellipse" : "rect")
        .then((r) => setRoiStats(m.id, r))
        .catch((e: Error) => setStatus(e.message));
    }
  };

  const onHandleDown = (e: React.PointerEvent, mid: string, pt: number) => {
    e.stopPropagation();
    const m = measures.find((x) => x.id === mid);
    dragRef.current = { mid, pt, before: m ? m.pts : [] };
    (e.target as Element).setPointerCapture(e.pointerId);
    setSelected(mid);
  };

  const onHandleMove = (e: React.PointerEvent) => {
    if (!dragRef.current || !svgRef.current) return;
    const r = svgRef.current.getBoundingClientRect();
    const ip = screenToImage(
      e.clientX - r.left,
      e.clientY - r.top,
      view,
      img,
      vp,
    );
    const nx = Math.min(1, Math.max(0, ip.x / img.w));
    const ny = Math.min(1, Math.max(0, ip.y / img.h));
    const { mid, pt } = dragRef.current;
    const m = measures.find((x) => x.id === mid);
    if (!m) return;
    const pts = m.pts.map((p, i) => (i === pt ? { x: nx, y: ny } : p));
    updateMeasure(imageId, mid, pts);
  };

  const onHandleUp = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const { mid, before } = dragRef.current;
    const m = measures.find((x) => x.id === mid);
    dragRef.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
    if (!m) return;
    if (before.length && JSON.stringify(before) !== JSON.stringify(m.pts)) {
      pushUndo({
        t: "measure-move",
        imageId,
        measureId: mid,
        before,
        after: m.pts,
      });
    }
    refresh(m);
  };

  // #34: non-zero tilt corrects line-like labels; θ suffix flags it
  const tiltOn = tilt != null && tilt.angle !== 0;
  const theta = tiltOn ? " θ" : "";

  const label = (m: Measure): string => {
    const px = toImagePx(m);
    switch (m.kind) {
      case "distance":
      case "profile": {
        const d = tiltDist(px[0], px[1], pixelSize, tilt);
        return d.unit === "cal"
          ? `${fmt(d.value)} ${pixelUnit}${theta}`
          : `${fmt(d.value)} px${theta}`;
      }
      case "polyline": {
        let total = 0;
        for (let i = 1; i < px.length; i++) {
          total += tiltDist(px[i - 1], px[i], pixelSize, tilt).value;
        }
        return pixelSize != null
          ? `${fmt(total)} ${pixelUnit}${theta}`
          : `${fmt(total)} px${theta}`;
      }
      case "angle":
        return px.length === 3 ? `${physAngle(px[1], px[0], px[2]).toFixed(1)}°` : "";
      case "roi":
      case "ellipse": {
        const s = roiStats[m.id];
        return s ? `μ ${fmt(s.mean)} · σ ${fmt(s.std)}` : "…";
      }
      case "text":
      case "arrow":
      case "box":
      case "circle":
        return m.text ?? "";
    }
  };

  const renderMeasure = (m: Measure, isPending = false) => {
    const pts = m.pts.map(toScreen);
    const sel = m.id === selected || selectedMulti.includes(m.id);
    const stroke = isPending
      ? "var(--capture)"
      : sel
        ? "var(--accent)"
        : (m.color ?? color);
    const sw = sel ? 2 : 1.5;
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

    return (
      <g key={m.id}>
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
                    setCtxMenu({ mid: m.id, x: e.clientX, y: e.clientY });
                  }
            }
          >
            {label(m)}
          </text>
        )}
        {!isPending &&
          pts.map((p, i) => {
            // adjacent-segment direction for the perpendicular bar glyph
            const nb = pts.length > 1 ? (i === 0 ? pts[1] : pts[i - 1]) : null;
            const ang = nb ? Math.atan2(nb.y - p.y, nb.x - p.x) : 0;
            return (
              <g
                key={i}
                pointerEvents="all"
                style={{ cursor: "move" }}
                onPointerDown={(e) => onHandleDown(e, m.id, i)}
                onPointerMove={onHandleMove}
                onPointerUp={onHandleUp}
              >
                <EndpointGlyph
                  cx={p.x}
                  cy={p.y}
                  sym={m.endSymbol ?? defaultEndSymbol}
                  stroke={sel ? "var(--accent)" : color}
                  angle={ang}
                />
              </g>
            );
          })}
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
      <div
        className="fvd-ctx-menu fvd-glass"
        style={{ left: ctxMenu.x, top: ctxMenu.y }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className="fvd-ctx-swatches">
          {["#ffffff", "#22d3ee", "#fbbf24", "#f472b6", "#a3e635",
            "#f43f5e"].map((c) => (
            <button
              key={c}
              className="fvd-swatch"
              style={{ background: c }}
              onClick={() => {
                setMeasureStyle(imageId, ctxMenu.mid, { color: c });
                setCtxMenu(null);
              }}
            />
          ))}
        </div>
        <div className="fvd-ctx-label">End symbol</div>
        <div className="fvd-ctx-sym-row">
          {(["bar", "none", "circle", "square", "cross"] as EndSymbol[]).map((sym) => {
            const active =
              (measures.find((x) => x.id === ctxMenu.mid)?.endSymbol ??
                defaultEndSymbol) === sym;
            return (
              <button
                key={sym}
                className={`fvd-ctx-sym${active ? " active" : ""}`}
                title={sym}
                onClick={() => {
                  setMeasureStyle(imageId, ctxMenu.mid, { endSymbol: sym });
                  setCtxMenu(null);
                }}
              >
                {sym === "bar" ? "|" : sym === "none" ? "—" : sym === "circle" ? "○" : sym === "square" ? "□" : "×"}
              </button>
            );
          })}
        </div>
        <div className="fvd-ctx-sep" />
        <button
          className="fvd-ctx-item"
          onClick={() => {
            const m = measures.find((x) => x.id === ctxMenu.mid);
            const t = window.prompt("Caption:", m?.text ?? "");
            if (t !== null) {
              useViewer.getState().setMeasureText(imageId, ctxMenu.mid, t);
            }
            setCtxMenu(null);
          }}
        >
          Edit caption…
        </button>
        <button
          className="fvd-ctx-item"
          onClick={() => {
            setMeasureStyle(imageId, ctxMenu.mid, {
              labelDx: 0,
              labelDy: 0,
            });
            setCtxMenu(null);
          }}
        >
          Reset label position
        </button>
        <button
          className="fvd-ctx-item danger"
          onClick={() => {
            removeMeasure(imageId, ctxMenu.mid);
            setCtxMenu(null);
          }}
        >
          Delete
        </button>
      </div>
    )}
    {ctxMenu && (
      <div
        className="fvd-ctx-backdrop"
        onPointerDown={() => setCtxMenu(null)}
        onContextMenu={(e) => {
          e.preventDefault();
          setCtxMenu(null);
        }}
      />
    )}
    </>
  );
}

function fmt(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(2);
  return Number(v.toPrecision(4)).toString();
}
