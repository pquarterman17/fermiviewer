// CSV serialisers for intensity profiles — line scans (DockPlot) and
// box integration (MeasurePanel). Each file opens with a commented `#`
// provenance header (image, calibration, geometry, reduce) followed by
// clean numeric columns, so an exported profile is self-documenting and
// re-importable. Pure string builders — no DOM, no store — so they're
// trivially unit-testable; downloadCsv() handles the browser side.

import type { BoxProfileResult, ProfileResult } from "./api";

/** Compact numeric formatting: trims float noise, blanks non-finite. */
function num(v: number): string {
  if (!Number.isFinite(v)) return "";
  // 7 sig-figs is plenty for intensities/positions and avoids 1.0000000002
  return String(Number(v.toPrecision(7)));
}

function cell(v: number | null): string {
  return v == null || !Number.isFinite(v) ? "" : num(v);
}

export interface ProfileCsvContext {
  imageName: string;
  /** unit per px; null/NaN → uncalibrated (x in px only) */
  pixelSize: number | null;
  pixelUnit: string;
  /** measure kind for the header note ("profile" | "polyline" | …) */
  kind: string;
  /** ⊥ integration width in px (box-profile captures) */
  width?: number;
  /** absolute image-px endpoints, for the header note */
  endpointsPx?: { x: number; y: number }[];
}

/** Serialise a line/polyline/box-profile result to CSV. When calibrated
 *  the table carries both a pixel position and the calibrated position. */
export function profileToCsv(p: ProfileResult, ctx: ProfileCsvContext): string {
  const cal = ctx.pixelSize != null && Number.isFinite(ctx.pixelSize);
  const u = ctx.pixelUnit;
  const iLabel = p.reduce === "sum" ? "intensity_sum" : "intensity";
  const lines: string[] = [
    "# fermiviewer profile export",
    `# image: ${ctx.imageName}`,
    `# kind: ${ctx.kind}${ctx.width && ctx.width > 1 ? " (box-integrated)" : ""}`,
    `# reduce: ${p.reduce}`,
  ];
  if (ctx.width && ctx.width > 1) {
    lines.push(`# integration_width_px: ${ctx.width}`);
  }
  if (ctx.endpointsPx && ctx.endpointsPx.length >= 2) {
    const fmt = (q: { x: number; y: number }) =>
      `(${num(q.x)},${num(q.y)})`;
    lines.push(`# endpoints_px: ${ctx.endpointsPx.map(fmt).join(" -> ")}`);
  }
  lines.push(
    cal
      ? `# pixel_size: ${num(ctx.pixelSize as number)} ${u}/px`
      : "# pixel_size: uncalibrated",
  );
  lines.push(`# length: ${num(p.length)} ${p.unit}`);

  if (cal) {
    const ps = ctx.pixelSize as number;
    lines.push(`position_px,position_${u},${iLabel}`);
    for (let i = 0; i < p.dist.length; i++) {
      lines.push(`${num(p.dist[i] / ps)},${num(p.dist[i])},${cell(p.intensity[i])}`);
    }
  } else {
    lines.push(`position_px,${iLabel}`);
    for (let i = 0; i < p.dist.length; i++) {
      lines.push(`${num(p.dist[i])},${cell(p.intensity[i])}`);
    }
  }
  return lines.join("\n") + "\n";
}

export interface BoxCsvContext {
  imageName: string;
  pixelUnit: string;
  /** measure kind for the header note (e.g. "roi") */
  kind: string;
}

/** Serialise a both-axes box integration to one CSV. The x (horizontal,
 *  over columns) and y (vertical, over rows) profiles sit side by side;
 *  when the axes differ in length the shorter one is blank-padded. */
export function boxProfileToCsv(b: BoxProfileResult, ctx: BoxCsvContext): string {
  const cal = b.pixel_size != null && Number.isFinite(b.pixel_size);
  const u = ctx.pixelUnit;
  const iL = b.reduce === "sum" ? "intensity_sum" : "intensity";
  const [r1, c1, r2, c2] = b.rect;
  const lines: string[] = [
    "# fermiviewer box-integration profile export",
    `# image: ${ctx.imageName}`,
    `# kind: ${ctx.kind} (box integration, both axes)`,
    `# reduce: ${b.reduce}`,
    `# box_px: rows ${r1}-${r2}, cols ${c1}-${c2}`,
    cal
      ? `# pixel_size: ${num(b.pixel_size as number)} ${u}/px`
      : "# pixel_size: uncalibrated",
    "# x = profile along columns (horizontal); y = profile along rows (vertical)",
  ];

  const n = Math.max(b.x_pos.length, b.y_pos.length);
  if (cal) {
    const ps = b.pixel_size as number;
    lines.push(`x_px,x_${u},x_${iL},y_px,y_${u},y_${iL}`);
    for (let i = 0; i < n; i++) {
      const x =
        i < b.x_pos.length
          ? `${num(b.x_pos[i])},${num(b.x_pos[i] * ps)},${cell(b.x_intensity[i])}`
          : ",,";
      const y =
        i < b.y_pos.length
          ? `${num(b.y_pos[i])},${num(b.y_pos[i] * ps)},${cell(b.y_intensity[i])}`
          : ",,";
      lines.push(`${x},${y}`);
    }
  } else {
    lines.push(`x_px,x_${iL},y_px,y_${iL}`);
    for (let i = 0; i < n; i++) {
      const x =
        i < b.x_pos.length ? `${num(b.x_pos[i])},${cell(b.x_intensity[i])}` : ",";
      const y =
        i < b.y_pos.length ? `${num(b.y_pos[i])},${cell(b.y_intensity[i])}` : ",";
      lines.push(`${x},${y}`);
    }
  }
  return lines.join("\n") + "\n";
}

/** Strip the extension off a filename for a CSV basename. */
export function csvBaseName(name: string | undefined): string {
  if (!name) return "image";
  return name.replace(/\.[^./\\]+$/, "") || name;
}

/** Trigger a browser download of CSV text (same pattern as exportActive). */
export function downloadCsv(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
