// Typed client for the `.fvp` project surface (routes/project_io.py,
// PROJECT_WORKFLOW_PLAN items 32–35; format spec docs/adr/0002).
//
// Three user actions, three calls:
//   Save Project           -> saveProject(path, "light")
//   Export Project Bundle  -> saveProject(path, "bundle")
//   Open Project…          -> openProject(path)   (.fvp, or a legacy v1 .json)
//   Locate folder…         -> relocateProject(root)
//
// Mirrors the route's Pydantic wire models — keep in sync.

import type { ImageMeta } from "./core";
import { post } from "./transport";
import type { SessionClientState } from "./workspace";

/** `light` references source pixels and embeds derived images (everyday save,
 *  megabytes); `bundle` embeds everything so the file needs no source folders
 *  (transfer to another machine, hundreds of MB). */
export type ProjectPayloadMode = "light" | "bundle";

/** An image whose pixels this machine could not find. It keeps its name and
 *  reference, and its sample membership / parameters / measurements ride the
 *  restored client state — so nothing about it is lost, and a save writes the
 *  reference straight back (ADR 0002 §4). There is deliberately no shape or
 *  dtype: there is nothing to render, and inventing zeros would put a broken
 *  image in the library instead of an honest placeholder. */
export interface UnavailableImage {
  id: string;
  name: string;
  /** Path relative to the project's declared data root, POSIX separators. */
  rel: string | null;
  /** Absolute path at import, provenance only — never used for resolution. */
  source: string | null;
  size_bytes: number | null;
}

/** What the SESSION now has open. After an append load (`replace: false`) that
 *  is still the project that was already there — merging a second project's
 *  images does not change which file the session belongs to. */
export interface ProjectInfo {
  path: string | null;
  name: string | null;
  payload_mode: ProjectPayloadMode;
  data_root_hint: string | null;
  primary_param: string | null;
  n_unavailable: number;
  /** The payload mode of the file just read, which on an append load is not
   *  necessarily the session's. */
  loaded_payload_mode: ProjectPayloadMode;
}

export interface ProjectLoadResponse {
  images: ImageMeta[];
  client_state: SessionClientState | null;
  unavailable: UnavailableImage[];
  project: ProjectInfo;
}

export interface ProjectSaveResponse {
  path: string;
  payload_mode: ProjectPayloadMode;
  n_images: number;
  n_unavailable: number;
  dropped_samples: number;
  dropped_measures: number;
}

/** A resolved file whose byte count is not the one recorded at save time.
 *  Reported rather than enforced: the shape/kind check is the real guard, and
 *  a re-exported file can differ in bytes while holding the same image. */
export interface ProjectSizeMismatch {
  id: string;
  name: string;
  rel: string;
  expected_bytes: number;
  actual_bytes: number;
}

export interface RelocateResponse {
  root: string;
  /** Images that came back to life — now in the session, ready to render. */
  resolved: ImageMeta[];
  still_unavailable: UnavailableImage[];
  mismatches: ProjectSizeMismatch[];
  /** Found under the chosen folder but holding something else: a wrong-DATA
   *  folder, which needs a different message from a wrong-path one. */
  rejected: { id: string; name: string }[];
}

/** Write the session as a `.fvp` (the suffix is applied server-side). */
export function saveProject(
  path: string,
  mode: ProjectPayloadMode,
  clientState: SessionClientState,
  name?: string | null,
): Promise<ProjectSaveResponse> {
  return post("/api/project/save", {
    path,
    mode,
    client_state: clientState,
    name: name ?? null,
  });
}

/** Open a `.fvp`, or a legacy v1 `.json`/`.npz` pair (upgraded in memory —
 *  the next save writes a `.fvp`). */
export function openProject(path: string): Promise<ProjectLoadResponse> {
  return post("/api/project/load", { path });
}

/** Re-resolve everything still unavailable against a folder the user picked.
 *  Invokable at any time and repeatable: samples that moved to different
 *  folders each get their own pick, and the root is APPENDED to the
 *  resolution order rather than replacing the project's recorded hint. */
export function relocateProject(root: string): Promise<RelocateResponse> {
  return post("/api/project/relocate", { root });
}
