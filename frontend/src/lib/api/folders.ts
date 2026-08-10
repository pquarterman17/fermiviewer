// Typed client for POST /api/session/open-folder (PROJECT_WORKFLOW_PLAN.md
// item 1, shipped in PR #127 — routes/folders.py). Mirrors its Pydantic
// wire models — keep in sync.
//
// See lib/folderImport.ts for how the returned groups become named
// ImageGroups in the store (or one merged group, per the import dialog's
// checkbox).

import type { FourDMeta, ImageMeta } from "./core";
import { post } from "./transport";

/** One candidate group the backend already computed from a folder scan
 *  (gate G3): a first-level subfolder's name, or the selected folder's own
 *  name for loose images sitting directly inside it. `io/folder_scan.py`
 *  never emits a group with an empty `images` array. */
export interface FolderGroupResult {
  name: string;
  images: (ImageMeta | FourDMeta)[];
}

export interface OpenFolderResponse {
  groups: FolderGroupResult[];
  /** Non-image / unsupported files skipped anywhere under the selected
   *  folder(s), counted rather than silently dropped. */
  skipped: number;
  /** True when the combined import hit the 500-supported-file cap
   *  (mirrors /session/launch-dir's files[:500]). */
  truncated: boolean;
}

/** Import one or more on-disk folders. Each is recursed fully server-side
 *  and opened exactly like `/session/open` would (same calibration
 *  auto-apply, same 4D-STEM split) — 404 for a path that doesn't exist,
 *  422 for one that isn't a directory. */
export function openFolders(paths: string[]): Promise<OpenFolderResponse> {
  return post("/api/session/open-folder", { paths });
}
