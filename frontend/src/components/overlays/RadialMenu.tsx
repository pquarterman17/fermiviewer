// Right-click radial tool menu (handoff §4/§9): capture tools arranged
// in a ring at the cursor.

import { useViewer, type CaptureMode } from "../../store/viewer";

const TOOLS: { glyph: string; label: string; mode: CaptureMode }[] = [
  { glyph: "↔", label: "Distance", mode: "distance" },
  { glyph: "∿", label: "Profile", mode: "profile" },
  { glyph: "∠", label: "Angle", mode: "angle" },
  { glyph: "▭", label: "ROI", mode: "roi" },
  { glyph: "⬚", label: "Box zoom", mode: "zoom" },
  { glyph: "✥", label: "Pan", mode: "none" }, // toggles the hand tool
];

const RADIUS = 64;

export default function RadialMenu() {
  const at = useViewer((s) => s.radial);
  const setRadial = useViewer((s) => s.setRadial);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const setPanTool = useViewer((s) => s.setPanTool);
  const panTool = useViewer((s) => s.panTool);

  if (!at) return null;

  const pick = (t: (typeof TOOLS)[number]) => {
    setRadial(null);
    if (t.label === "Pan") {
      setPanTool(!panTool);
    } else {
      setCaptureMode(t.mode);
    }
  };

  return (
    <div
      className="fvd-overlay-backdrop transparent"
      onMouseDown={() => setRadial(null)}
      onContextMenu={(e) => {
        e.preventDefault();
        setRadial(null);
      }}
    >
      {TOOLS.map((t, i) => {
        const ang = (i / TOOLS.length) * 2 * Math.PI - Math.PI / 2;
        const x = at.x + Math.cos(ang) * RADIUS;
        const y = at.y + Math.sin(ang) * RADIUS;
        return (
          <button
            key={t.label}
            className="fvd-glass fvd-radial-btn"
            style={{ left: x, top: y }}
            title={t.label}
            onMouseDown={(e) => {
              e.stopPropagation();
              pick(t);
            }}
          >
            <span className="glyph">{t.glyph}</span>
            <span className="lbl">{t.label}</span>
          </button>
        );
      })}
    </div>
  );
}
