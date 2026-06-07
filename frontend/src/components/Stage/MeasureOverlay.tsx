// Redraggable measurement overlay (handoff §4/§9): distance / profile /
// angle / ROI rendered at wrap level — handles stay constant-size at any
// zoom; labels live-update in calibrated units.

import { useRef } from "react";

import { measurePolyline, measureProfile, measureRoi } from "../../lib/api";
import {
  imageToScreen,
  physAngle,
  physDist,
  screenToImage,
  type Size,
} from "../../lib/geometry";
import { useStageInfo } from "../../store/stage";
import { useViewer, type Measure, type View } from "../../store/viewer";

const FONT_PX = { S: 10, M: 12, L: 15, XL: 19 } as const;
const HANDLE_R = 5;

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
  const pushUndo = useViewer((s) => s.pushUndo);
  const svgRef = useRef<SVGSVGElement>(null);

  const toScreen = (p: { x: number; y: number }) =>
    imageToScreen(p.x * img.w, p.y * img.h, view, img, vp);
  const toImagePx = (m: Measure) =>
    m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));

  const font = FONT_PX[overlay.size];
  const color = overlay.color;

  // ── post-edit analysis refresh (on handle release) ──
  const refresh = (m: Measure) => {
    const px = toImagePx(m);
    const width = useViewer.getState().profileWidth;
    if (m.kind === "profile") {
      measureProfile(imageId, px[0], px[1], width)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "polyline") {
      measurePolyline(imageId, px, width)
        .then((r) => setProfile({ ...r, measureId: m.id }))
        .catch((e: Error) => setStatus(e.message));
    } else if (m.kind === "roi") {
      measureRoi(imageId, px[0], px[1])
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

  const label = (m: Measure): string => {
    const px = toImagePx(m);
    switch (m.kind) {
      case "distance":
      case "profile": {
        const d = physDist(px[0], px[1], pixelSize);
        return d.unit === "cal"
          ? `${fmt(d.value)} ${pixelUnit}`
          : `${fmt(d.value)} px`;
      }
      case "polyline": {
        let total = 0;
        for (let i = 1; i < px.length; i++) {
          total += physDist(px[i - 1], px[i], pixelSize).value;
        }
        return pixelSize != null
          ? `${fmt(total)} ${pixelUnit}`
          : `${fmt(total)} px`;
      }
      case "angle":
        return px.length === 3 ? `${physAngle(px[1], px[0], px[2]).toFixed(1)}°` : "";
      case "roi": {
        const s = roiStats[m.id];
        return s ? `μ ${fmt(s.mean)} · σ ${fmt(s.std)}` : "…";
      }
    }
  };

  const renderMeasure = (m: Measure, isPending = false) => {
    const pts = m.pts.map(toScreen);
    const sel = m.id === selected;
    const stroke = isPending ? "var(--capture)" : sel ? "var(--accent)" : color;
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
      pointerEvents: (isPending ? "none" : "stroke") as "none" | "stroke",
    };

    let shape: React.ReactNode = null;
    let labelAt = pts[0];
    if (m.kind === "roi" && pts.length === 2) {
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
      shape = (
        <line
          x1={pts[0].x}
          y1={pts[0].y}
          x2={pts[1].x}
          y2={pts[1].y}
          strokeDasharray={m.kind === "profile" ? "6 4" : undefined}
          {...common}
        />
      );
      labelAt = {
        x: (pts[0].x + pts[1].x) / 2 + 8,
        y: (pts[0].y + pts[1].y) / 2 - 8,
      };
    }

    return (
      <g key={m.id}>
        {shape}
        {m.pts.length >= 2 && (
          <text
            x={labelAt.x}
            y={labelAt.y}
            fill={isPending ? "var(--capture)" : color}
            fontSize={font}
            fontFamily="var(--font-mono)"
            paintOrder="stroke"
            stroke="rgba(0,0,0,0.75)"
            strokeWidth={3}
            pointerEvents="none"
          >
            {label(m)}
          </text>
        )}
        {!isPending &&
          pts.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={HANDLE_R}
              fill="var(--surface-0)"
              stroke={sel ? "var(--accent)" : color}
              strokeWidth={1.5}
              pointerEvents="all"
              style={{ cursor: "move" }}
              onPointerDown={(e) => onHandleDown(e, m.id, i)}
              onPointerMove={onHandleMove}
              onPointerUp={onHandleUp}
            />
          ))}
      </g>
    );
  };

  return (
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
  );
}

function fmt(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(2);
  return Number(v.toPrecision(4)).toString();
}
