// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import { json, post } from "./transport";

// ── user-configurable metadata (custom fields + filename auto-fill) ──────

export interface MetaField {
  name: string;
  type: string;
  options: string[];
}

export interface UserMeta {
  fields: MetaField[];
  patterns: string[];
  config_path: string;
  values: Record<string, string>;
  source_path: string | null;
  can_write_sidecar: boolean;
  has_sidecar: boolean;
}

/** Resolved custom-metadata fields + values for one image (filename →
 *  sidecar → session), plus where they can be persisted. */
export async function getUserMeta(id: string): Promise<UserMeta> {
  return json(await fetch(`/api/image/${id}/usermeta`));
}

/** Persist custom-metadata values to the image + its sidecar (if on disk). */
export function saveUserMeta(
  id: string,
  values: Record<string, string>,
): Promise<{ values: Record<string, string>; wrote_sidecar: boolean }> {
  return post(`/api/image/${id}/usermeta`, { values });
}

export interface BatchAutofillResult {
  results: {
    id: string;
    name: string;
    matched: boolean;
    filled: number;
    wrote_sidecar: boolean;
  }[];
  n_matched: number;
  n_total: number;
}

/** Apply the filename pattern to many images at once, writing each sidecar. */
export function batchAutofill(imageIds: string[]): Promise<BatchAutofillResult> {
  return post("/api/usermeta/batch-autofill", { image_ids: imageIds });
}

export function analyzeRoughness(
  id: string,
): Promise<Record<string, number | string>> {
  return post("/api/analyze/roughness", { image_id: id });
}

export function applyCalibration(
  id: string,
  pixelSize: number,
  unit: string,
  saveAsKey?: string,
): Promise<{ image: ImageMeta }> {
  return post("/api/calibration/apply", {
    image_id: id,
    pixel_size: pixelSize,
    unit,
    save_as_key: saveAsKey || null,
  });
}

/** Drop a calibration back to uncalibrated pixels (Calibration card Clear). */
export function clearCalibration(id: string): Promise<{ image: ImageMeta }> {
  return post("/api/calibration/clear", { image_id: id });
}

/** Headerless RAW import with explicit geometry (checklist L). */
export function openRaw(opts: {
  path: string;
  width: number;
  height: number;
  bitDepth?: number;
  byteOrder?: "little" | "big";
  headerBytes?: number;
}): Promise<ImageMeta> {
  return post("/api/session/open-raw", {
    path: opts.path,
    width: opts.width,
    height: opts.height,
    bit_depth: opts.bitDepth ?? 16,
    byte_order: opts.byteOrder ?? "little",
    header_bytes: opts.headerBytes ?? 0,
  });
}

export function renameImage(id: string, name: string): Promise<ImageMeta> {
  return post(`/api/image/${id}/rename`, { name });
}

/** Multi-panel labeled figure → PNG blob. */
export async function exportFigure(
  ids: string[],
  opts: { cols?: number; gap?: number; scale?: number; cmap?: string } = {},
): Promise<Blob> {
  const res = await fetch("/api/export/figure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      cols: opts.cols ?? 0,
      gap: opts.gap ?? 4,
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary error body */
    }
    throw new Error(detail);
  }
  return res.blob();
}

/** Auto-detect a burned-in scale bar in the bottom strip. */
export function detectScaleBar(id: string): Promise<{
  found: boolean;
  bar_len: number;
  msg: string;
}> {
  return post("/api/calibration/detect-bar", { image_id: id });
}

/** Explode a 3D cube into per-frame derived images. */
export function explodeStack(id: string): Promise<ImageMeta[]> {
  return post(`/api/image/${id}/explode`, {});
}

export function updateMetadata(
  id: string,
  updates: Record<string, string | number | boolean>,
): Promise<ImageMeta> {
  return post(`/api/image/${id}/metadata`, { updates });
}

/** Render many images server-side into one ZIP. */
export async function exportBatch(
  ids: string[],
  opts: { format?: string; scale?: number; cmap?: string } = {},
): Promise<Blob> {
  const res = await fetch("/api/export/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      format: opts.format ?? "png",
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary error body */
    }
    throw new Error(detail);
  }
  return res.blob();
}

/** Animate selected images into a GIF; returns the file blob. */
export async function exportGif(
  ids: string[],
  opts: { fps?: number; scale?: number; cmap?: string } = {},
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch("/api/export/gif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      fps: opts.fps ?? 4,
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary or empty error body */
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await res.blob(), filename: match?.[1] ?? "stack.gif" };
}

export interface CalibrationEntry {
  pixel_size: number;
  unit: string;
  note: string;
  saved: string;
}

export async function listCalibrations(): Promise<
  Record<string, CalibrationEntry>
> {
  const r = await fetch("/api/calibration");
  if (!r.ok) throw new Error(`calibration list failed: ${r.status}`);
  return ((await r.json()) as { entries: Record<string, CalibrationEntry> })
    .entries;
}

export async function deleteCalibration(key: string): Promise<void> {
  const r = await fetch(`/api/calibration/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`calibration delete failed: ${r.status}`);
}

/** Apply a STORED calibration (by key) to an image. */
export function applyCalibrationKey(
  id: string,
  key: string,
): Promise<{ image: ImageMeta }> {
  return post("/api/calibration/apply", { image_id: id, key });
}
