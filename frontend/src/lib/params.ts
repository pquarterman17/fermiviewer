// Parameter-field schema shared by the modal ParamDialog (menu commands)
// and the inline TransformPanel expanders. Framework-agnostic (no React)
// so lib/ tool catalogues (e.g. transformTools) can describe their own
// parameters here without importing a component.
//
// Shared platform code — keep in sync with quantized's
// frontend/src/lib/params.ts (ported from here originally; quantized then
// hardened coerceParams and folded that back into this copy, 2026-08-05).

export interface ParamField {
  key: string;
  label: string;
  type: "number" | "select" | "boolean" | "text";
  default: number | string | boolean;
  options?: string[]; // for select
  hint?: string;
}

export type ParamValues = Record<string, number | string | boolean>;

/** Coerce in-progress number strings to numbers (falling back to the field
 *  default) before a command consumes the values. Mirrors the coercion the
 *  modal dialog applied on its Run button, so the inline and modal paths
 *  produce identical parameter objects.
 *
 *  Guarantees the output has EVERY field's key, even if `values` is missing
 *  one (falls back to `f.default`) — the shape a caller's `params.someKey`
 *  can rely on regardless of how `values` got built. ParamDialog's own local
 *  state is normally fully populated before a user can interact with it, but
 *  this is the last chokepoint before a command consumes the result, so it
 *  stays defensive: a caller that does `(params.x_label as string).trim()`
 *  with no guard of its own turns an `undefined` here into a thrown error
 *  OUTSIDE the command's own try/catch (quantized's P0.4 finding 15,
 *  2026-07-27: traced to a ParamDialog render race, now fixed at the source
 *  in both repos' ParamDialog.tsx — this guard is defense in depth for
 *  every OTHER askParams() caller, not a substitute for that fix). */
export function coerceParams(
  values: ParamValues,
  fields: ParamField[],
): ParamValues {
  const out: ParamValues = {};
  for (const f of fields) {
    const v = values[f.key];
    if (v === undefined) {
      out[f.key] = f.default;
    } else if (f.type === "number" && typeof v === "string") {
      // NB: must not use `Number(v) || default` — that maps a valid typed
      // 0 (e.g. Butterworth low-cutoff = 0 to disable) to the default,
      // since 0 is falsy. Mirror ParamFields' on-blur Number.isFinite check.
      const n = Number(v);
      out[f.key] = Number.isFinite(n) ? n : (f.default as number);
    } else {
      out[f.key] = v;
    }
  }
  return out;
}
