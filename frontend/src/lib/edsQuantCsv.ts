// CSV serialiser for EDS model-fit quantification results (#11).
// Operates on the EdsPeakfitResult / EdsZetaResult shapes returned by
// /api/eds/peakfit and /api/eds/zeta. Pure string builder — no DOM, no
// store — so it is trivially unit-testable (downloadCsv from
// eelsQuantCsv.ts does the browser part).
//
// Columns: element, line, energy_kev, net_area, net_area_error,
// atomic_percent, atomic_percent_error, weight_percent, weight_percent_error.
// A commented provenance header records image, method, χ²ᵣ and — for the
// ζ-factor method — mass-thickness/thickness/dose. Artifact markers (#8)
// append as commented rows so the correction trail survives in the export.

import type {
  EdsPeakfitResult,
  EdsZetaQuant,
  EdsZetaResult,
} from "./api";

function num(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "";
  return String(Number(v.toPrecision(7)));
}

export interface EdsQuantCsvContext {
  imageName: string;
}

function isZetaQuant(
  q: EdsPeakfitResult["quant"] | EdsZetaQuant,
): q is EdsZetaQuant {
  return q != null && "mass_thickness_kg_m2" in q;
}

/**
 * Serialise an EDS model-fit result (Cliff-Lorimer or ζ-factor quant)
 * to CSV. Works with or without the quant block; ζ results also emit
 * mass-thickness (kg/m² and µg/cm²), thickness (when a density was
 * given) and the electron dose in the provenance header.
 */
export function edsModelFitToCsv(
  r: EdsPeakfitResult | EdsZetaResult,
  ctx: EdsQuantCsvContext,
): string {
  const quant = r.quant;
  const zeta = isZetaQuant(quant) ? quant : null;
  const lines: string[] = [
    "# fermiviewer EDS model-fit export",
    `# image: ${ctx.imageName}`,
    `# method: ${zeta ? "zeta-factor" : "cliff-lorimer"}`,
    `# reduced_chi2: ${num(r.reduced_chi2)}`,
  ];
  if (zeta) {
    lines.push(
      `# mass_thickness_kg_m2: ${num(zeta.mass_thickness_kg_m2)} ± ${num(zeta.mass_thickness_error_kg_m2)}`,
      `# mass_thickness_ug_cm2: ${num(zeta.mass_thickness_ug_cm2)}`,
      `# thickness_nm: ${zeta.thickness_nm == null ? "" : num(zeta.thickness_nm)}`,
      `# dose_electrons: ${num(zeta.dose_electrons)}`,
    );
  }
  lines.push(
    "element,line,energy_kev,net_area,net_area_error," +
      "atomic_percent,atomic_percent_error,weight_percent,weight_percent_error",
  );

  const qi = (sym: string) => quant?.elements.indexOf(sym) ?? -1;
  for (const el of r.elements) {
    const i = qi(el.symbol);
    lines.push(
      [
        el.symbol,
        el.line,
        num(el.energy_kev),
        num(el.net_area),
        num(el.net_area_error),
        num(i >= 0 ? quant?.atomic_percent[i] : null),
        num(i >= 0 ? quant?.atomic_percent_error?.[i] : null),
        num(i >= 0 ? quant?.weight_percent[i] : null),
        num(i >= 0 ? quant?.weight_percent_error?.[i] : null),
      ].join(","),
    );
  }

  if (r.artifacts && r.artifacts.length > 0) {
    lines.push("# artifact,kind,energy_kev,status,area,area_error");
    for (const a of r.artifacts) {
      lines.push(
        `# ${a.label},${a.kind},${num(a.energy_kev)},${a.status},${num(a.area)},${num(a.area_error)}`,
      );
    }
  }
  return lines.join("\n") + "\n";
}
