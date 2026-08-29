// Store bridge for the server-carried ADR 0006 region workspace. Keeping the
// network mutation here gives every future region-manager control one atomic,
// rollback-safe path instead of independently editing a client-only mirror.

import type { StateCreator } from "zustand";

import {
  replaceRegionSets as apiReplaceRegionSets,
  type ProjectRegions,
} from "../lib/api";
import { regionVisibilityKey, sanitizeRegionUi } from "../lib/regionWorkspace";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];

export function createRegionActions(
  set: Set,
): Pick<
  ViewerState,
  | "replaceRegions"
  | "selectRegion"
  | "toggleRegionSetVisibility"
  | "toggleRegionVisibility"
> {
  return {
    replaceRegions: async (regions: ProjectRegions) => {
      const accepted = await apiReplaceRegionSets(regions);
      set((state) => ({
        regions: accepted,
        regionUi: sanitizeRegionUi(state.regionUi, accepted),
        status: `updated ${accepted.sets.length} region set${
          accepted.sets.length === 1 ? "" : "s"
        }`,
      }));
    },
    selectRegion: (setId, regionId = null) => {
      set((state) => ({
        regionUi: {
          ...state.regionUi,
          selectedSetId: setId,
          selectedRegionId: regionId,
        },
      }));
    },
    toggleRegionSetVisibility: (setId) => {
      set((state) => ({
        regionUi: {
          ...state.regionUi,
          hiddenSetIds: state.regionUi.hiddenSetIds.includes(setId)
            ? state.regionUi.hiddenSetIds.filter((id) => id !== setId)
            : [...state.regionUi.hiddenSetIds, setId],
        },
      }));
    },
    toggleRegionVisibility: (setId, regionId) => {
      const key = regionVisibilityKey(setId, regionId);
      set((state) => ({
        regionUi: {
          ...state.regionUi,
          hiddenRegionKeys: state.regionUi.hiddenRegionKeys.includes(key)
            ? state.regionUi.hiddenRegionKeys.filter(
                (hidden) => hidden !== key,
              )
            : [...state.regionUi.hiddenRegionKeys, key],
        },
      }));
    },
  };
}
