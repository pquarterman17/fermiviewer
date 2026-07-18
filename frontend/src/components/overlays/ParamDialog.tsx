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
  const title = useParamDialog((s) => s.title);
  const fields = useParamDialog((s) => s.fields);
  const resolve = useParamDialog((s) => s.resolve);
  const close = useParamDialog((s) => s.close);
  const [values, setValues] = useState<ParamValues>({});

  useEffect(() => {
    if (title !== null) {
      const init: ParamValues = {};
      for (const f of fields) init[f.key] = f.default;
      setValues(init);
    }
  }, [title, fields]);

  if (title === null) return null;

  const finish = (v: ParamValues | null) => {
    resolve?.(v);
    close();
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
