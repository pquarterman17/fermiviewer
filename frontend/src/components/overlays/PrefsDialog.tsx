// Preferences (checklist N): persisted defaults applied to newly
// opened images + capture tools. Stored in localStorage "fv_prefs".

import { useEffect, useState } from "react";

import { loadPrefs, savePrefs, type Prefs } from "../../lib/prefs";
import { useViewer } from "../../store/viewer";

const CMAPS = ["gray", "viridis", "inferno", "magma", "plasma", "cividis"];

export default function PrefsDialog() {
  const open = useViewer((s) => s.prefsOpen);
  const setOpen = useViewer((s) => s.setPrefsOpen);
  const setStatus = useViewer((s) => s.setStatus);
  const setProfileWidth = useViewer((s) => s.setProfileWidth);

  const [p, setP] = useState<Prefs>(loadPrefs());

  useEffect(() => {
    if (open) setP(loadPrefs());
  }, [open]);

  if (!open) return null;

  const save = () => {
    savePrefs(p);
    setProfileWidth(p.profileWidth);
    setStatus("preferences saved");
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
          <span className="k">Auto-open minimap</span>
          <label className="fvd-check">
            <input
              type="checkbox"
              checked={p.minimap}
              onChange={(e) => setP({ ...p, minimap: e.target.checked })}
            />
          </label>
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
