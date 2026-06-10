// Scale Bar inspector card (item #33): length presets, thickness, font
// size, position reset. Shown in the Image tab when the active image is
// calibrated (pixel_size != null).

import { niceScaleLength } from "../../lib/geometry";
import { useViewer } from "../../store/viewer";

export default function ScaleBarCard() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const sbState = useViewer((s) =>
    s.activeId ? s.scaleBars[s.activeId] : undefined,
  );
  const scaleBarVisible = useViewer((s) => s.scaleBarVisible);
  const toggleScaleBar = useViewer((s) => s.toggleScaleBar);
  const setScaleBar = useViewer((s) => s.setScaleBar);

  // Only show when the active image has pixel calibration
  if (!activeId || !meta || meta.pixel_size == null) return null;

  const pixelSize = meta.pixel_size;
  const unit = meta.pixel_unit;

  // Nice-number presets at representative zoom levels
  const presets: number[] = [];
  for (const zoom of [1, 2, 4, 8]) {
    const p = niceScaleLength((120 * pixelSize) / zoom);
    if (!presets.includes(p)) presets.push(p);
  }
  presets.sort((a, b) => a - b);

  const current = sbState?.lengthPhys;
  const thickness = sbState?.thickness ?? null;
  const fontSize = sbState?.fontSize ?? null;

  const reset = () => {
    setScaleBar(activeId, { x: 0.02, y: 0.92, lengthPhys: null, thickness: null, fontSize: null });
  };

  return (
    <div className="fvd-card">
      <h3>Scale Bar</h3>

      <div className="fvd-meta-row">
        <span className="k">Visible</span>
        <label className="fvd-toggle-label">
          <input
            type="checkbox"
            checked={scaleBarVisible}
            onChange={toggleScaleBar}
          />
        </label>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Length</span>
        <div className="fvd-sb-presets">
          <button
            className={`fvd-seg-btn${current == null ? " active" : ""}`}
            onClick={() => setScaleBar(activeId, { lengthPhys: null })}
          >
            Auto
          </button>
          {presets.map((p) => (
            <button
              key={p}
              className={`fvd-seg-btn${current === p ? " active" : ""}`}
              onClick={() => setScaleBar(activeId, { lengthPhys: p })}
            >
              {p >= 1
                ? `${Number(p.toPrecision(3))} ${unit}`
                : `${Number((p * 1000).toPrecision(3))} p${unit}`}
            </button>
          ))}
        </div>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Thickness</span>
        <div className="fvd-sb-spin">
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { thickness: Math.max(1, (thickness ?? 3) - 1) })
            }
          >
            −
          </button>
          <span>{thickness ?? "auto"}</span>
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { thickness: (thickness ?? 3) + 1 })
            }
          >
            +
          </button>
          {thickness != null && (
            <button
              className="fvd-icon-btn"
              title="Reset to auto"
              onClick={() => setScaleBar(activeId, { thickness: null })}
            >
              ↺
            </button>
          )}
        </div>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Font size</span>
        <div className="fvd-sb-spin">
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { fontSize: Math.max(8, (fontSize ?? 12) - 1) })
            }
          >
            −
          </button>
          <span>{fontSize ?? "auto"}</span>
          <button
            className="fvd-icon-btn"
            onClick={() =>
              setScaleBar(activeId, { fontSize: (fontSize ?? 12) + 1 })
            }
          >
            +
          </button>
          {fontSize != null && (
            <button
              className="fvd-icon-btn"
              title="Reset to auto"
              onClick={() => setScaleBar(activeId, { fontSize: null })}
            >
              ↺
            </button>
          )}
        </div>
      </div>

      <div className="fvd-meta-row">
        <span className="k">Position</span>
        <button className="fvd-seg-btn" onClick={reset}>
          Reset
        </button>
      </div>
    </div>
  );
}
