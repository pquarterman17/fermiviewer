import type { StepHeightResult } from "../../lib/api";

type Sample = number | null;

const isNumber = (value: Sample): value is number => value !== null && Number.isFinite(value);

function points(values: Sample[], width: number, height: number, domain?: [number, number]): string {
  if (!values.length) return "";
  const finite = values.filter(isNumber);
  const lo = domain?.[0] ?? Math.min(...finite);
  const hi = domain?.[1] ?? Math.max(...finite);
  const span = Math.max(hi - lo, Number.EPSILON);
  return values.map((v, i) => {
    if (!isNumber(v)) return "";
    const x = values.length === 1 ? width / 2 : i * width / (values.length - 1);
    return `${x.toFixed(1)},${(height - (v - lo) * height / span).toFixed(1)}`;
  }).join(" ");
}

export function stepWarnings(result: StepHeightResult): string[] {
  const warnings: string[] = [];
  const scatter = Math.max(result.lower_std, result.upper_std);
  if (result.height < 3 * scatter) warnings.push("Weak terrace separation relative to surface scatter.");
  if (result.upper_fraction < 0.15 || result.upper_fraction > 0.85) warnings.push("Terraces are strongly unequal; include more of the smaller terrace.");
  if (Math.min(result.n_lower, result.n_upper) < 64) warnings.push("A terrace has too few fitted pixels for a robust measurement.");
  const positions = result.profile_position.filter(isNumber);
  const span = positions[positions.length - 1] ?? 0;
  const along = result.profile_axis === "x" ? result.slope_x : result.slope_y;
  if (Math.abs(along * span) > 0.5 * result.height) warnings.push("Background slope is large relative to the step height.");
  if (result.fit_rms > 0.25 * result.height) warnings.push("Fit residuals are large relative to the step height.");
  return warnings;
}

export default function AfmStepEvidence({ result }: { result: StepHeightResult }) {
  const warnings = stepWarnings(result);
  const profileValues = [...result.profile_measured, ...result.profile_fitted].filter(isNumber);
  const profileDomain: [number, number] = [Math.min(...profileValues), Math.max(...profileValues)];
  return <section className="fvd-afm-step-evidence" aria-labelledby="afm-step-evidence-title">
    <div className="fvd-afm-section-head"><div><h3 id="afm-step-evidence-title">Fit evidence</h3><span>Profile runs in increasing {result.profile_axis.toUpperCase()}</span></div></div>
    {warnings.length > 0 && <div className="fvd-ws-note warning" role="alert"><strong>Check this fit</strong><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
    <div className="fvd-afm-step-visuals">
      <figure><figcaption>Terrace mask</figcaption><div className="fvd-afm-terrace-mask" style={{ aspectRatio: `${result.terrace_mask[0]?.length ?? 1} / ${result.terrace_mask.length || 1}`, gridTemplateColumns: `repeat(${result.terrace_mask[0]?.length ?? 1}, 1fr)` }} role="img" aria-label="Lower and upper fitted terrace mask">{result.terrace_mask.flatMap((row, y) => row.map((value, x) => <i key={`${x}-${y}`} data-terrace={value} />))}</div></figure>
      <figure><figcaption>Measured profile and fitted levels</figcaption><svg viewBox="0 0 320 120" role="img" aria-label="Step sampling profile"><polyline className="measured" points={points(result.profile_measured, 320, 120, profileDomain)} /><polyline className="fitted" points={points(result.profile_fitted, 320, 120, profileDomain)} /></svg><div className="fvd-chart-legend"><span>Measured</span><span>Fit</span></div></figure>
      <figure><figcaption>Profile residuals</figcaption><svg viewBox="0 0 320 80" role="img" aria-label="Step fit residuals"><polyline className="residual" points={points(result.profile_residual, 320, 80)} /></svg></figure>
    </div>
  </section>;
}
