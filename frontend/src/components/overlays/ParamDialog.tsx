// Reusable parameter dialog replacing the window.prompt shims:
// promise-based — askParams(title, fields) resolves with typed values
// or null on cancel. One dialog instance lives in <App>.

import { useEffect, useState } from "react";

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

  // Keyed on the request identity, not its title: two queued requests may share
  // a title, and the next one still needs its own defaults.
  useEffect(() => {
    if (!active) return;
    const init: ParamValues = {};
    for (const f of active.fields) init[f.key] = f.default;
    setValues(init);
  }, [active]);

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
