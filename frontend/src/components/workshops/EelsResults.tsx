import type { EelsFitResult, EelsQuantResult } from "../../lib/api";
import { formatPlusMinus } from "../../lib/formatUncertainty";
import EelsFitResidualPlot from "./eels/EelsFitResidualPlot";

export function EelsFitResults({ result }: { result: EelsFitResult }) {
  return (
    <>
      <div className="fvd-ws-note">
        Model fit · χ²ᵣ {result.reduced_chi2.toExponential(2)} · R²{" "}
        {result.r_squared.toFixed(3)}
        {result.success ? "" : " · (not converged)"}
      </div>
      <EelsFitResidualPlot result={result} />
      <table className="fvd-ws-table">
        <thead>
          <tr>
            <th>Element</th>
            <th>at% ± 1σ</th>
            <th>amp ± 1σ</th>
          </tr>
        </thead>
        <tbody>
          {result.edges.map((edge) => (
            <tr key={`${edge.element}-${edge.shell}`}>
              <td>{edge.element}</td>
              <td>
                {formatPlusMinus(
                  edge.atomic_percent,
                  edge.atomic_percent_error,
                  2,
                )}
              </td>
              <td>
                {edge.amplitude.toExponential(2)} ±{" "}
                {edge.amplitude_error.toExponential(1)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function EelsQuantResults({
  result,
  onExport,
}: {
  result: EelsQuantResult;
  onExport: () => void;
}) {
  return (
    <>
      <table className="fvd-ws-table">
        <thead>
          <tr>
            <th>Element</th>
            <th>at% ± 1σ</th>
            <th>I</th>
          </tr>
        </thead>
        <tbody>
          {result.elements.map((element, index) => (
            <tr key={element}>
              <td>{element}</td>
              <td>
                {formatPlusMinus(
                  result.atomic_percent[index],
                  result.atomic_percent_error?.[index] ?? 0,
                  2,
                )}
              </td>
              <td>{result.intensity[index].toExponential(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          onClick={onExport}
          title="Download the EELS quantification table as CSV"
        >
          Export CSV
        </button>
      </div>
    </>
  );
}
