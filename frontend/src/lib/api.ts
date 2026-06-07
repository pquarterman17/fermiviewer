// Typed client for the FastAPI backend (handoff §8). Mirrors the
// Pydantic wire models in src/fermiviewer/models.py — keep in sync.

export type DataKind = "image" | "spectrum" | "spectrum_image";

export interface ImageMeta {
  id: string;
  name: string;
  kind: DataKind;
  shape: number[];
  dtype: string;
  pixel_size: number | null;
  pixel_unit: string;
  n_channels: number | null;
  energy_first: number | null;
  energy_last: number | null;
  energy_units: string;
  meta: Record<string, string | number | boolean>;
}

export interface Histogram {
  bins: number[];
  counts: number[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export async function openSession(paths: string[]): Promise<ImageMeta[]> {
  return json(
    await fetch("/api/session/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }),
  );
}

export async function listImages(): Promise<ImageMeta[]> {
  return json(await fetch("/api/session/images"));
}

export async function closeImage(id: string): Promise<void> {
  await json(await fetch(`/api/image/${id}`, { method: "DELETE" }));
}

export async function fetchHistogram(
  id: string,
  bins = 256,
): Promise<Histogram> {
  return json(await fetch(`/api/image/${id}/histogram?bins=${bins}`));
}

/** URL for the windowed 8-bit PNG render (Stage texture + thumbnails). */
export function renderUrl(
  id: string,
  opts: { lo?: number; hi?: number; gamma?: number } = {},
): string {
  const q = new URLSearchParams();
  if (opts.lo !== undefined) q.set("lo", String(opts.lo));
  if (opts.hi !== undefined) q.set("hi", String(opts.hi));
  if (opts.gamma !== undefined) q.set("gamma", String(opts.gamma));
  const qs = q.toString();
  return `/api/image/${id}/render${qs ? `?${qs}` : ""}`;
}
