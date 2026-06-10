// Preferences (checklist N): persisted defaults applied to newly
// opened images + capture tools. Stored in localStorage "fv_prefs".

import { useEffect, useState } from "react";

import { setCustomColormap } from "../../lib/colormaps";
import { loadPrefs, savePrefs, type Prefs } from "../../lib/prefs";
import { useViewer } from "../../store/viewer";

const CMAPS = ["gray", "viridis", "inferno", "magma", "plasma", "cividis"];

export default function PrefsDialog() {
  const open = useViewer((s) => s.prefsOpen);
  const setOpen = useViewer((s) => s.setPrefsOpen);
  const setStatus = useViewer((s) => s.setStatus);
  const setProfileWidth = useViewer((s) => s.setProfileWidth);

  const [p, setP] = useState<Prefs>(loadPrefs());
  const [customCmap, setCustomCmap] = useState("");

  useEffect(() => {
    if (open) {
      setP(loadPrefs());
      try {
        const stops = JSON.parse(
          localStorage.getItem("fv_custom_cmap") ?? "[]",
        ) as number[][];
        setCustomCmap(
          stops
            .map(
              ([r, g, b]) =>
                "#" +
                [r, g, b]
                  .map((v) => v.toString(16).padStart(2, "0"))
                  .join(""),
            )
            .join(", "),
        );
      } catch {
        setCustomCmap("");
      }
    }
  }, [open]);

  if (!open) return null;

  const save = () => {
    // sanitize D13 fields: lo < hi, grid odd within 3–15
    const lo = Math.min(Math.max(p.autoLoPct, 0), 49.9);
    const hi = Math.max(Math.min(p.autoHiPct, 100), lo + 0.1);
    const grid = Math.min(15, Math.max(3, Math.round(p.inspectorGrid))) | 1;
    savePrefs({ ...p, autoLoPct: lo, autoHiPct: hi, inspectorGrid: grid });
    setProfileWidth(p.profileWidth);
    if (customCmap.trim() && !setCustomColormap(customCmap)) {
      setStatus("prefs: custom colormap needs ≥2 hex stops — not saved");
    } else {
      setStatus("preferences saved");
    }
    setOpen(false);
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
      <div
        className="fvd-glass fvd-export"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Preferences</h2>
        <div className="fvd-ws-row">
          <span className="k">Default colormap</span>
          <select
            value={p.defaultCmap}
            onChange={(e) => setP({ ...p, defaultCmap: e.target.value })}
          >
            {CMAPS.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </div>
        <div className="fvd-ws-row">
          <span className="k">Profile width (px)</span>
          <input
            type="number"
            min={1}
            max={99}
            style={{ width: 56 }}
            value={p.profileWidth}
            onChange={(e) =>
              setP({ ...p, profileWidth: Number(e.target.value) || 1 })
            }
          />
        </div>
        <div className="fvd-ws-row">
          <span className="k">Custom cmap</span>
          <input
            style={{ flex: 1 }}
            placeholder="#000, #a070f0, #fff"
            value={customCmap}
            title="2+ comma-separated hex stops for the 'custom' colormap"
            onChange={(e) => setCustomCmap(e.target.value)}
          />
        </div>
        <div className="fvd-ws-row">
          <span className="k">Auto-open minimap</span>
          <label className="fvd-check">
            <input
              type="checkbox"
              checked={p.minimap}
              onChange={(e) => setP({ ...p, minimap: e.target.checked })}
            />
          </label>
        </div>
        <div className="fvd-ws-row">
          <span className="k">Auto-contrast %</span>
          <input
            type="number"
            min={0}
            max={50}
            step={0.1}
            style={{ width: 64 }}
            title="low percentile"
            value={p.autoLoPct}
            onChange={(e) =>
              setP({ ...p, autoLoPct: Number(e.target.value) || 0 })
            }
          />
          <span className="k">–</span>
          <input
            type="number"
            min={50}
            max={100}
            step={0.1}
            style={{ width: 64 }}
            title="high percentile"
            value={p.autoHiPct}
            onChange={(e) =>
              setP({ ...p, autoHiPct: Number(e.target.value) || 100 })
            }
          />
        </div>
        <div className="fvd-ws-row">
          <span className="k">Default export scale</span>
          <select
            value={p.exportScale}
            onChange={(e) => setP({ ...p, exportScale: Number(e.target.value) })}
          >
            {[1, 2, 3, 4].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </div>
        <div className="fvd-ws-row">
          <span className="k">Pixel inspector grid</span>
          <input
            type="number"
            min={3}
            max={15}
            step={2}
            style={{ width: 56 }}
            title="odd N for the N×N value grid"
            value={p.inspectorGrid}
            onChange={(e) =>
              setP({ ...p, inspectorGrid: Number(e.target.value) || 7 })
            }
          />
        </div>
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button className="fvd-btn primary" onClick={save}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
