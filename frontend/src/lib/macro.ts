// Macro record/replay (checklist N): captures derived-op API calls at
// the wire layer and replays them against any image, chaining lineage
// (each step that produces an image feeds the next step). Persisted to
// localStorage so a recorded pipeline survives reloads.

import type { ImageMeta } from "./api";

export interface MacroStep {
  /** endpoint path; "{id}" marks the image-id slot for path-param ops */
  path: string;
  body: Record<string, unknown>;
}

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

/** Stop + persist; returns the number of captured steps. */
export function stopRecording(): number {
  recording = false;
  localStorage.setItem(KEY, JSON.stringify(steps));
  return steps.length;
}

/** Called by the api layer on every POST. No-op unless recording. */
export function record(path: string, body: Record<string, unknown>): void {
  if (!recording || !RECORDABLE.test(path)) return;
  const { image_id: _id, ...rest } = body; // id re-bound at replay
  steps.push({ path, body: rest });
}

/** Record a path-param op (e.g. /api/image/{id}/fft). */
export function recordPathOp(template: string): void {
  if (!recording) return;
  steps.push({ path: template, body: {} });
}

export function loadMacro(): MacroStep[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as MacroStep[];
  } catch {
    return [];
  }
}

/** Replay the stored macro starting from `startId`. Every produced
 *  image is reported via `onImage` and becomes the next step's input. */
export async function replayMacro(
  startId: string,
  onImage: (m: ImageMeta) => void,
): Promise<number> {
  const macro = loadMacro();
  let current = startId;
  let n = 0;
  for (const st of macro) {
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
