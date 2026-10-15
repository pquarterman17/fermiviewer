import type { ImageMeta } from "./api";
import { linearUnitToNm } from "./lengthUnits";

/** Parsers whose 2-D images represent scanning-probe channels. */
export const SPM_PARSERS = new Set([
  "nanoscope",
  "gwyddion",
  "asylum",
  "jpk",
  "wsxm",
  "nanosurf",
  "ntmdt",
  "nanonis",
]);

/** True when image metadata identifies an AFM/SPM source. */
export function isSpmImage(meta: ImageMeta | null | undefined): boolean {
  const parser = meta?.meta.parser;
  return typeof parser === "string" && SPM_PARSERS.has(parser);
}

/** True only for an SPM channel whose measured values are physical heights.
 * Other channels in the same container may be voltage, phase, force,
 * adhesion, or modulus and must not enter ISO 25178 height analysis. */
export function isSpmHeightImage(meta: ImageMeta | null | undefined): boolean {
  return isSpmImage(meta) && linearUnitToNm(meta?.value_unit ?? "") !== null;
}
