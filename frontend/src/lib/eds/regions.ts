// Pinned integration regions — the running list under the EDS spectrum.
//
// A region is a frozen snapshot of one `integrateWindow` result plus the
// element it was taken for and the spectrum it was measured on. It is a
// measurement record, not a live view: re-integrating later against a
// different spectrum would silently rewrite numbers the user already read.

import type { WindowIntegration } from "./integrate";

export interface IntegrationRegion extends WindowIntegration {
  id: string;
  /** Element symbol, or the energy window itself for an unnamed window. */
  label: string;
  /** The spectrum this was measured on ("Sum spectrum", "ROI […]", …). */
  source: string;
}

/** Identity of a region: same element, window and background model. Re-adding
 *  an identical region updates it in place instead of stacking duplicates. */
export function regionId(
  label: string,
  eLo: number,
  eHi: number,
  bg: string,
  source: string,
): string {
  return `${label}|${eLo.toFixed(4)}|${eHi.toFixed(4)}|${bg}|${source}`;
}

export function makeRegion(
  integration: WindowIntegration,
  element: string,
  source: string,
): IntegrationRegion {
  const label =
    element && element !== "(custom)"
      ? element
      : `${integration.eLo.toFixed(2)}–${integration.eHi.toFixed(2)}`;
  return {
    ...integration,
    label,
    source,
    id: regionId(label, integration.eLo, integration.eHi, integration.bg, source),
  };
}

/** Append a region, or replace the existing one with the same identity. */
export function upsertRegion(
  regions: IntegrationRegion[],
  region: IntegrationRegion,
): IntegrationRegion[] {
  const index = regions.findIndex((r) => r.id === region.id);
  if (index < 0) return [...regions, region];
  const next = [...regions];
  next[index] = region;
  return next;
}
