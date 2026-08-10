// Project save / open / locate — the store slice behind the File menu's
// project commands (PROJECT_WORKFLOW_PLAN items 32–35).
//
// A slice of its own rather than more lines in viewer.ts, which just
// graduated from its legacy cap and must not regrow past the 500-line
// ceiling. It replaces the old saveWorkspace/loadWorkspace pair: the same two
// gestures, now writing the single-file `.fvp` (docs/adr/0002) with a payload
// mode, and with a third gesture — Locate folder… — that only a referenced
// format needs.

import type { StateCreator } from "zustand";

import {
  openProject as apiOpenProject,
  relocateProject as apiRelocateProject,
  saveProject as apiSaveProject,
  type ProjectPayloadMode,
  type RelocateResponse,
} from "../lib/api";
import {
  clientState,
  ingestImages,
  restoreBrowseScale,
  sessionSlice,
} from "./viewerSession";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];
type Get = Parameters<StateCreator<ViewerState>>[1];

const plural = (n: number): string => (n === 1 ? "" : "s");

/** Status text for one relocate, in the order the user cares about: what came
 *  back, then what did not, then what looked wrong. A size mismatch is
 *  REPORTED, never used to reject the folder — those pixels already passed the
 *  shape/kind check, and a re-exported file legitimately differs in bytes. */
export function relocateStatus(r: RelocateResponse): string {
  const parts = [`located ${r.resolved.length} image${plural(r.resolved.length)}`];
  if (r.still_unavailable.length) {
    parts.push(`${r.still_unavailable.length} still missing`);
  }
  if (r.rejected.length) {
    parts.push(`${r.rejected.length} found but not matching`);
  }
  if (r.mismatches.length) {
    parts.push(
      `size differs from the saved project: ${r.mismatches
        .map((m) => m.name)
        .join(", ")}`,
    );
  }
  return parts.join(" · ");
}

export function createProjectActions(
  set: Set,
  get: Get,
): Pick<ViewerState, "saveProject" | "openProject" | "locateData"> {
  return {
    saveProject: async (path, mode: ProjectPayloadMode = "light") => {
      const s = get();
      const r = await apiSaveProject(
        path,
        mode,
        clientState(s),
        s.currentProject?.name,
      );
      const missing = r.n_unavailable
        ? ` (${r.n_unavailable} unavailable, reference${plural(
            r.n_unavailable,
          )} kept)`
        : "";
      set({
        currentProject: { path: r.path, name: s.currentProject?.name ?? null },
        status: `saved ${mode === "bundle" ? "bundle" : "project"}: ${
          r.n_images
        } image${plural(r.n_images)} → ${r.path}${missing}`,
      });
    },

    openProject: async (path) => {
      const r = await apiOpenProject(path);
      const missing = r.unavailable.length
        ? ` · ${r.unavailable.length} unavailable — File ▸ Locate Data Folder…`
        : "";
      restoreBrowseScale(r.client_state);
      set({
        ...sessionSlice(r, get().overlay),
        // an ad-hoc file open isn't a named workspace
        currentWorkspace: null,
        // the SESSION's project, which after an append load is still the one
        // that was already open rather than the file just read
        currentProject: r.project.path
          ? { path: r.project.path, name: r.project.name }
          : null,
        status: `opened ${r.images.length} image${plural(
          r.images.length,
        )}${missing}`,
      });
    },

    /** Re-point the missing data at a folder the user picked. Repeatable by
     *  design: samples that moved to different folders each need their own
     *  pick, so this NARROWS `unavailable` rather than clearing it. */
    locateData: async (root) => {
      const r = await apiRelocateProject(root);
      // Resolved images join the library through the SAME ingest path a normal
      // open uses, so display defaults, history seeding and ordering behave
      // identically — a re-pointed image is not a second kind of image.
      if (r.resolved.length) ingestImages(set, r.resolved);
      const unavailable: ViewerState["unavailable"] = {};
      for (const u of r.still_unavailable) unavailable[u.id] = u;
      set({ unavailable, status: relocateStatus(r) });
    },
  };
}
