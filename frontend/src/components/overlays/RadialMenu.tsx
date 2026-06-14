// Right-click radial tool menu (handoff §4/§9): capture tools arranged
// in a ring at the cursor, plus a Copy action that puts the current view
// (scale bar + measurements baked in) on the clipboard.

import { copyActive } from "../../lib/export";
import { useViewer, type CaptureMode } from "../../store/viewer";

type RadialItem = {
  glyph: string;
  label: string;
  mode?: CaptureMode;
  action?: "copy";
};

const TOOLS: RadialItem[] = [
  { glyph: "↔", label: "Distance", mode: "distance" },
  { glyph: "∿", label: "Profile", mode: "profile" },
  { glyph: "∠", label: "Angle", mode: "angle" },
  { glyph: "▭", label: "ROI", mode: "roi" },
  { glyph: "⬚", label: "Box zoom", mode: "zoom" },
  { glyph: "✥", label: "Pan", mode: "none" }, // toggles the hand tool
];

// Copy is an action, not a capture mode — it runs immediately and closes
// the ring. Appended only when there's a raster image to copy.
const COPY_TOOL: RadialItem = { glyph: "⧉", label: "Copy", action: "copy" };

const RADIUS = 64;

export default function RadialMenu() {
  const at = useViewer((s) => s.radial);
  const setRadial = useViewer((s) => s.setRadial);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const setPanTool = useViewer((s) => s.setPanTool);
  const panTool = useViewer((s) => s.panTool);
  const setStatus = useViewer((s) => s.setStatus);
  // Copy only applies to a raster image (a 1-D spectrum has nothing to
  // rasterize). Primitive boolean → safe Zustand snapshot.
  const canCopy = useViewer((s) => {
    const m = s.activeId ? s.images[s.activeId] : null;
    return !!m && m.kind !== "spectrum";
  });

  if (!at) return null;

  const tools = canCopy ? [...TOOLS, COPY_TOOL] : TOOLS;

  const pick = (t: RadialItem) => {
    setRadial(null);
    if (t.action === "copy") {
      // bakes scale bar + measurements by default (copyActive defaults)
      copyActive()
        .then(() =>
          setStatus("copied to clipboard (scale bar + measurements)"),
        )
        .catch((e: Error) => setStatus(`clipboard: ${e.message}`));
      return;
    }
    if (t.label === "Pan") {
      setPanTool(!panTool);
    } else if (t.mode) {
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
      {tools.map((t, i) => {
        const ang = (i / tools.length) * 2 * Math.PI - Math.PI / 2;
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
