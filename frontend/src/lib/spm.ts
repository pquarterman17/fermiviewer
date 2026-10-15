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

// Keep aligned with io/spm_common.py's primary-channel vocabulary. A length
// unit alone is insufficient: deformation/indentation channels are also nm.
const TOPOGRAPHY_CHANNELS = [
  "height", "topography", "z-axis", "zsensor", "z sensor", "z-sensor", "z",
];

/** True when image metadata identifies an AFM/SPM source. */
export function isSpmImage(meta: ImageMeta | null | undefined): boolean {
  const parser = meta?.meta.parser;
  return typeof parser === "string" && SPM_PARSERS.has(parser);
}

/** True only for an SPM channel whose measured values are physical heights.
 * Other channels in the same container may be voltage, phase, force,
 * adhesion, or modulus and must not enter ISO 25178 height analysis. */
export function isSpmHeightImage(meta: ImageMeta | null | undefined): boolean {
  if (!isSpmImage(meta) || linearUnitToNm(meta?.value_unit ?? "") === null) return false;
  const raw = meta?.meta.channel ?? meta?.meta.channel_label;
  if (typeof raw !== "string") return false;
  const channel = raw.trim().toLowerCase();
  return TOPOGRAPHY_CHANNELS.some(
    (name) => channel === name || (name.length > 1 && channel.startsWith(name)),
  );
}
