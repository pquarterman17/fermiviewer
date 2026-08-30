// Store bridge for the server-carried ADR 0006 region workspace. Keeping the
// network mutation here gives every future region-manager control one atomic,
// rollback-safe path instead of independently editing a client-only mirror.

import type { StateCreator } from "zustand";

import {
  listRegionSets,
  replaceRegionSets as apiReplaceRegionSets,
  type ProjectRegions,
} from "../lib/api";
import { regionVisibilityKey, sanitizeRegionUi } from "../lib/regionWorkspace";
import type { ViewerState } from "./viewerState";

type Set = Parameters<StateCreator<ViewerState>>[0];
type Get = Parameters<StateCreator<ViewerState>>[1];

export function createRegionActions(
  set: Set,
  get: Get,
): Pick<
  ViewerState,
  | "replaceRegions"
  | "hydrateRegions"
  | "refreshRegions"
  | "selectRegion"
  | "toggleRegionSetVisibility"
  | "toggleRegionVisibility"
> {
  return {
    hydrateRegions: (regions) => {
      set((state) => ({
        regions,
        regionsLoaded: true,
        regionsLoadError: null,
        regionUi: sanitizeRegionUi(state.regionUi, regions),
      }));
    },
    refreshRegions: async () => {
      set({ regionsLoaded: false, regionsLoadError: null });
      try {
        const regions = await listRegionSets();
        get().hydrateRegions(regions);
      } catch (error) {
        const message = (error as Error).message || "request failed";
        set({
          regionsLoaded: false,
          regionsLoadError: message,
          status: `analysis regions unavailable: ${message}`,
        });
        throw error;
      }
    },
    replaceRegions: async (regions: ProjectRegions) => {
      if (!get().regionsLoaded) {
        throw new Error("analysis regions are not loaded; retry before editing");
      }
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
