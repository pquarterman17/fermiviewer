// Reusable parameter dialog replacing the window.prompt shims:
// promise-based — askParams(title, fields) resolves with typed values
// or null on cancel. One dialog instance lives in <App>.
//
// Shared platform code — keep the render-time reset pattern below in sync
// with quantized's frontend/src/components/overlays/ParamDialog.tsx.

import { useState } from "react";

import {
  coerceParams,
  type ParamValues,
} from "../../lib/params";
import { useParamDialog } from "../../store/params";
import ModalDialog from "./ModalDialog";
import { ParamFieldRow } from "./ParamFields";

export default function ParamDialog() {
  // ONE selector returning the queue head. Reading `queue[0]` hands back a
  // stable object reference; deriving `title`/`fields` inside a selector would
  // build a fresh value each call and re-render forever.
  const active = useParamDialog((s) => s.queue[0]);
  const submit = useParamDialog((s) => s.submit);
  const [values, setValues] = useState<ParamValues>({});

  // Reset `values` to the active request's field defaults SYNCHRONOUSLY,
  // during render, rather than in a useEffect (react.dev "adjusting state
  // when a prop changes"). Keyed on the request identity (`active.id`), not
  // its title: two queued requests may share a title, and the next one
  // still needs its own defaults.
  //
  // A useEffect-based reset used to run here instead — it fires strictly
  // AFTER the first commit/paint, leaving a window where `values` still
  // holds the PREVIOUS request's leftovers (or the initial `{}`). A fast
  // field edit landing inside that window races the effect: the edit's
  // `setValues({...values, [key]: v})` and the effect's `setValues(init)`
  // both close over the SAME stale `values`, and `useState` REPLACES rather
  // than merges, so whichever call lands second wins outright — when the
  // edit wins, every OTHER field's key goes missing from the resolved
  // result. This is the exact mechanism quantized traced live (P0.4 finding
  // 15, 2026-07-27: the "Export figure…" dialog hung with zero network
  // activity, no toast, no console error) and fixed by moving the reset
  // here, during render — ported into this repo preventatively since
  // fermiviewer's askParams() has the same 13+ callers exposed to it
  // (BatchDialog, MenuBar, menus/*, lib/rename.ts). Resetting during render
  // means the FIRST commit already has full, race-free defaults, so there
  // is no window left for an edit to land in.
  const [initializedId, setInitializedId] = useState<number | null>(null);
  if (active && active.id !== initializedId) {
    const init: ParamValues = {};
    for (const f of active.fields) init[f.key] = f.default;
    setValues(init);
    setInitializedId(active.id);
  }

  if (!active) return null;

  const { title, fields } = active;

  const finish = (v: ParamValues | null) => {
    submit(v);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      finish(coerceParams(values, fields));
    }
    if (e.key === "Escape") {
      e.preventDefault();
      finish(null);
    }
    e.stopPropagation();
  };

  return (
    <ModalDialog
      ariaLabel={title}
      className="fvd-export fvd-param-dialog"
      onClose={() => finish(null)}
      onKeyDown={onKey}
    >
        <h2>{title}</h2>
        {fields.map((f, i) => (
          <ParamFieldRow
            key={f.key}
            field={f}
            value={values[f.key]}
            autoFocus={i === 0}
            onChange={(v) => setValues({ ...values, [f.key]: v })}
          />
        ))}
        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={() => finish(null)}
            title="Cancel — close without running (Esc)"
          >
            Cancel
          </button>
          <button
            className="fvd-btn primary"
            onClick={() => finish(coerceParams(values, fields))}
            title="Run the operation with these parameters (Enter)"
          >
            Run
          </button>
        </div>
    </ModalDialog>
  );
}
