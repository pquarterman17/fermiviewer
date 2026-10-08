import type { GrainResult } from "../../lib/api";
import type { QualityAssessment } from "../../lib/analysisQuality";
import { pickSizeValues } from "../../lib/populationHistogram";

export function AnalysisQualityCard({
  value,
  accepted,
  onAccept,
}: {
  value: QualityAssessment;
  accepted: boolean;
  onAccept: () => void;
}) {
  return (
    <div className={`fvd-quality ${value.rating}`} role={value.rating === "poor" ? "alert" : "status"}>
      <div className="fvd-quality-head">
        <span className="fvd-quality-badge">{value.rating}</span>
        <span>{value.summary}</span>
      </div>
      {value.concerns.length > 0 && (
        <ul>
          {value.concerns.map((item, index) => (
            <li key={`${item.message}-${index}`}>
              {item.message} <span>{item.suggestion}</span>
            </li>
          ))}
        </ul>
      )}
      {value.rating === "poor" && !accepted && (
        <button className="fvd-btn" onClick={onAccept}>Use anyway</button>
      )}
      {value.rating === "poor" && accepted && (
        <div className="fvd-quality-accepted">Accepted for manual review — not validated.</div>
      )}
    </div>
  );
}

/** Mean equivalent diameter in the same unit the size histogram uses
 *  (calibrated when every grain is, px otherwise) — the tile used to say px
 *  while the histogram beside it read nm. */
export function grainMeanDiameter(r: GrainResult): string {
  const { values, unit } = pickSizeValues(
    r.equiv_diameter_px ?? [],
    r.diameter_calibrated ?? [],
    r.unit,
  );
  if (unit === "px" || values.length === 0) {
    return `${r.mean_diameter_px.toFixed(1)} px`;
  }
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return `${Number(mean.toPrecision(4))} ${unit}`;
}

export function GrainMetrics({ r }: { r: GrainResult }) {
  const tiles: { v: string; k: string }[] = [
    { v: String(r.n_grains), k: "grains" },
    { v: grainMeanDiameter(r), k: "mean ⌀" },
  ];
  if (r.astm_grain_size != null) {
    tiles.push({ v: `G ${r.astm_grain_size.toFixed(1)}`, k: "ASTM" });
  }
  tiles.push({ v: String(r.n_triple_junctions), k: "junctions" });
  return (
    <div className="fvd-metrics">
      {tiles.map((tile) => (
        <div key={tile.k} className="fvd-metric">
          <span className="v">{tile.v}</span>
          <span className="k">{tile.k}</span>
        </div>
      ))}
    </div>
  );
}
