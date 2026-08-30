import type {
  ProjectRegion,
  ProjectRegionSet,
  ProjectRegions,
  RegionShape,
  RegionWorkspaceUi,
} from "./api";
import type { Measure } from "../store/viewerTypes";

export const REGION_DRAWING_KINDS = new Set<Measure["kind"]>([
  "polygon",
  "lasso",
  "roi",
  "ellipse",
]);

export function measureToRegionShape(
  measure: Measure,
  width: number,
  height: number,
): RegionShape | null {
  if (!REGION_DRAWING_KINDS.has(measure.kind) || width <= 0 || height <= 0) {
    return null;
  }
  const allRings = [measure.pts, ...(measure.holes ?? [])];
  if (allRings.some((points) => points.some(({ x, y }) => !Number.isFinite(x) || !Number.isFinite(y)))) {
    return null;
  }
  const ring = (points: Measure["pts"]) =>
    points.map(({ x, y }) => [y * height, x * width] as [number, number]);
  if (measure.kind === "polygon" || measure.kind === "lasso") {
    if (measure.pts.length < 3 || measure.holes?.some((hole) => hole.length < 3)) {
      return null;
    }
    return {
      kind: "polygon",
      outline: ring(measure.pts),
      holes: measure.holes?.map(ring),
    };
  }
  if (measure.pts.length < 2) return null;
  const [a, b] = measure.pts;
  const rows = [a.y * height, b.y * height].sort((x, y) => x - y);
  const cols = [a.x * width, b.x * width].sort((x, y) => x - y);
  return {
    kind: measure.kind === "ellipse" ? "ellipse" : "rect",
    bounds: [rows[0], cols[0], rows[1], cols[1]],
  };
}

export function regionShapeToMeasure(
  shape: RegionShape,
  width: number,
  height: number,
): Omit<Measure, "id"> | null {
  if (width <= 0 || height <= 0) return null;
  const point = ([row, col]: [number, number]) => ({
    x: col / width,
    y: row / height,
  });
  if (shape.kind === "polygon") {
    return {
      kind: "polygon",
      pts: shape.outline.map(point),
      holes: shape.holes?.map((ring) => ring.map(point)),
    };
  }
  if (shape.kind === "circle" || shape.holes?.length) return null;
  const [r0, c0, r1, c1] = shape.bounds;
  return {
    kind: shape.kind === "ellipse" ? "ellipse" : "roi",
    pts: [point([r0, c0]), point([r1, c1])],
  };
}

export function regionShapeSummary(shape: RegionShape): string {
  if (shape.kind === "polygon") {
    const holes = shape.holes?.length ?? 0;
    return `${shape.outline.length} vertices${holes ? ` · ${holes} hole${holes === 1 ? "" : "s"}` : ""}`;
  }
  if (shape.kind === "circle") {
    const radius = Math.abs(shape.bounds[2] - shape.bounds[0]) / 2;
    return `circle · r ${Number(radius.toFixed(2))} px`;
  }
  return shape.kind === "ellipse" ? "ellipse bounds" : "rectangle bounds";
}

export function regionVisibilityKey(setId: string, regionId: string): string {
  return JSON.stringify([setId, regionId]);
}

export function sanitizeRegionUi(
  ui: RegionWorkspaceUi,
  workspace: ProjectRegions,
): RegionWorkspaceUi {
  const setIds = new Set(workspace.sets.map((group) => group.id));
  const regionKeys = new Set(
    workspace.sets.flatMap((group) =>
      group.regions.map((region) => regionVisibilityKey(group.id, region.id))),
  );
  const selectedSetId = ui.selectedSetId && setIds.has(ui.selectedSetId)
    ? ui.selectedSetId
    : null;
  const selectedSet = workspace.sets.find((group) => group.id === selectedSetId);
  const selectedRegionId =
    ui.selectedRegionId && selectedSet?.regions.some((region) => region.id === ui.selectedRegionId)
      ? ui.selectedRegionId
      : null;
  return {
    selectedSetId,
    selectedRegionId,
    hiddenSetIds: ui.hiddenSetIds.filter((id) => setIds.has(id)),
    hiddenRegionKeys: ui.hiddenRegionKeys.filter((key) => regionKeys.has(key)),
  };
}

export function restoreRegionUi(
  ui: Partial<RegionWorkspaceUi> | null | undefined,
  workspace: ProjectRegions,
): RegionWorkspaceUi {
  return sanitizeRegionUi({
    selectedSetId: ui?.selectedSetId ?? null,
    selectedRegionId: ui?.selectedRegionId ?? null,
    hiddenSetIds: ui?.hiddenSetIds ?? [],
    hiddenRegionKeys: ui?.hiddenRegionKeys ?? [],
  }, workspace);
}

export function nextRegionId(label: string, taken: Iterable<string>): string {
  const base = label
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "") || "region";
  const used = new Set(taken);
  if (!used.has(base)) return base;
  let suffix = 2;
  while (used.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

export function duplicateRegion(
  region: ProjectRegion,
  taken: Iterable<string>,
): ProjectRegion {
  return {
    ...region,
    id: nextRegionId(`${region.id}-copy`, taken),
    name: `${region.name ?? "Region"} copy`,
    meta: { ...region.meta },
    parts: region.parts.map((part) => ({
      ...part,
      shape: {
        ...part.shape,
        bounds: part.shape.bounds ? [...part.shape.bounds] : undefined,
        outline: part.shape.outline?.map((point) => [...point]),
        holes: part.shape.holes?.map((ring) => ring.map((point) => [...point])),
      },
    })) as ProjectRegion["parts"],
  };
}

export function duplicateRegionSet(
  source: ProjectRegionSet,
  workspace: ProjectRegions,
): ProjectRegionSet {
  const setId = nextRegionId(
    `${source.id}-copy`,
    workspace.sets.map((group) => group.id),
  );
  const taken = new Set(
    workspace.sets.flatMap((group) => group.regions.map((region) => region.id)),
  );
  const regions = source.regions.map((region) => {
    const copy = duplicateRegion(region, taken);
    taken.add(copy.id);
    return copy;
  });
  return {
    ...source,
    id: setId,
    name: `${source.name ?? "Region set"} copy`,
    meta: { ...source.meta },
    regions,
  };
}

export function regionSummary(region: ProjectRegion): string {
  const included = region.parts.filter((part) => part.mode === "include").length;
  const excluded = region.parts.length - included;
  const holes = region.parts.reduce(
    (sum, part) => sum + (part.shape.holes?.length ?? 0),
    0,
  );
  const pieces = [`${included} part${included === 1 ? "" : "s"}`];
  if (excluded) pieces.push(`${excluded} exclusion${excluded === 1 ? "" : "s"}`);
  if (holes) pieces.push(`${holes} hole${holes === 1 ? "" : "s"}`);
  return pieces.join(" · ");
}
