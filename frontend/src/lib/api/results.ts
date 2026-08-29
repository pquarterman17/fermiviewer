import { post } from "./transport";
import type { PersistedResultOutput, PersistedResultRecord } from "./project";

export interface CalibrationAgreementWire {
  verified: boolean;
  agrees: boolean;
  shared_sources: string[];
  reference_only: string[];
  candidate_only: string[];
  differences: string[];
}

export interface ResultComparisonMatch {
  id: string;
  outputs: string[];
  calibration_agreement: CalibrationAgreementWire;
}

export interface ResultComparisonRejection {
  id: string;
  code: string;
  message: string;
}

export interface ResultComparison {
  reference_id: string;
  outputs: string[];
  compatible: ResultComparisonMatch[];
  rejected: ResultComparisonRejection[];
  notes: string[];
}

export interface ReportOutput extends PersistedResultOutput {
  caption?: string;
  shape?: number[] | null;
  dtype?: string | null;
  values?: unknown[] | null;
  values_inlined?: boolean;
}

export interface ReportResult extends PersistedResultRecord {
  methods: string;
  outputs?: ReportOutput[];
}

export interface ReportCalibrationVariant {
  axes: Array<{ index: number; scale: number | null; origin: number | null; units: string; calibrated: boolean }>;
  source: string | null;
  result_ids: string[];
}

export interface ReportCalibrationSummary {
  image_id: string;
  result_ids: string[];
  consistent: boolean;
  variants: ReportCalibrationVariant[];
}

export interface ResultsReport {
  version: number;
  generated_at: string;
  app_version: string;
  results: ReportResult[];
  calibration: ReportCalibrationSummary[];
  methods: string;
  warnings: string[];
}

/** Ask the backend's canonical compatibility rules which results can be
 * compared. Omitting candidates evaluates every other saved result. */
export function comparePersistedResults(
  referenceId: string,
  candidateIds?: string[],
  signal?: AbortSignal,
): Promise<ResultComparison> {
  return post("/api/results/compare", {
    reference_id: referenceId,
    ...(candidateIds ? { candidate_ids: candidateIds } : {}),
  }, { signal });
}

/** Build the deterministic report manifest in the caller's selected order. */
export function buildPersistedResultsReport(
  resultIds: string[],
  signal?: AbortSignal,
): Promise<ResultsReport> {
  return post("/api/results/report", { result_ids: resultIds }, { signal });
}
