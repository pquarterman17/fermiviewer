// Non-interactive measure-overlay pieces split out of MeasureOverlay.tsx to
// keep that drag-heavy SVG component under the frontend size ratchet.
// Everything here is a pure function of a Measure (+ explicit context) —
// no hooks, no refs, no store subscriptions.

import type { RoiStats } from "../../lib/api";
import {
  areaPxToPhysical,
  physAngle,
  polygonStats,
  polygonStatsWithHoles,
  tiltDist,
  type Size,
  type TiltSettings,
} from "../../lib/geometry";
import type { EndSymbol, Measure } from "../../store/viewer";

export const HANDLE_R = 5;

/** SVG glyph for an endpoint handle. The hit-circle (transparent, R=8)
 *  is always rendered so draggability is consistent regardless of glyph.
 *  `angle` (radians) is the adjacent-segment direction — used by the
 *  "bar" glyph, a dimension-style tick drawn perpendicular to the line. */
export function EndpointGlyph({
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
        <line
          x1={cx - r}
          y1={cy - r}
          x2={cx + r}
          y2={cy + r}
          stroke={stroke}
          strokeWidth={1.5}
        />
        <line
          x1={cx + r}
          y1={cy - r}
          x2={cx - r}
          y2={cy + r}
          stroke={stroke}
          strokeWidth={1.5}
        />
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

/** Measure points, normalized 0–1 image coords → image-pixel coords. */
export function toImagePx(m: Measure, img: Size): { x: number; y: number }[] {
  return m.pts.map((p) => ({ x: p.x * img.w, y: p.y * img.h }));
}

export interface MeasureLabelCtx {
  img: Size;
  pixelSize: number | null;
  pixelUnit: string;
  tilt: TiltSettings | null;
  roiStats: Record<string, RoiStats>;
}

/** Per-kind display label ("12.3 nm", "μ 4.1 · σ 0.2", …). */
export function measureLabel(m: Measure, ctx: MeasureLabelCtx): string {
  const { img, pixelSize, pixelUnit, tilt, roiStats } = ctx;
  const px = toImagePx(m, img);
  // #34: non-zero tilt corrects line-like labels; θ suffix flags it
  const theta = tilt != null && tilt.angle !== 0 ? " θ" : "";
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
      return px.length === 3
        ? `${physAngle(px[1], px[0], px[2]).toFixed(1)}°`
        : "";
    case "roi":
    case "ellipse": {
      const s = roiStats[m.id];
      return s ? `μ ${fmt(s.mean)} · σ ${fmt(s.std)}` : "…";
    }
    case "polygon":
    case "lasso": {
      // plan item 4: the on-canvas label must net out holes too — this
      // used to call plain polygonStats unconditionally, so a region
      // with a hole (area math correct in lib/regionTable's CSV/table
      // path since item 19) still showed its GROSS area right on the
      // shape it was drawn on. Holes-free stays the exact pre-item-19
      // polygonStats call, so nothing here regresses.
      const holesPx = m.holes?.length
        ? m.holes.map((h) => h.map((p) => ({ x: p.x * img.w, y: p.y * img.h })))
        : undefined;
      const stats = holesPx ? polygonStatsWithHoles(px, holesPx) : polygonStats(px);
      const areaPhys = areaPxToPhysical(stats.areaPx2, pixelSize);
      // legibility (plan item 4 requirement 4): a holed region must not
      // read identically to a plain region of the same net area
      const holeNote = holesPx
        ? ` (${holesPx.length} hole${holesPx.length > 1 ? "s" : ""})`
        : "";
      return areaPhys != null
        ? `${fmt(areaPhys)} ${pixelUnit}²${holeNote}`
        : `${fmt(stats.areaPx2)} px²${holeNote}`;
    }
    case "text":
    case "arrow":
    case "box":
    case "circle":
      return m.text ?? "";
  }
}

export function fmt(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(2);
  return Number(v.toPrecision(4)).toString();
}
