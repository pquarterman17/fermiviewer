import { post } from "./transport";

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
