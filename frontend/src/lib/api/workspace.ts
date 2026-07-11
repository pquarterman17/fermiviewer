// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import { json, post } from "./transport";

// ── workspace persistence ───────────────────────────────────────────

export interface SessionClientState {
  order?: string[];
  activeId?: string | null;
  views?: Record<string, unknown>;
  display?: Record<string, unknown>;
  measures?: Record<string, unknown>;
  overlay?: unknown;
  /** Named saved ROIs per image (Tier-2 #5 ROI Manager); keyed by image id. */
  savedRois?: Record<string, unknown>;
  /** Named, reusable image groups for side-by-side compare. */
  imageGroups?: unknown;
  /** The compare grid: per-pane image + group bindings, plus its shape. */
  sbsPanes?: unknown;
  sbsRows?: number;
  sbsCols?: number;
}

export async function saveSession(
  path: string,
  clientState: SessionClientState,
): Promise<{ n_images: number; json_path: string }> {
  return post("/api/session/save", { path, client_state: clientState });
}

export async function loadSession(
  path: string,
): Promise<{ images: ImageMeta[]; client_state: SessionClientState | null }> {
  return post("/api/session/load", { path });
}

// ── named workspaces (design WS4b) ──────────────────────────────────
// A workspace is the same session payload, addressed by display name and
// kept under the OS config dir instead of a user-typed path.

export interface WorkspaceInfo {
  slug: string;
  name: string;
  saved_at: string | null;
  n_images: number;
}

export async function listWorkspaces(): Promise<WorkspaceInfo[]> {
  const r = await json<{ workspaces: WorkspaceInfo[] }>(
    await fetch("/api/workspaces"),
  );
  return r.workspaces;
}

export async function saveWorkspaceNamed(
  name: string,
  clientState: SessionClientState,
): Promise<{ slug: string; name: string; n_images: number }> {
  return post("/api/workspaces/save", { name, client_state: clientState });
}

export async function loadWorkspaceNamed(slug: string): Promise<{
  images: ImageMeta[];
  client_state: SessionClientState | null;
  name: string;
}> {
  return post("/api/workspaces/load", { slug });
}

export async function deleteWorkspace(
  slug: string,
): Promise<{ deleted: boolean }> {
  return json(await fetch(`/api/workspaces/${slug}`, { method: "DELETE" }));
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
