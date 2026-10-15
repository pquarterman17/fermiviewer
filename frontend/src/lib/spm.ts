import type { ImageMeta } from "./api";

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
