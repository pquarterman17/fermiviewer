// Per-sample result-vs-parameter roll-up — the W4 item 24 deliverable: for
// each sample group, combine its member images' measured region areas
// against ONE named parameter (item 23's per-sample editor), producing
// mean/std/n so a collaborator gets "area vs anneal temperature, with error
// bars" as a table, a plot, and a CSV. This module is the artifact's
// arithmetic; components/workshops/ProjectComparePanel.tsx only wires
// selectors and the export button around it.
//
// Pure module — no React, no zustand. Consumes:
//   - lib/regionTable.ts's regionRows/regionPhysicalAreas (item 15) for the
//     per-image area numbers, so recalibrating an image changes this
//     roll-up with no migration step, exactly like the Regions card — areas
//     are never re-derived here.
//   - lib/measureStats.ts's meanSd for the mean/population-std arithmetic,
//     so the two share one pinned convention instead of two hand-rolled
//     copies that could drift apart.
//   - lib/groups.ts's ImageGroup/GroupParam — a sample IS an ImageGroup; a
//     "sample" here is any group with member images (`ids.length > 0`). A
//     purely organisational group (a project holding only sub-samples, no
//     images of its own) contributes nothing and is silently skipped — it
//     is not a sample, so it has nothing to be excluded FROM.
//
// The one documented numeric-with-unit convention (lib/groups.ts
// GroupParam, item 23): `value` is a finite number for anything plotted on
// the x-axis; string/boolean values are categorical and are reported in
// `excluded` here rather than coerced to a number.

import type { GroupParam, ImageGroup } from "./groups";
import { meanSd } from "./measureStats";
import {
  regionPhysicalAreas,
  regionRows,
  unitToken,
  type RegionCandidate,
  type RegionTableImage,
} from "./regionTable";

/** One sample's aggregated result, ready to plot/tabulate/export. */
export interface SampleCompareRow {
  groupId: string;
  sampleName: string;
  /** The chosen parameter's numeric value — the x-axis / independent variable. */
  paramValue: number;
  /** The chosen parameter's unit as recorded on this sample (null = none). */
  paramUnit: string | null;
  /** Physical unit of this row's aggregated result — equal to
   *  ProjectCompareResult.resultUnit for every row that made it into `rows`. */
  resultUnit: string;
  mean: number;
  std: number;
  n: number;
}

/** A sample group that could not be included, and why — so a collaborator
 *  sees "N samples excluded: ..." instead of a table that silently shrank. */
export interface SampleExclusion {
  groupId: string;
  sampleName: string;
  reason: string;
}

export interface ProjectCompareResult {
  /** Included samples, ordered ascending by paramValue so a plot reads as a
   *  trend, not group-creation order. */
  rows: SampleCompareRow[];
  excluded: SampleExclusion[];
  /** The parameter name every row was aggregated against. */
  paramName: string;
  /** Physical unit shared by every row's result, derived from the first
   *  included sample's calibrated images — never hardcoded, never guessed
   *  (mirrors regionTable.ts's areaPhysicalColumn). Null when `rows` is
   *  empty (nothing produced a usable number). */
  resultUnit: string | null;
}

interface SampleAggregate {
  values: number[];
  units: Set<string>;
  anyRegionsDrawn: boolean;
}

function aggregateSample(
  group: ImageGroup,
  imagesById: Record<string, RegionTableImage | undefined>,
  measuresByImage: Record<string, RegionCandidate[] | undefined>,
): SampleAggregate {
  const values: number[] = [];
  const units = new Set<string>();
  let anyRegionsDrawn = false;
  for (const imgId of group.ids) {
    const image = imagesById[imgId];
    if (!image) continue;
    const measures = measuresByImage[imgId] ?? [];
    if (regionRows(measures, image).length > 0) anyRegionsDrawn = true;
    const areas = regionPhysicalAreas(measures, image);
    if (areas.length > 0) {
      units.add(image.pixel_unit);
      values.push(...areas);
    }
  }
  return { values, units, anyRegionsDrawn };
}

/**
 * Aggregate a chosen result (region areas, item 15) against a chosen named
 * parameter (item 23) for every sample group with member images.
 *
 * Every sample lands in `rows` or `excluded` with a stated reason — never
 * silently dropped:
 *   - no `paramName` parameter set on the sample
 *   - the parameter's value is not a finite number (categorical — reported,
 *     not coerced)
 *   - no regions drawn on any of its images
 *   - regions drawn but none of its images are calibrated
 *   - its own images mix more than one physical unit (can't average nm and um)
 *   - its unit doesn't match the table's shared unit, decided by the first
 *     included sample (cross-sample unit mismatch)
 *
 * `rows` is sorted ascending by paramValue.
 */
