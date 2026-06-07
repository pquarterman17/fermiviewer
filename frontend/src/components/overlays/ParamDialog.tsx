// Reusable parameter dialog replacing the window.prompt shims:
// promise-based — askParams(title, fields) resolves with typed values
// or null on cancel. One dialog instance lives in <App>.

import { useEffect, useState } from "react";
import { create } from "zustand";

export interface ParamField {
  key: string;
  label: string;
  type: "number" | "select" | "boolean";
  default: number | string | boolean;
  options?: string[]; // for select
  hint?: string;
}

export type ParamValues = Record<string, number | string | boolean>;

interface DialogState {
  title: string | null;
  fields: ParamField[];
  resolve: ((v: ParamValues | null) => void) | null;
  open: (
    title: string,
    fields: ParamField[],
    resolve: (v: ParamValues | null) => void,
  ) => void;
  close: () => void;
}

const useParamDialog = create<DialogState>((set) => ({
  title: null,
  fields: [],
  resolve: null,
  open: (title, fields, resolve) => set({ title, fields, resolve }),
  close: () => set({ title: null, fields: [], resolve: null }),
}));

/** Open the dialog; resolves with the values or null on cancel. */
export function askParams(
  title: string,
  fields: ParamField[],
): Promise<ParamValues | null> {
  return new Promise((resolve) => {
    useParamDialog.getState().open(title, fields, resolve);
  });
}

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
    if (e.key === "Enter") finish(values);
    if (e.key === "Escape") finish(null);
    e.stopPropagation();
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => finish(null)}>
      <div
        className="fvd-glass fvd-export fvd-param-dialog"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={onKey}
      >
        <h2>{title}</h2>
        {fields.map((f) => (
          <div key={f.key} className="fvd-ws-row">
            <span className="k" title={f.hint}>
              {f.label}
            </span>
            {f.type === "number" && (
              <input
                autoFocus={f === fields[0]}
                value={String(values[f.key] ?? "")}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
                onBlur={(e) => {
                  const n = Number(e.target.value);
                  setValues({
                    ...values,
                    [f.key]: Number.isFinite(n) ? n : f.default,
                  });
                }}
              />
            )}
            {f.type === "select" && (
              <select
                value={String(values[f.key])}
                onChange={(e) =>
                  setValues({ ...values, [f.key]: e.target.value })
                }
              >
                {(f.options ?? []).map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            )}
            {f.type === "boolean" && (
              <label className="fvd-check">
                <input
                  type="checkbox"
                  checked={Boolean(values[f.key])}
                  onChange={(e) =>
                    setValues({ ...values, [f.key]: e.target.checked })
                  }
                />
              </label>
            )}
          </div>
        ))}
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={() => finish(null)}>
            Cancel
          </button>
          <button
            className="fvd-btn primary"
            onClick={() => {
              // coerce any in-progress number strings
              const out: ParamValues = {};
              for (const f of fields) {
                const v = values[f.key];
                out[f.key] =
                  f.type === "number" && typeof v === "string"
                    ? Number(v) || (f.default as number)
                    : v;
              }
              finish(out);
            }}
          >
            Run
          </button>
        </div>
      </div>
    </div>
  );
}
