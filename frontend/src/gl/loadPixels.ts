// The one kind→endpoint branch for putting an image's pixels on the GPU
// (ADR 0003 §5): scalar kinds ride /data16 into the LUT shader, rgb_image
// rides /rgb8 into the colour branch. Every GLRenderer surface (Stage,
// CompareStage, SideBySideStage) loads through here so a new kind cannot
// land in one stage and not the others.

import {
  fetchData16,
  fetchRgb8,
  type DataKind,
  type Raster16,
} from "../lib/api";
import type { GLRenderer } from "./render";

export interface LoadedPixels {
  w: number;
  h: number;
  /** Scalar raster for probes/readouts — null for colour images, whose
   *  channels are colours, not measurements (the backend serves luma to
   *  the measure endpoints via the raster boundary). */
  raster: Raster16 | null;
}

/** `getGl` is resolved AFTER the fetch, matching the callers' historical
 *  semantics: the renderer may be created between effect and response
 *  (StrictMode re-mounts), or gone by then — null means "renderer gone,
 *  nothing uploaded" and callers simply drop the frame. */
export async function loadImagePixels(
  getGl: () => GLRenderer | null,
  id: string,
  kind: DataKind | undefined,
  frame?: number,
): Promise<LoadedPixels | null> {
  if (kind === "rgb_image") {
    const rgb = await fetchRgb8(id);
    const gl = getGl();
    if (!gl) return null;
    gl.setImageRgb8(rgb.data, rgb.w, rgb.h);
    return { w: rgb.w, h: rgb.h, raster: null };
  }
  const r = await fetchData16(id, frame);
  const gl = getGl();
  if (!gl) return null;
  gl.setImage16(r.data, r.w, r.h);
  return { w: r.w, h: r.h, raster: r };
}
