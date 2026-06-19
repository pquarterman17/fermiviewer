// Renders the trained-mode training scribbles over the image. Strokes are
// stored in image coords; each is drawn as a round-capped SVG polyline whose
// width tracks the brush radius at the current zoom, so what you paint is
// exactly what the backend rasterizes. Pointer events stay on the canvas
// (this layer is inert) — the Stage owns the painting.

import { imageToScreen, type Size } from "../../lib/geometry";
import { SCRIBBLE_COLORS, useScribble } from "../../store/scribble";
import { type View } from "../../store/viewer";

const color = (classId: number) =>
  SCRIBBLE_COLORS[(classId - 1) % SCRIBBLE_COLORS.length];

export default function ScribbleOverlay({
  view,
  img,
  vp,
}: {
  view: View;
  img: Size;
  vp: Size;
}) {
  const strokes = useScribble((s) => s.strokes);
  const boundary = useScribble((s) => s.boundary);
  if (strokes.length === 0) return null;

  return (
    <svg
      className="fvd-scribble-overlay"
      width={vp.w}
      height={vp.h}
      style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
    >
      {strokes.map((st, i) => {
        const c = color(st.classId);
        const w = Math.max(1, st.radius * 2 * view.z);
        const isBoundary = boundary.includes(st.classId);
        const screen = st.points.map((p) =>
          imageToScreen(p[0], p[1], view, img, vp),
        );
        if (screen.length === 1) {
          return (
            <circle
              key={i}
              cx={screen[0].x}
              cy={screen[0].y}
              r={Math.max(1, st.radius * view.z)}
              fill={c}
              opacity={isBoundary ? 0.4 : 0.55}
              stroke={isBoundary ? "#fff" : "none"}
              strokeDasharray={isBoundary ? "3 3" : undefined}
            />
          );
        }
        const pts = screen.map((s) => `${s.x},${s.y}`).join(" ");
        return (
          <polyline
            key={i}
            points={pts}
            fill="none"
            stroke={c}
            strokeWidth={w}
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity={isBoundary ? 0.4 : 0.55}
            strokeDasharray={isBoundary ? `${w} ${w}` : undefined}
          />
        );
      })}
    </svg>
  );
}
