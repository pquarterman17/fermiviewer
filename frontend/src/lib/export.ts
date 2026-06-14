// Shared "export the active image now" routine used by BOTH the Export
// dialog's Run button and the Export inspector card, so the two can't
// drift. Reads current display / overlay / scale-bar / tilt state from
// the store (matching lib/stageOps' store-singleton pattern) and triggers
// a browser download.

import { exportImage, type ExportOptions } from "./api";
import { DEFAULT_DISPLAY, useViewer } from "../store/viewer";

export interface ExportNowOpts {
  format: ExportOptions["format"];
  scale: number;
  /** include the scale bar when the image is calibrated (default true) */
  scaleBar?: boolean;
  /** bake measurement overlays when present (default true) */
  measures?: boolean;
  /** include a colorbar (default false) */
  colorbar?: boolean;
}

/** Export the active image with the current view settings and download it.
 *  Returns the filename; throws if there is no exportable active image. */
export async function exportActive(opts: ExportNowOpts): Promise<string> {
  const s = useViewer.getState();
  const id = s.activeId;
  if (!id) throw new Error("no active image");
  const meta = s.images[id];
  if (!meta || meta.kind === "spectrum") {
    throw new Error("image is not exportable");
  }

  const display = s.display[id] ?? DEFAULT_DISPLAY;
  const measures = s.measures[id] ?? [];
  const sb = s.scaleBars[id];
  const tilt = s.tilts[id] ?? null;

  const canBar = opts.format !== "tiff16" && meta.pixel_size !== null;
  const canMeasure = opts.format !== "tiff16" && measures.length > 0;
  const wantBar = (opts.scaleBar ?? true) && canBar;
  const wantMeasures = (opts.measures ?? true) && canMeasure;

  const include: string[] = [];
  if (wantBar) include.push("scale_bar");
  if (wantMeasures) include.push("measurements");
  if (opts.format !== "tiff16" && opts.colorbar) include.push("colorbar");

  const { blob, filename } = await exportImage(id, {
    format: opts.format,
    scale: opts.scale,
    lo: display.lo,
    hi: display.hi,
    gamma: display.gamma,
    // custom colormap is client-local — fall back to gray server-side
    cmap: display.cmap === "custom" ? "gray" : display.cmap,
    include,
    measures: wantMeasures
      ? measures.map((m) => ({
          kind: m.kind,
          pts: m.pts,
          text: m.text,
          endSymbol: m.endSymbol ?? s.overlay.endSymbol ?? "bar",
          width: m.width,
        }))
      : undefined,
    overlay_color: s.overlay.color,
    // #34: baked distance labels match the on-screen corrected values
    ...(tilt && tilt.angle !== 0
      ? {
          tilt_angle_deg: tilt.angle,
          tilt_axis: tilt.axis,
          tilt_geometry: tilt.geometry,
        }
      : {}),
    // honor on-screen scale-bar geometry + font size when overridden
    ...(wantBar && sb
      ? {
          scale_bar_norm_x: sb.x,
          scale_bar_norm_y: sb.y,
          scale_bar_length_phys: sb.lengthPhys,
          scale_bar_thickness: sb.thickness,
          scale_bar_font_size: sb.fontSize,
        }
      : {}),
  });

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  return filename;
}