export function compareSamplesByParam(
  groups: ImageGroup[],
  imagesById: Record<string, RegionTableImage | undefined>,
  measuresByImage: Record<string, RegionCandidate[] | undefined>,
  paramName: string,
): ProjectCompareResult {
  const rows: SampleCompareRow[] = [];
  const excluded: SampleExclusion[] = [];
  let resultUnit: string | null = null;

  for (const group of groups) {
    if (!group.ids || group.ids.length === 0) continue; // not a sample

    const param: GroupParam | undefined = group.params?.[paramName];
    if (!param) {
      excluded.push({
        groupId: group.id,
        sampleName: group.name,
        reason: `no "${paramName}" parameter set`,
      });
      continue;
    }
    if (typeof param.value !== "number" || !Number.isFinite(param.value)) {
      excluded.push({
        groupId: group.id,
        sampleName: group.name,
        reason:
          `"${paramName}" is categorical (${JSON.stringify(param.value)}), ` +
          "not numeric — excluded from the plot rather than coerced",
      });
      continue;
    }

    const agg = aggregateSample(group, imagesById, measuresByImage);
    if (agg.values.length === 0) {
      excluded.push({
        groupId: group.id,
        sampleName: group.name,
        reason: agg.anyRegionsDrawn
          ? "regions drawn but none of its images are calibrated"
          : "no regions drawn on any of its images",
      });
      continue;
    }
    if (agg.units.size > 1) {
      excluded.push({
        groupId: group.id,
        sampleName: group.name,
        reason:
          `its images mix physical units (${[...agg.units].sort().join(", ")}) ` +
          "— cannot average",
      });
      continue;
    }
    const [sampleUnit] = agg.units;
    if (resultUnit == null) {
      resultUnit = sampleUnit;
    } else if (sampleUnit !== resultUnit) {
      excluded.push({
        groupId: group.id,
        sampleName: group.name,
        reason:
          `calibrated in "${sampleUnit}", other samples in "${resultUnit}" ` +
          "— cannot combine in one table",
      });
      continue;
    }

    const { mean, std, n } = meanSd(agg.values);
    rows.push({
      groupId: group.id,
      sampleName: group.name,
      paramValue: param.value,
      paramUnit: param.unit ?? null,
      resultUnit: sampleUnit,
      mean,
      std,
      n,
    });
  }

  rows.sort((a, b) => a.paramValue - b.paramValue);
  return { rows, excluded, paramName, resultUnit };
}

// ---------------------------------------------------------------------------
// CSV / table columns — units derived from the data, never hardcoded.
// ---------------------------------------------------------------------------

/** Column header for the named parameter, e.g. "anneal_temp_degC" (falls
 *  back to the bare name when the sample recorded no unit). Takes the unit
 *  off the first row — samples sharing one parameter name are expected to
 *  share its unit; item 23's editor is where that convention is enforced
 *  per-sample. */
export function paramColumn(paramName: string, paramUnit: string | null): string {
  return paramUnit ? `${paramName}_${unitToken(paramUnit)}` : paramName;
}

/** Column headers for the result-vs-parameter table/CSV, e.g.
 *  ["sample", "anneal_temp_degC", "n", "area_um2_mean", "area_um2_sd"].
 *  Falls back to "area_mean"/"area_sd" (no unit) only when nothing
 *  calibrated — `result.rows` is then empty besides. */
export function compareCsvColumns(result: ProjectCompareResult): string[] {
  const token = result.resultUnit ? unitToken(result.resultUnit) : null;
  const meanCol = token ? `area_${token}2_mean` : "area_mean";
  const sdCol = token ? `area_${token}2_sd` : "area_sd";
  const firstParamUnit = result.rows[0]?.paramUnit ?? null;
  return ["sample", paramColumn(result.paramName, firstParamUnit), "n", meanCol, sdCol];
}

/** Row data matching compareCsvColumns, in the same order. */
export function compareCsvRows(rows: SampleCompareRow[]): (string | number)[][] {
  return rows.map((r) => [r.sampleName, r.paramValue, r.n, r.mean, r.std]);
}
