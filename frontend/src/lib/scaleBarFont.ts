// One place for the scale-bar label font bounds. The export backend caps
// scale_bar_font_size at 200 px, so anything that can reach it (per-image
// override, Preferences default) is held to this range first.

export const SCALE_BAR_FONT_MIN = 8;
export const SCALE_BAR_FONT_MAX = 120;

/** Whole px within [MIN, MAX]; null/undefined/non-finite → null (auto). */
export function clampScaleBarFont(v: number | null | undefined): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  return Math.min(SCALE_BAR_FONT_MAX, Math.max(SCALE_BAR_FONT_MIN, Math.round(v)));
}
