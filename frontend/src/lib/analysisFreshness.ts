/** Stable identity for controls that determine a regional height analysis. */
export function heightAnalysisKey(
  regionChoice: string,
  roi: [number, number, number, number] | null,
  backgroundRemoval: string,
): string {
  return `${regionChoice}|${roi?.join(",") ?? "whole"}|${backgroundRemoval}`;
}
