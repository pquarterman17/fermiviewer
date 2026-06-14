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
    out[f.key] =
      f.type === "number" && typeof v === "string"
        ? Number(v) || (f.default as number)
        : v;
  }
  return out;
}
