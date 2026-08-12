// Save the on-screen composite overlay to the library (SPECTRAL plan #10,
// ADR 0003). The pixels come off the SAME canvas the user is looking at —
// the figure-export philosophy (lib/elemental/figureExport.ts) applied to
// registration: one blend implementation, composed client-side, stored
// verbatim. Both Maps tabs (EDS and EELS) call this one helper.

import { registerComposite, type ImageMeta } from "../api";

export interface SaveCompositeArgs {
  /** The live overlay canvas (MapOverlay's canvasRef) — null → nothing saved. */
  canvas: HTMLCanvasElement | null;
  /** The cube the maps came from; its spatial calibration is inherited. */
  parentId: string;
  name: string;
  /** Provenance for captions: species, colours, blend, legend selection. */
  recipe?: Record<string, unknown>;
}

/** Returns the registered ImageMeta, or null when there is nothing to save
 *  (no canvas yet). Callers ingest the meta into the viewer store so the
 *  composite appears in the filmstrip immediately. */
export async function saveCompositeToLibrary(
  args: SaveCompositeArgs,
): Promise<ImageMeta | null> {
  const { canvas } = args;
  if (!canvas || canvas.width === 0 || canvas.height === 0) return null;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  const n = canvas.width * canvas.height;
  const rgb = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) {
    rgb[i * 3] = rgba[i * 4];
    rgb[i * 3 + 1] = rgba[i * 4 + 1];
    rgb[i * 3 + 2] = rgba[i * 4 + 2];
  }
  return registerComposite({
    parentId: args.parentId,
    name: args.name,
    width: canvas.width,
    height: canvas.height,
    pixels: rgb,
    recipe: args.recipe ?? {},
  });
}

/** "Composite — Fe, Cu, O (cube name)" — the library row's display name. */
export function compositeName(
  symbols: string[],
  parentName: string | undefined,
): string {
  const list = symbols.length ? symbols.join(", ") : "empty";
  return parentName
    ? `Composite — ${list} (${parentName})`
    : `Composite — ${list}`;
}
