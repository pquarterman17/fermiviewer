// Custom Metadata card: user-configured fields (config: metadata.yaml),
// pre-filled per image from the filename pattern / saved sidecar, editable
// here, and persisted to a <name>.fvmeta.yaml sidecar beside the file.

import { useEffect, useRef, useState } from "react";

import {
  batchAutofill,
  downloadUserMetaSidecar,
  getUserMeta,
  saveUserMeta,
  type MetaField,
  type UserMeta,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import Card from "./Card";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Compact "how this works" disclosure — the mechanism (filename auto-fill,
 *  precedence, what the two buttons do) explained in a few short lines so
 *  a physicist can read it in ~20s without leaving the card. */
function HowThisWorks({ configPath }: { configPath: string }) {
  return (
    <details style={{ marginTop: 4 }}>
      <summary style={{ cursor: "pointer", fontSize: 11, opacity: 0.85 }}>
        How this works
      </summary>
      <div className="fvd-ws-note" style={{ fontSize: 11 }}>
        <p style={{ margin: "4px 0" }}>
          Fields are configured in{" "}
          <code style={{ wordBreak: "break-all", userSelect: "all" }}>
            {configPath}
          </code>
          .
        </p>
        <p style={{ margin: "4px 0" }}>
          Filename auto-fill matches the file name against a pattern, e.g.{" "}
          <code>{"D{Design}_L{Lot}_W{Wafer}_R{Reticle}"}</code> parses{" "}
          <code>D1234_L44576_W1234_R13.dm3</code> into Design=1234,
          Lot=44576, Wafer=1234, Reticle=13.
        </p>
        <p style={{ margin: "4px 0" }}>
          Values resolve filename auto-fill first, then a saved file, then
          your own edits here — your edits win, and clearing a field to
          blank sticks.
        </p>
        <p style={{ margin: "4px 0" }}>
          <b>Save</b> stores the values above for this image. <b>Auto-fill
          all</b> runs the filename pattern on every open image and saves
          each one.
        </p>
      </div>
    </details>
  );
}

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
  // The effect below only re-runs on activeId/reload, not on every keystroke
  // (that would refetch on every character typed) — so its promise callback
  // must read `dirty` through a ref kept current every render, not the
  // `dirty` closed over when the effect last ran. Without this, a same-image
  // refresh (Auto-fill all → setReload) that is still in flight when the
  // user starts typing resolves with the STALE (pre-edit) `dirty`, sees it
  // as false, and overwrites the in-progress edit with the server's value.
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

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
        if (imageChanged || !dirtyRef.current) {
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

  // no fields configured yet — point the user at their config file, with
  // a copy-pasteable minimal example so getting started doesn't require
  // reading the docs
  if (info.fields.length === 0) {
    return (
      <Card title="Custom Metadata" defaultOpen={false}>
        <div className="fvd-meta-row">
          <span className="k">No fields configured</span>
        </div>
        <div className="fvd-ws-note">
          Add a <code>fields:</code> list to your config, e.g.:
          <pre
            style={{
              margin: "4px 0",
              whiteSpace: "pre",
              userSelect: "all",
            }}
          >
{`fields:
  - Design
  - Lot
  - Wafer`}
          </pre>
          You can also add a <code>pattern:</code> line (e.g.{" "}
          <code>{"D{Design}_L{Lot}"}</code>) to fill fields from the file
          name automatically.
          <br />
          Config file:{" "}
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

  const downloadSidecar = () => {
    if (!activeId) return;
    setBusy(true);
    downloadUserMetaSidecar(activeId)
      .then(({ blob, filename }) => {
        downloadBlob(blob, filename);
        setStatus(`downloaded ${filename}`);
      })
      .catch((e: Error) => setStatus(`metadata: ${e.message}`))
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
      ? `↳ Saved in ${info.sidecar_name} next to the image — these values ` +
        `load automatically whenever this file is opened.`
      : `↳ Save writes ${info.sidecar_name} next to the image, so the ` +
        `values load automatically next time.`
    : `↳ This image didn't come from a file on disk, so values stay with ` +
      `this session only — Save still keeps them, and Save Project (File ` +
      `menu) preserves them too. Download metadata file gives you ` +
      `${info.sidecar_name} to place next to the original image so it ` +
      `loads automatically there.`;

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
        {!info.can_write_sidecar && (
          <button
            className="fvd-btn"
            onClick={downloadSidecar}
            disabled={busy}
            title={`Download the saved values as ${info.sidecar_name} (Save first if you've made changes)`}
          >
            Download metadata file
          </button>
        )}
      </div>
      <div className="fvd-ws-note">{footHint}</div>
      <HowThisWorks configPath={info.config_path} />
    </Card>
  );
}
