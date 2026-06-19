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
  /** report caption burned into a band below the figure (WS4c). Already
   *  composed (user text + optional metadata line); empty/undefined → none */
  caption?: string;
}

/** Build the /export request (id + options) from current store state.
 *  Shared by exportActive (download) and copyActive (clipboard) so the
 *  two can never drift on which overlays get baked into the picture. */
function buildExportRequest(
  opts: ExportNowOpts,
): { id: string; options: ExportOptions } {
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

  const caption = opts.caption?.trim();
  const wantCaption = opts.format !== "tiff16" && !!caption;

  const include: string[] = [];
  if (wantBar) include.push("scale_bar");
  if (wantMeasures) include.push("measurements");
  if (opts.format !== "tiff16" && opts.colorbar) include.push("colorbar");
  if (wantCaption) include.push("caption");

  const options: ExportOptions = {
    format: opts.format,
    scale: opts.scale,
    lo: display.lo,
    hi: display.hi,
    gamma: display.gamma,
    // custom colormap is client-local — fall back to gray server-side
    cmap: display.cmap === "custom" ? "gray" : display.cmap,
    include,
    caption: wantCaption ? caption : undefined,
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
    // honor on-screen scale-bar geometry, font, colour + unit override
    ...(wantBar && sb
      ? {
          scale_bar_norm_x: sb.x,
          scale_bar_norm_y: sb.y,
          scale_bar_length_phys: sb.lengthPhys,
          scale_bar_thickness: sb.thickness,
          scale_bar_font_size: sb.fontSize,
          scale_bar_color: sb.color ?? null,          // audit #10
          scale_bar_unit_override: sb.unitOverride ?? null, // audit #10
        }
      : {}),
  };
  return { id, options };
}

/** Export the active image with the current view settings and download it.
 *  Returns the filename; throws if there is no exportable active image. */
export async function exportActive(opts: ExportNowOpts): Promise<string> {
  const { id, options } = buildExportRequest(opts);
  const { blob, filename } = await exportImage(id, options);

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  return filename;
}

/** Render the active image with the given options and return the PNG blob
 *  WITHOUT downloading — drives the Export dialog's live preview. Gating
 *  (which overlays are allowed) still uses the chosen format, so a tiff16
 *  selection previews bare like its real export; the request is then forced
 *  to png at scale 1 so any format previews fast in an <img>. */
export async function previewActive(opts: ExportNowOpts): Promise<Blob> {
  const { id, options } = buildExportRequest({ ...opts, scale: 1 });
  const { blob } = await exportImage(id, { ...options, format: "png" });
  return blob;
}

/** Copy the active image to the clipboard as a PNG. Bakes in the scale
 *  bar + measurements by default (same overlay logic as exportActive) —
 *  pass scaleBar/measures: false to copy a bare image. Used by the radial
 *  right-click "Copy" item and the menu-bar "Copy to Clipboard". */
export async function copyActive(
  opts: ExportNowOpts = { format: "png", scale: 1 },
): Promise<void> {
  const { id, options } = buildExportRequest(opts);
  const { blob } = await exportImage(id, options);
  await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
}
