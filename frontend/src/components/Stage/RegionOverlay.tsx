// Non-interactive preview of the canonical ADR 0006 analysis regions.
// Geometry stays in 0-based [row, col] image coordinates until this layer;
// unlike measurement annotations, nothing is normalized or approximated.

import { useId } from "react";

import { imageToScreen, type Size } from "../../lib/geometry";
import type {
  ProjectRegion,
  ProjectRegionClass,
  ProjectRegionSet,
  RegionShape,
} from "../../lib/api";
import { regionVisibilityKey } from "../../lib/regionWorkspace";
import { useViewer, type View } from "../../store/viewer";

interface PreviewRegion {
  set: ProjectRegionSet;
  region: ProjectRegion;
  color: string;
  selected: boolean;
}

export function visibleRegionPreviews(
  imageId: string,
  sets: ProjectRegionSet[],
  classes: ProjectRegionClass[],
  hiddenSetIds: string[],
  hiddenRegionKeys: string[],
  selectedSetId: string | null,
  selectedRegionId: string | null,
): PreviewRegion[] {
  const colors = new Map(classes.map((entry) => [entry.id, entry.color]));
  return sets
    .filter((group) => group.image_id === imageId && !hiddenSetIds.includes(group.id))
    .flatMap((group) => group.regions
      .filter((region) => !hiddenRegionKeys.includes(regionVisibilityKey(group.id, region.id)))
      .map((region) => ({
        set: group,
        region,
        color: colors.get(region.region_class ?? "") ?? "#8b5cf6",
        selected: group.id === selectedSetId && region.id === selectedRegionId,
      })));
}

function polygonPath(
  rings: [number, number][][],
  toScreen: (point: [number, number]) => { x: number; y: number },
): string {
  return rings.map((ring) => ring.map((point, index) => {
    const p = toScreen(point);
    return `${index === 0 ? "M" : "L"}${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
  }).join(" ") + " Z").join(" ");
}

/** Exact vector boundary for one canonical shape in viewport coordinates. */
export function regionShapePath(
  shape: RegionShape,
  view: View,
  img: Size,
  vp: Size,
): string {
  const toScreen = ([row, col]: [number, number]) =>
    imageToScreen(col, row, view, img, vp);
  if (shape.kind === "polygon") {
    return polygonPath([shape.outline, ...(shape.holes ?? [])], toScreen);
  }

  const [r0, c0, r1, c1] = shape.bounds;
  // Rect/ellipse bounds name inclusive pixel centres, so their footprint
  // extends half a pixel beyond each endpoint. Circle bounds are the true
  // disc boundary and must not receive that expansion (calc.regions).
  const halfPixel = shape.kind === "circle" ? 0 : 0.5;
  const a = imageToScreen(c0 - halfPixel, r0 - halfPixel, view, img, vp);
  const b = imageToScreen(c1 + halfPixel, r1 + halfPixel, view, img, vp);
  const x0 = Math.min(a.x, b.x);
  const x1 = Math.max(a.x, b.x);
  const y0 = Math.min(a.y, b.y);
  const y1 = Math.max(a.y, b.y);
  let outer: string;
  if (shape.kind === "rect") {
    outer = `M${x0.toFixed(2)} ${y0.toFixed(2)} H${x1.toFixed(2)} V${y1.toFixed(2)} H${x0.toFixed(2)} Z`;
  } else {
    const rx = (x1 - x0) / 2;
    const ry = (y1 - y0) / 2;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    outer = `M${(cx - rx).toFixed(2)} ${cy.toFixed(2)} A${rx.toFixed(2)} ${ry.toFixed(2)} 0 1 0 ${(cx + rx).toFixed(2)} ${cy.toFixed(2)} A${rx.toFixed(2)} ${ry.toFixed(2)} 0 1 0 ${(cx - rx).toFixed(2)} ${cy.toFixed(2)} Z`;
  }
  return [outer, polygonPath(shape.holes ?? [], toScreen)].filter(Boolean).join(" ");
}

export default function RegionOverlay({
  imageId,
  view,
  img,
  vp,
}: {
  imageId: string;
  view: View;
  img: Size;
  vp: Size;
}) {
  const regions = useViewer((state) => state.regions);
  const ui = useViewer((state) => state.regionUi);
  const patternPrefix = useId().replaceAll(":", "");
  const previews = visibleRegionPreviews(
    imageId,
    regions.sets,
    regions.classes,
    ui.hiddenSetIds,
    ui.hiddenRegionKeys,
    ui.selectedSetId,
    ui.selectedRegionId,
  );
  if (previews.length === 0) return null;

  return (
    <svg
      className="fvd-measure-layer fvd-region-overlay"
      width={vp.w}
      height={vp.h}
      pointerEvents="none"
      aria-label="Analysis region preview"
    >
      <defs>
        {previews.map(({ set, region, color }, index) => (
          <pattern key={`${set.id}-${region.id}`} id={`${patternPrefix}-${index}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="7" stroke={color} strokeWidth="2" opacity="0.45" />
          </pattern>
        ))}
      </defs>
      {previews.map(({ set, region, color, selected }, previewIndex) => (
        <g key={`${set.id}-${region.id}`} data-region-id={region.id}>
          {region.parts.map((part, index) => (
            <path
              key={index}
              d={regionShapePath(part.shape, view, img, vp)}
              fill={part.mode === "include" ? color : `url(#${patternPrefix}-${previewIndex})`}
              fillOpacity={part.mode === "include" ? (selected ? 0.22 : 0.12) : 1}
              fillRule="evenodd"
              stroke={color}
              strokeWidth={selected ? 2.5 : 1.5}
              strokeDasharray={part.mode === "exclude" ? "5 4" : undefined}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </g>
      ))}
    </svg>
  );
}
