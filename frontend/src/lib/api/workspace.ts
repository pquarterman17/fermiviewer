// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import type {
  PersistedResultRecord,
  ProjectInfo,
  UnavailableImage,
} from "./project";
import type { ProjectRegions, RegionWorkspaceUi } from "./regionSets";
import { json, post } from "./transport";

// ── workspace persistence ───────────────────────────────────────────
//
// The path-based saveSession/loadSession are gone with the v1 write path
// (plan #32): the File menu speaks lib/api/project.ts now. What remains here
// is the NAMED workspace switcher, which is the same `.fvp` bytes addressed by
// display name instead of a path.

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
  /** The µm-per-screen-px browse lock (W2 gate G5) — presentational, so it
   *  rides the manifest's opaque `ui_state` like everything else here except
   *  `imageGroups` and `measures`, which are promoted to validated sections.
   *  Additive (plan item 11): absent on a project saved before this key
   *  existed, and the lock loads back off in that case. */
  browseScale?: { locked: boolean; scale: number | null };
  /** Selection and visibility are presentation, not canonical geometry. */
  regionUi?: RegionWorkspaceUi;
}

// ── named workspaces (design WS4b) ──────────────────────────────────
// A workspace is the same project payload, addressed by display name and
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
  /** Placeholders, exactly as an Open Project… returns them: a workspace is a
   *  light-mode project, so its sources can go missing too. */
  unavailable: UnavailableImage[];
  /** Persisted scientific results carried by the same .fvp container. */
  results: PersistedResultRecord[];
  /** Live named analysis regions carried by the same .fvp container. */
  regions: ProjectRegions;
  project: ProjectInfo;
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
