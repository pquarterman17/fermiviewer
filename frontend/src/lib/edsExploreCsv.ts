// Pure CSV serializers for the EDS Spectrum-Image explorer's exports.
// Kept out of the component so the formatting is unit-testable and the
// explorer stays under the 500-line module ceiling.
import type { EdsElementMapResult, Spectrum } from "./api";

/** Element-window map → CSV: a comment header (window + background mode)
 *  followed by the H×W counts grid, one map row per line. */
export function elementMapCsv(m: EdsElementMapResult): string {
  const header =
    `# EDS element map ${m.e_lo.toFixed(3)}-${m.e_hi.toFixed(3)} keV ` +
    `(${m.bg} bg)\n`;
  const rows = m.map
    .map((row) => row.map((v) => v.toFixed(4)).join(","))
    .join("\n");
  return header + rows;
}

/** Displayed spectrum → CSV: `energy_<units>,counts` header then one
 *  energy/counts pair per line. */
export function spectrumCsv(s: Spectrum): string {
  const header = `energy_${s.units},counts\n`;
  const rows = s.energy
    .map((e, i) => `${e.toFixed(6)},${s.counts[i].toFixed(6)}`)
    .join("\n");
  return header + rows;
}
