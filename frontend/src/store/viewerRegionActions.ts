// Store bridge for the server-carried ADR 0006 region workspace. Keeping the
// network mutation here gives every future region-manager control one atomic,
// rollback-safe path instead of independently editing a client-only mirror.

import type { StateCreator } from "zustand";

import {
  replaceRegionSets as apiReplaceRegionSets,
  type ProjectRegions,
} from "../lib/api";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];

export function createRegionActions(
  set: Set,
): Pick<ViewerState, "replaceRegions"> {
  return {
    replaceRegions: async (regions: ProjectRegions) => {
      const accepted = await apiReplaceRegionSets(regions);
      set({
        regions: accepted,
        status: `updated ${accepted.sets.length} region set${
          accepted.sets.length === 1 ? "" : "s"
        }`,
      });
    },
  };
}
