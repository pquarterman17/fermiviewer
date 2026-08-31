// Macro record/replay (Scripting #8: macro convergence) — a recorded
// macro IS a batch recipe. Recording classifies each wire call via
// macroOpMap.wireToOp: a call with a server-op equivalent (filter/geometry
// kinds, eels_map, eels_quantify, eds_quantify) is stored as an {op, params}
// step in the SAME vocabulary ops/catalogue*.py registers and
// POST /api/batch/run accepts; a call without a currently translated wire
// shape is kept as a
// "legacy" step so the macro stays complete and replayable, but is excluded
// from anything that needs a pure op recipe (saving as a preset, exporting
// .fvbatch.json) — the macro is "partially convergent" in that case, and
// `stopRecording`/`macroLegacyCount` report how many steps aren't batchable.
//
// Persisted to localStorage so a recorded pipeline survives reloads. Old
// (pre-convergence) entries — plain {path, body}, no `kind` — are migrated
// on load: mappable ones become op steps, the rest become legacy steps, so
// nothing written by the previous version of this module crashes the new one.

import {
  runBatchRecipe,
  type BatchInputBindings,
  type BatchRecipeStep,
} from "./api/batch";
import type { ImageMeta } from "./api/core";
import { wireToOp } from "./macroOpMap";

export type MacroStep =
  | {
      kind: "op";
      op: string;
      params: Record<string, unknown>;
      inputs?: Record<string, string>;
      bindings?: BatchInputBindings;
      // a symbolically named region (ADR 0007 §11), resolved per image by
      // the runner. Carried so a scoped recipe saved as a macro replays
      // scoped rather than silently over the whole image.
      region_ref?: string;
    }
  | { kind: "legacy"; path: string; body: Record<string, unknown> };

const KEY = "fv_macro";
// only image-producing / image-transforming ops make sense in a macro
const RECORDABLE = /^\/api\/(filter$|analyze\/|eels\/|eds\/quantify$)/;

let recording = false;
let steps: MacroStep[] = [];

export function isRecording(): boolean {
  return recording;
}

export function startRecording(): void {
  recording = true;
  steps = [];
}

/** Stop + persist; returns the total captured steps, how many of those
 *  have no server-op equivalent (recorded verbatim, replayable, but not
 *  batchable as a recipe/preset), and whether the save actually persisted
 *  (false on a localStorage quota/serialization error — the caller should
 *  tell the user rather than let this throw out of a menu action). */
export function stopRecording(): { total: number; legacy: number; persisted: boolean } {
  recording = false;
  const persisted = trySetItem(KEY, JSON.stringify(steps));
  return {
    total: steps.length,
    legacy: steps.filter((s) => s.kind === "legacy").length,
    persisted,
  };
}

/** localStorage.setItem can throw (quota exceeded, private-browsing
 *  restrictions, serialization edge cases) — callers here run inside menu
 *  actions with no surrounding try/catch, so this must never propagate. */
