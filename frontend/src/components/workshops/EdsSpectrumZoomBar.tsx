// Visible affordances for the EDS spectrum's energy zoom. The gestures (drag,
// wheel, double-click) all work without this bar; it exists because none of
// them announce themselves, and because typing an exact energy range is the
// only precise way to frame a specific line.

import { useEffect, useState } from "react";

import { panBy, zoomBy, clampRange, type XRange } from "../../lib/eds/zoomRange";

const STEP = 1.6;

export default function EdsSpectrumZoomBar({
  range,
  bounds,
  minSpan,
  unit,
  onChange,
}: {
  /** Current view, or null for the full spectrum. */
  range: XRange | null;
  /** Full energy extent of the displayed spectrum. */
  bounds: XRange;
  minSpan: number;
  unit: string;
  onChange: (range: XRange | null) => void;
}) {
  const [lo, hi] = range ?? bounds;
  // Drafts let the user finish typing "1.2" without "1." being committed and
  // clamped out from under them mid-keystroke.
  const [draft, setDraft] = useState<[string, string]>(["", ""]);
  useEffect(() => {
    setDraft([lo.toFixed(3), hi.toFixed(3)]);
  }, [lo, hi]);

  const commit = (next: [string, string]) => {
    const a = Number(next[0]);
    const b = Number(next[1]);
    if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) {
      setDraft([lo.toFixed(3), hi.toFixed(3)]);
      return;
    }
    onChange(clampRange([a, b], bounds, minSpan));
  };

  const edit = (index: 0 | 1, value: string) => {
    const next: [string, string] = [...draft] as [string, string];
    next[index] = value;
    setDraft(next);
  };

  const zoomed = range !== null;

  return (
    <div className="fvd-eds-zoombar">
      <span className="k">View</span>
      {([0, 1] as const).map((index) => (
        <input
          key={index}
          type="number"
          step={0.05}
          className="fvd-eds-zoom-input"
          value={draft[index]}
          aria-label={index === 0 ? "View energy low" : "View energy high"}
          onChange={(event) => edit(index, event.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit(draft);
          }}
        />
      ))}
      <span className="k">{unit}</span>
      <div className="fvd-eds-zoom-buttons">
        <button
          type="button"
          className="fvd-icon-btn"
          aria-label="Pan left"
          disabled={!zoomed || lo <= bounds[0]}
          onClick={() => onChange(panBy(range, bounds, -0.5, minSpan))}
        >
          ◀
        </button>
        <button
          type="button"
          className="fvd-icon-btn"
          aria-label="Zoom out"
          disabled={!zoomed}
          onClick={() => onChange(zoomBy(range, bounds, STEP, minSpan))}
        >
          −
        </button>
        <button
          type="button"
          className="fvd-icon-btn"
          aria-label="Zoom in"
          onClick={() => onChange(zoomBy(range, bounds, 1 / STEP, minSpan))}
        >
          +
        </button>
        <button
          type="button"
          className="fvd-icon-btn"
          aria-label="Pan right"
          disabled={!zoomed || hi >= bounds[1]}
          onClick={() => onChange(panBy(range, bounds, 0.5, minSpan))}
        >
          ▶
        </button>
        <button
          type="button"
          className="fvd-btn"
          disabled={!zoomed}
          title="Show the full energy range"
          onClick={() => onChange(null)}
        >
          Reset
        </button>
      </div>
      <span className="fvd-eds-zoom-hint">
        drag zooms · shift+drag sets the window · wheel zooms
      </span>
    </div>
  );
}
