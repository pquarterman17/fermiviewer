// Custom Metadata card: user-configured fields (config: metadata.yaml),
// pre-filled per image from the filename pattern / saved sidecar, editable
// here, and persisted to a <name>.fvmeta.yaml sidecar beside the file.

import { useEffect, useRef, useState } from "react";

import {
  batchAutofill,
  getUserMeta,
  saveUserMeta,
  type MetaField,
  type UserMeta,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import Card from "./Card";

export default function CustomMetaCard() {
  const activeId = useViewer((s) => s.activeId);
  const order = useViewer((s) => s.order);
  const setStatus = useViewer((s) => s.setStatus);
  const [info, setInfo] = useState<UserMeta | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const prevActive = useRef<string | null>(null);

  useEffect(() => {
    if (!activeId) {
      setInfo(null);
      return;
    }
    const imageChanged = prevActive.current !== activeId;
    prevActive.current = activeId;
    let alive = true;
    getUserMeta(activeId)
      .then((u) => {
        if (!alive) return;
        setInfo(u);
        // refresh field list / sidecar status always, but don't clobber
        // unsaved edits on the SAME image (e.g. a batch refresh fired while
        // the user was typing). On an image switch, always load fresh.
        if (imageChanged || !dirty) {
          setValues(u.values);
          setDirty(false);
        }
      })
      .catch(() => {
        if (alive) setInfo(null);
      });
    return () => {
      alive = false;
    };
  }, [activeId, reload]);

  if (!activeId || !info) return null;

  // no fields configured yet — point the user at their config file
  if (info.fields.length === 0) {
    return (
      <Card title="Custom Metadata" defaultOpen={false}>
        <div className="fvd-meta-row">
          <span className="k">No fields configured</span>
        </div>
        <div className="fvd-ws-note">
          Add a <code>fields:</code> list to your config:
          <br />
          <code style={{ wordBreak: "break-all" }}>{info.config_path}</code>
        </div>
      </Card>
    );
  }

  const save = () => {
    if (!activeId) return;
    setBusy(true);
    saveUserMeta(activeId, values)
      .then((r) => {
        setStatus(
          r.wrote_sidecar
            ? "metadata saved (sidecar written)"
            : "metadata saved (session)",
        );
        setDirty(false);
        setInfo((p) =>
          p
            ? { ...p, values, has_sidecar: r.wrote_sidecar || p.has_sidecar }
            : p,
        );
      })
      .catch((e: Error) => setStatus(`metadata: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const runBatch = () => {
    setBusy(true);
    batchAutofill(order)
      .then((r) => {
        setStatus(
          `auto-filled ${r.n_matched}/${r.n_total} files from filename`,
        );
        setReload((x) => x + 1); // refresh the active image's values
      })
      .catch((e: Error) => setStatus(`batch auto-fill: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const renderField = (f: MetaField) => {
    const v = values[f.name] ?? "";
    const onChange = (val: string) => {
      setValues((p) => ({ ...p, [f.name]: val }));
      setDirty(true);
    };
    if (f.options.length > 0) {
      // keep a non-listed current value selectable (e.g. filename-derived)
      const opts = v && !f.options.includes(v) ? [v, ...f.options] : f.options;
      return (
        <select
          value={v}
          style={{ flex: 1 }}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="" />
          {opts.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      );
    }
    const type =
      f.type === "number" ? "number" : f.type === "date" ? "date" : "text";
    return (
      <input
        type={type}
        style={{ flex: 1 }}
        value={v}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  };

  const footHint = info.can_write_sidecar
    ? info.has_sidecar
      ? "↳ saved to a .fvmeta.yaml beside the file"
      : "↳ Save writes a .fvmeta.yaml beside the file"
    : "↳ session only — no file path for a sidecar";

  return (
    <Card title="Custom Metadata" defaultOpen>
      {info.fields.map((f) => (
        <div className="fvd-meta-row" key={f.name}>
          <span className="k" title={f.name}>
            {f.name}
          </span>
          {renderField(f)}
        </div>
      ))}
      <div className="fvd-btn-row">
        <button
          className="fvd-btn primary"
          onClick={save}
          disabled={busy || !dirty}
          title="Save these values (writes a .fvmeta.yaml sidecar)"
        >
          {busy ? "Saving…" : "Save"}
        </button>
        <button
          className="fvd-btn"
          title="Apply the filename pattern to every loaded file and write their sidecars"
          onClick={runBatch}
          disabled={busy || order.length === 0}
        >
          Auto-fill all ({order.length})
        </button>
      </div>
      <div className="fvd-ws-note">{footHint}</div>
    </Card>
  );
}
