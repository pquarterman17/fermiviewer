// Canonical named-region workspace (ADR 0006, roadmap 4B). Coordinates are
// always 0-based [row, col] floats with inclusive bounds. This is distinct
// from normalized [x, y] annotation measures and from frozen result snapshots.

import { json, post } from "./transport";

export type RegionPoint = [number, number];
export type RegionBounds = [number, number, number, number];

interface RegionShapeBase {
  holes?: RegionPoint[][];
}

export interface RegionPolygonShape extends RegionShapeBase {
  kind: "polygon";
  outline: RegionPoint[];
  bounds?: never;
}

export interface RegionBoundedShape extends RegionShapeBase {
  kind: "rect" | "ellipse" | "circle";
  bounds: RegionBounds;
  outline?: never;
}

export type RegionShape = RegionPolygonShape | RegionBoundedShape;

export interface RegionPart {
  mode: "include" | "exclude";
  shape: RegionShape;
}

export interface ProjectRegion {
  id: string;
  name: string | null;
  region_class: string | null;
  parts: RegionPart[];
  meta: Record<string, unknown>;
}

export interface ProjectRegionSet {
  id: string;
  name: string | null;
  image_id: string | null;
  regions: ProjectRegion[];
  meta: Record<string, unknown>;
}

export interface ProjectRegionClass {
  id: string;
  label: string | null;
  color: string | null;
  note: string | null;
}

export interface ProjectRegions {
  schema: 1;
  classes: ProjectRegionClass[];
  sets: ProjectRegionSet[];
}

/** Presentational manager state persisted in ui_state, never geometry. */
export interface RegionWorkspaceUi {
  selectedSetId: string | null;
  selectedRegionId: string | null;
  hiddenSetIds: string[];
  /** Opaque set+region keys; region ids need only be unique inside one set. */
  hiddenRegionKeys: string[];
}

export const EMPTY_PROJECT_REGIONS: ProjectRegions = {
  schema: 1,
  classes: [],
  sets: [],
};

/** Read the server-carried region workspace without reopening the project. */
export async function listRegionSets(): Promise<ProjectRegions> {
  return json(await fetch("/api/region-sets"));
}

/** Validate and atomically replace the server-carried region workspace. */
export function replaceRegionSets(regions: ProjectRegions): Promise<ProjectRegions> {
  return post("/api/region-sets/replace", regions);
}
