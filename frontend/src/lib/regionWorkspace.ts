import type {
  ProjectRegion,
  ProjectRegionSet,
  ProjectRegions,
  RegionWorkspaceUi,
} from "./api";

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
