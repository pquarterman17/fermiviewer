// Seeding of the EELS background/signal fit windows from a spectrum's energy
// range. Extracted from EelsWorkshop so the workshop keeps shrinking.

function fmtNum(v: number): string {
  return Number(v.toPrecision(4)).toString();
}

export interface FitWindows {
  bgLo: string;
  bgHi: string;
  sigLo: string;
  sigHi: string;
}

/** Default background / signal windows as fractions of the energy span. */
export function seedFitWindows(energy: number[]): FitWindows {
  const e0 = energy[0];
  const span = energy[energy.length - 1] - e0;
  return {
    bgLo: fmtNum(e0 + 0.1 * span),
    bgHi: fmtNum(e0 + 0.3 * span),
    sigLo: fmtNum(e0 + 0.35 * span),
    sigHi: fmtNum(e0 + 0.6 * span),
  };
}
