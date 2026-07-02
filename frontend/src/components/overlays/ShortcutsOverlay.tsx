// "?" shortcuts overlay — the §9 keyboard map.

import { useViewer } from "../../store/viewer";

const GROUPS: [string, [string, string][]][] = [
  [
    "View",
    [
      ["+ / −", "Zoom in / out"],
      ["F · 0", "Fit image"],
      ["1", "Actual size (100%)"],
      ["Z", "Box-zoom marquee"],
      ["X", "Zoom to dimensions (fixed size)"],
      ["H", "Hand / pan tool"],
      ["Space (hold)", "Pan"],
      ["Double-click", "Reset to fit"],
    ],
  ],
  [
    "Measure",
    [
      ["D", "Distance"],
      ["L", "Line profile"],
      ["B", "Box profile (integrated)"],
      ["G", "Angle (3-point)"],
      ["R", "ROI statistics"],
      ["A", "Auto contrast"],
      ["Del", "Delete selected measure"],
      ["Esc", "Cancel capture"],
    ],
  ],
  [
    "App",
    [
      ["⌘K", "Command palette"],
      ["⌘Z / ⇧⌘Z", "Undo / redo"],
      ["?", "This overlay"],
      ["F2", "Rename active image"],
      ["← → ↑ ↓ · [ / ]", "Previous / next image"],
      ["⌘[ / ⌘]", "Toggle library / inspector"],
      ["⌘⇧L", "Toggle theme"],
      ["Right-click", "Radial tool menu"],
    ],
  ],
];

export default function ShortcutsOverlay() {
  const open = useViewer((s) => s.shorts);
  const setShorts = useViewer((s) => s.setShorts);
  if (!open) return null;

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setShorts(false)}>
      <div
        className="fvd-glass fvd-shorts"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Keyboard shortcuts</h2>
        <div className="fvd-shorts-cols">
          {GROUPS.map(([title, rows]) => (
            <div key={title}>
              <h3>{title}</h3>
              {rows.map(([keys, what]) => (
                <div key={keys} className="fvd-shorts-row">
                  <span className="fvd-shortcut">{keys}</span>
                  <span>{what}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
