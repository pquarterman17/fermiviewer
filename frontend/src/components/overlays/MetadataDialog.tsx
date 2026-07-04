// Metadata viewer/editor (checklist K): all metadata entries of the
// active image, string values editable, add-new row at the bottom.

import { useEffect, useState } from "react";

import { updateMetadata } from "../../lib/api";
import { useViewer } from "../../store/viewer";

export default function MetadataDialog() {
  const open = useViewer((s) => s.metaOpen);
  const setOpen = useViewer((s) => s.setMetaOpen);
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);

  const [edits, setEdits] = useState<Record<string, string>>({});
  const [newKey, setNewKey] = useState("");
  const [newVal, setNewVal] = useState("");

  useEffect(() => {
    setEdits({});
    setNewKey("");
    setNewVal("");
  }, [open, activeId]);

  if (!open) return null;

  const entries = Object.entries(meta?.meta ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );

  const save = () => {
    if (!activeId) return;
    const updates: Record<string, string> = { ...edits };
    if (newKey.trim()) updates[newKey.trim()] = newVal;
    if (Object.keys(updates).length === 0) {
      setOpen(false);
      return;
    }
    updateMetadata(activeId, updates)
      .then((m) => {
        useViewer.setState((s) => ({
          images: { ...s.images, [m.id]: m },
        }));
        setStatus(`metadata updated (${Object.keys(updates).length})`);
        setOpen(false);
      })
      .catch((e: Error) => setStatus(`metadata: ${e.message}`));
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
      <div
        className="fvd-glass fvd-export"
        style={{ maxHeight: "70vh", overflowY: "auto" }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>Metadata — {meta?.name ?? "(no image)"}</h2>
        {entries.length === 0 && (
          <div className="fvd-ws-empty">No metadata entries.</div>
        )}
        {entries.map(([k, v]) => (
          <div className="fvd-ws-row" key={k}>
            <span
              className="k"
              style={{ width: 140, overflow: "hidden" }}
              title={k}
            >
              {k}
            </span>
            <input
              style={{ flex: 1 }}
              value={edits[k] ?? String(v)}
              onChange={(e) => setEdits((p) => ({ ...p, [k]: e.target.value }))}
            />
          </div>
        ))}
        <div className="fvd-ws-row">
          <input
            placeholder="new key"
            style={{ width: 140 }}
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
          />
          <input
            placeholder="value"
            style={{ flex: 1 }}
            value={newVal}
            onChange={(e) => setNewVal(e.target.value)}
          />
        </div>
        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={() => setOpen(false)}
            title="Discard changes and close (Esc)"
          >
            Cancel
          </button>
          <button
            className="fvd-btn primary"
            onClick={save}
            title="Save metadata changes to the image"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
