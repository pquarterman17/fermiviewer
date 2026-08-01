// Diffraction workshop ROI overlay builders, extracted verbatim from
// DiffractionWorkshop.tsx (repo-health #33): the committed-ROI SVG shape
// and the live-draw-in-progress SVG shape, each a plain function of the
// state the component already tracks (committedRoi/scale, roiDraw).

import type { AnalysisRoi } from "../../../lib/api";
import type { RoiDraw } from "./diffractionGeometry";

// ── ROI SVG geometry for the committed ROI overlay ──────────────────
export function committedRoiOverlay(
  committedRoi: AnalysisRoi | null,
  scale: number,
): React.ReactNode {
  if (!committedRoi || !scale) return null;
  if (committedRoi.kind === "rect") {
    const { r0, c0, r1, c1 } = committedRoi;
    return (
      <rect
        x={c0 * scale}
        y={r0 * scale}
        width={(c1 - c0) * scale}
        height={(r1 - r0) * scale}
        fill="none"
        stroke="var(--capture, #35e0c2)"
        strokeWidth={1.5}
        strokeDasharray="5 3"
      />
    );
  }
  if (committedRoi.kind === "circle") {
    const { cr, cc, radius } = committedRoi;
    return (
      <circle
        cx={cc * scale}
        cy={cr * scale}
        r={radius * scale}
        fill="none"
        stroke="var(--capture, #35e0c2)"
        strokeWidth={1.5}
        strokeDasharray="5 3"
      />
    );
  }
  return null;
}

// ── ROI live-draw overlay (while user is drawing) ─────────────────
export function liveRoiDrawOverlay(roiDraw: RoiDraw): React.ReactNode {
  if (!roiDraw.p1 || !roiDraw.p2 || roiDraw.mode === "none") return null;
  const x1 = roiDraw.p1.x, y1 = roiDraw.p1.y;
  const x2 = roiDraw.p2.x, y2 = roiDraw.p2.y;
  if (roiDraw.mode === "rect") {
    return (
      <rect
        x={Math.min(x1, x2)} y={Math.min(y1, y2)}
        width={Math.abs(x2 - x1)} height={Math.abs(y2 - y1)}
        fill="rgba(53,224,194,0.08)"
        stroke="var(--capture, #35e0c2)"
        strokeWidth={1}
        strokeDasharray="4 3"
      />
    );
  }
  const r = Math.hypot(x2 - x1, y2 - y1);
  return (
    <circle cx={x1} cy={y1} r={r}
      fill="rgba(53,224,194,0.08)"
      stroke="var(--capture, #35e0c2)"
      strokeWidth={1} strokeDasharray="4 3"
    />
  );
}
