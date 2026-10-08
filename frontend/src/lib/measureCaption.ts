// "Edit caption…" on a VALUE measure (distance, profile, polyline, angle,
// ROI, ellipse, polygon, lasso) used to be stored on Measure.text but
// never shown — only the annotation kinds (text/arrow/box/circle), whose
// label IS the caption, rendered it. The caption now leads the measured
// value everywhere it is shown: the stage label, the Measurements list and
// the export (calc/export.py _captioned mirrors this format).

import type { Measure } from "../store/viewer";

/** `value` prefixed with the measure's caption ("caption · value"), or the
 *  bare value when there is no caption. */
export function withCaption(m: Pick<Measure, "text">, value: string): string {
  const caption = m.text?.trim();
  if (!caption) return value;
  return value ? `${caption} · ${value}` : caption;
}
