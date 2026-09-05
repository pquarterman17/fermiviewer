// One line of numbers for a region preview: what an analysis will read, in
// a form a user can check against what they drew before running it.

import type { RegionPreviewResponse } from "./api/regions";

const COUNT = new Intl.NumberFormat("en-US");

/** `0.123` → `"12.3 % of image"`; the whole image says so instead of "100 %". */
export function fractionLabel(fraction: number): string {
  if (fraction >= 1) return "whole image";
  const pct = fraction * 100;
  return `${pct >= 1 ? pct.toFixed(1) : pct.toPrecision(2)} % of image`;
}

/** Three significant figures, no trailing zeros: `1234.5` → `"1230"`,
 *  `0.04567` → `"0.0457"`. */
export function areaLabel(area: number, unit: string): string {
  return `${Number(area.toPrecision(3))} ${unit}²`;
}

export function formatRegionPreview(p: RegionPreviewResponse): string {
  const pieces = [`${COUNT.format(p.pixel_count)} px`, fractionLabel(p.fraction)];
  if (p.area_calibrated != null) pieces.push(areaLabel(p.area_calibrated, p.unit));
  // an exact mask reads narrower than its box: say so, with the box, because
  // a neighbourhood-based analysis reads the box for context (ADR 0007 §9)
  if (p.exact_mask) pieces.push(`exact mask in a ${COUNT.format(p.bbox_pixels)} px box`);
  return pieces.join(" · ");
}
