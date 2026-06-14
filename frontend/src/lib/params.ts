// Parameter-field schema shared by the modal ParamDialog (menu commands)
// and the inline TransformPanel expanders. Framework-agnostic (no React)
// so lib/ tool catalogues (e.g. transformTools) can describe their own
// parameters here without importing a component.

export interface ParamField {
  key: string;
  label: string;
  type: "number" | "select" | "boolean" | "text";
  default: number | string | boolean;
  options?: string[]; // for select
  hint?: string;
}

export type ParamValues = Record<string, number | string | boolean>;

/** Coerce in-progress number strings to numbers (falling back to the
 *  field default) before a command consumes the values. Mirrors the
 *  coercion the modal dialog applied on its Run button, so the inline
 *  and modal paths produce identical parameter objects. */
export function coerceParams(
  values: ParamValues,
  fields: ParamField[],
): ParamValues {
  const out: ParamValues = {};
  for (const f of fields) {
    const v = values[f.key];
    // NB: must not use `Number(v) || default` — that maps a valid typed
    // 0 (e.g. Butterworth low-cutoff = 0 to disable) to the default,
    // since 0 is falsy. Mirror ParamFields' on-blur Number.isFinite check.
    if (f.type === "number" && typeof v === "string") {
      const n = Number(v);
      out[f.key] = Number.isFinite(n) ? n : (f.default as number);
    } else {
      out[f.key] = v;
    }
  }
  return out;
}