function trySetItem(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** Called by the api layer on every POST. No-op unless recording. */
export function record(path: string, body: Record<string, unknown>): void {
  if (!recording || !RECORDABLE.test(path)) return;
  const { image_id: _id, ...rest } = body; // id re-bound at replay
  const op = wireToOp(path, rest);
  steps.push(op ? { kind: "op", ...op } : { kind: "legacy", path, body: rest });
}

/** Record a path-param op (e.g. /api/image/{id}/fft) — always legacy; no
 *  path-param endpoint has a batch-op equivalent today. */
export function recordPathOp(template: string): void {
  if (!recording) return;
  steps.push({ kind: "legacy", path: template, body: {} });
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Migrate one stored entry: current-format op/legacy steps pass through;
 *  the pre-convergence {path, body} shape (no `kind`) is reclassified
 *  through the same wireToOp table used when recording. */
function migrate(raw: unknown): MacroStep | null {
  if (!isPlainObject(raw)) return null;
  if (raw.kind === "op" && typeof raw.op === "string" && isPlainObject(raw.params)) {
    const inputs = isPlainObject(raw.inputs)
      ? Object.fromEntries(Object.entries(raw.inputs).filter(([, value]) => typeof value === "string")) as Record<string, string>
      : undefined;
    const bindings = isPlainObject(raw.bindings)
      ? raw.bindings as BatchInputBindings
      : undefined;
    return {
      kind: "op", op: raw.op, params: raw.params,
      ...(inputs ? { inputs } : {}),
      ...(bindings ? { bindings } : {}),
    };
  }
  if (raw.kind === "legacy" && typeof raw.path === "string" && isPlainObject(raw.body)) {
    return { kind: "legacy", path: raw.path, body: raw.body };
  }
  if (typeof raw.path === "string" && isPlainObject(raw.body)) {
    const op = wireToOp(raw.path, raw.body);
    return op ? { kind: "op", ...op } : { kind: "legacy", path: raw.path, body: raw.body };
  }
  return null;
}

export function loadMacro(): MacroStep[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    if (!Array.isArray(raw)) return [];
    return raw.map(migrate).filter((s): s is MacroStep => s !== null);
  } catch {
    return [];
  }
}

/** The macro's op steps only (legacy steps dropped) — a pure batch recipe,
 *  suitable for `runBatchRecipe`, saving as a preset, or .fvbatch.json
 *  export. Defaults to the persisted macro. */
export function macroOpSteps(macro: MacroStep[] = loadMacro()): BatchRecipeStep[] {
  return macro
    .filter((s): s is Extract<MacroStep, { kind: "op" }> => s.kind === "op")
    .map(({ op, params, inputs, region_ref }) => ({
      op,
      params,
      ...(inputs ? { inputs } : {}),
      ...(region_ref ? { region_ref } : {}),
    }));
}

/** How many of the macro's steps have no op equivalent (dropped by
 *  `macroOpSteps`). Zero means the macro is fully convergent. */
export function macroLegacyCount(macro: MacroStep[] = loadMacro()): number {
  return macro.filter((s) => s.kind === "legacy").length;
}

/** Overwrite the persisted macro with a plain op recipe (e.g. a loaded
 *  preset) so it becomes replayable via `replayMacro`. Returns the step
 *  count and whether the save actually persisted (see `trySetItem`). */
export function setMacroFromRecipe(
  recipeSteps: BatchRecipeStep[],
  inputBindings: BatchInputBindings = {},
): { n: number; persisted: boolean } {
  const next: MacroStep[] = recipeSteps.map(({ op, params, inputs, region_ref }) => ({
    kind: "op", op, params,
    ...(inputs ? { inputs } : {}),
    ...(region_ref ? { region_ref } : {}),
    ...(inputs
      ? { bindings: Object.fromEntries(
          Object.values(inputs)
            .filter((name) => inputBindings[name] !== undefined)
            .map((name) => [name, inputBindings[name]]),
        ) }
      : {}),
  }));
  const persisted = trySetItem(KEY, JSON.stringify(next));
  return { n: next.length, persisted };
}

/** Replay the stored macro starting from `startId`. Every produced image is
 *  reported via `onImage` and becomes the next step's input. Op steps run
 *  through the same server recipe runner batch presets use (one-step,
 *  single-input recipes, chained per step); legacy steps replay via their
 *  original wire call. */
export async function replayMacro(
  startId: string,
  onImage: (m: ImageMeta) => void,
): Promise<number> {
  const macro = loadMacro();
  let current = startId;
  let n = 0;
  for (const st of macro) {
    if (st.kind === "op") {
      const result = await runBatchRecipe(
        [current],
        [{ op: st.op, params: st.params, ...(st.inputs ? { inputs: st.inputs } : {}) }],
        () => {},
        st.bindings ?? {},
      );
      const output = result.outputs[0];
      if (output.status !== "done") {
        throw new Error(`step ${n + 1} (${st.op}): ${output.error ?? "failed"}`);
      }
      if (output.derived) {
        onImage(output.derived);
        current = output.derived.id;
      }
    } else {
      const path = st.path.replace("{id}", current);
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...st.body, image_id: current }),
      });
      if (!res.ok) {
        let detail = `${res.status}`;
        try {
          detail =
            ((await res.json()) as { detail?: string }).detail ?? detail;
        } catch {
          /* non-JSON error body */
        }
        throw new Error(`step ${n + 1} (${st.path}): ${detail}`);
      }
      const out = (await res.json()) as Record<string, unknown>;
      const meta = extractImage(out);
      if (meta) {
        onImage(meta);
        current = meta.id;
      }
    }
    n++;
  }
  return n;
}

function extractImage(out: Record<string, unknown>): ImageMeta | null {
  if (typeof out["id"] === "string" && Array.isArray(out["shape"])) {
    return out as unknown as ImageMeta;
  }
  const inner = out["image"] as Record<string, unknown> | undefined;
  if (inner && typeof inner["id"] === "string") {
    return inner as unknown as ImageMeta;
  }
  const map = out["map"] as Record<string, unknown> | undefined;
  if (map && typeof map["id"] === "string") {
    return map as unknown as ImageMeta;
  }
  return null;
}
