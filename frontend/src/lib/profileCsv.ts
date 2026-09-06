// CSV serialisers for intensity profiles — line scans (DockPlot) and
// box integration (MeasurePanel). Each file opens with a commented `#`
// provenance header (image, calibration, geometry, reduce) followed by
// clean numeric columns, so an exported profile is self-documenting and
// re-importable. Pure string builders — no DOM, no store — so they're
// trivially unit-testable; downloadCsv() handles the browser side.

import type { BoxProfileResult, ProfileResult } from "./api";
import { calibratedSpacing, type PixelSpacing } from "./geometry";

/** Compact numeric formatting: trims float noise, blanks non-finite. */
function num(v: number): string {
  if (!Number.isFinite(v)) return "";
  // 7 sig-figs is plenty for intensities/positions and avoids 1.0000000002
  return String(Number(v.toPrecision(7)));
}

function cell(v: number | null): string {
  return v == null || !Number.isFinite(v) ? "" : num(v);
}

/** `[row, column]` extents when the image is anisotropic, else null — the
 *  square-pixel CSV paths below are untouched (ADR 0008). */
function anisotropic(
  spacing: PixelSpacing | null | undefined,
): [number, number] | null {
  const sp = calibratedSpacing(null, spacing);
  return sp && sp[0] !== sp[1] ? sp : null;
}

function spacingHeader(sp: [number, number], u: string): string {
  return `# pixel_spacing: rows ${num(sp[0])} ${u}/px, columns ${num(sp[1])} ${u}/px`;
}

/** Maps each calibrated position along a line/polyline back to its
 *  pixel-path position, piecewise per segment, when the pixels are not
 *  square: a segment's physical length is `hypot(dx·col, dy·row)` while
 *  its pixel length is `hypot(dx, dy)`, so the two differ by a factor
 *  that depends on the segment's direction and dividing by one scalar
 *  cannot recover it. Returns null when the geometry is unknown. */
function pixelPositions(
  dist: number[],
  pts: { x: number; y: number }[] | undefined,
  sp: [number, number],
): number[] | null {
  if (!pts || pts.length < 2) return null;
  const cumPx = [0];
  const cumPhys = [0];
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].x - pts[i - 1].x;
    const dy = pts[i].y - pts[i - 1].y;
    cumPx.push(cumPx[i - 1] + Math.hypot(dx, dy));
    cumPhys.push(cumPhys[i - 1] + Math.hypot(dx * sp[1], dy * sp[0]));
  }
  const total = cumPhys[cumPhys.length - 1];
  if (!(total > 0)) return null;
  let k = 1;
  return dist.map((d) => {
    while (k < cumPhys.length - 1 && d > cumPhys[k]) k++;
    const segPhys = cumPhys[k] - cumPhys[k - 1];
    const f = segPhys > 0 ? (d - cumPhys[k - 1]) / segPhys : 0;
    return cumPx[k - 1] + f * (cumPx[k] - cumPx[k - 1]);
  });
}

export interface ProfileCsvContext {
  imageName: string;
  /** unit per px; null/NaN → uncalibrated (x in px only) */
  pixelSize: number | null;
  /** `ImageMeta.pixel_spacing` `[row, column]`; when anisotropic the
   *  position_px column is recovered per segment from `endpointsPx` */
  pixelSpacing?: PixelSpacing | null;
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
  const aniso = cal ? anisotropic(ctx.pixelSpacing) : null;
  if (aniso) lines.push(spacingHeader(aniso, u));
  lines.push(`# length: ${num(p.length)} ${p.unit}`);

  if (cal) {
    const ps = ctx.pixelSize as number;
    const pxPos = aniso ? pixelPositions(p.dist, ctx.endpointsPx, aniso) : null;
    if (aniso && !pxPos) {
      // no usable geometry: a per-segment mapping is impossible and a
      // column-scale quotient would be wrong, so the px column is dropped
      lines.push(`position_${u},${iLabel}`);
      for (let i = 0; i < p.dist.length; i++) {
        lines.push(`${num(p.dist[i])},${cell(p.intensity[i])}`);
      }
      return lines.join("\n") + "\n";
    }
    lines.push(`position_px,position_${u},${iLabel}`);
    for (let i = 0; i < p.dist.length; i++) {
      const px = pxPos ? pxPos[i] : p.dist[i] / ps;
      lines.push(`${num(px)},${num(p.dist[i])},${cell(p.intensity[i])}`);
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
  /** `ImageMeta.pixel_spacing` `[row, column]`: the y (rows) axis is
   *  calibrated with the ROW extent, x (columns) with the column extent
   *  (`pixel_size`). Absent → square pixels, as before. */
  pixelSpacing?: PixelSpacing | null;
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
  ];
  const aniso = cal ? anisotropic(ctx.pixelSpacing) : null;
  if (aniso) lines.push(spacingHeader(aniso, u));
  lines.push(
    "# x = profile along columns (horizontal); y = profile along rows (vertical)",
  );

  const n = Math.max(b.x_pos.length, b.y_pos.length);
  if (cal) {
    const ps = b.pixel_size as number;
    const [sRow, sCol] = aniso ?? [ps, ps];
    lines.push(`x_px,x_${u},x_${iL},y_px,y_${u},y_${iL}`);
    for (let i = 0; i < n; i++) {
      const x =
        i < b.x_pos.length
          ? `${num(b.x_pos[i])},${num(b.x_pos[i] * sCol)},${cell(b.x_intensity[i])}`
          : ",,";
      const y =
        i < b.y_pos.length
          ? `${num(b.y_pos[i])},${num(b.y_pos[i] * sRow)},${cell(b.y_intensity[i])}`
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
