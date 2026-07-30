// Spectrum integration readout: what the current energy window actually
// contains, plus the regions the user has pinned for comparison.
//
// The live line is computed from the displayed spectrum, so it answers "how
// much signal is in this window, on this pixel/ROI/whole cube" — a different
// and more directly readable quantity than the element map's per-pixel total.
// Net is reported unclamped: a negative net means the window holds no peak
// above its background, which is exactly what the user needs to see.

import { useElementColors } from "../../lib/eds/elementColors";
import type { WindowIntegration } from "../../lib/eds/integrate";
import type { IntegrationRegion } from "../../lib/eds/regions";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";

function pm(value: number, error: number): string {
  return `${formatCountTick(value)} ± ${formatCountTick(error)}`;
}

export default function EdsIntegrationPanel({
  current,
  element,
  unit,
  source,
  regions,
  onAdd,
  onRemove,
  onClear,
  onSelect,
  onExport,
}: {
  current: WindowIntegration | null;
  /** "(custom)" or an element symbol — names the region when pinned. */
  element: string;
  unit: string;
  source: string;
  regions: IntegrationRegion[];
  onAdd: () => void;
  onRemove: (id: string) => void;
  onClear: () => void;
  onSelect: (region: IntegrationRegion) => void;
  onExport: () => void;
}) {
  const colors = useElementColors();

  return (
    <section className="fvd-eds-integration" aria-label="Spectrum integration">
      <div className="fvd-eds-integration-live">
        {current ? (
          <>
            <div>
              <strong>
                Net {pm(current.net, current.sigma)}
              </strong>
              <span className="k">
                {" "}
                ({(current.fraction * 100).toFixed(2)}% of spectrum)
              </span>
            </div>
            <div className="k">
              {current.eLo.toFixed(3)}–{current.eHi.toFixed(3)} {unit} ·{" "}
              {current.channels} ch · gross {formatCountTick(current.gross)} ·{" "}
              {current.bg === "none"
                ? "no background"
                : `${current.bg} bg ${formatCountTick(current.background)}`}
            </div>
            {current.note && (
              <div className="fvd-ws-note">{current.note}</div>
            )}
          </>
        ) : (
          <div className="k">No channels in the current energy window.</div>
        )}
        <button
          type="button"
          className="fvd-btn"
          disabled={!current}
          title={
            element === "(custom)"
              ? "Pin this window's integral to the region list"
              : `Pin this integral to the region list as ${element}`
          }
          onClick={onAdd}
        >
          + Add region
        </button>
      </div>

      {regions.length > 0 && (
        <>
          <div className="fvd-eds-integration-head">
            <strong>Integrated regions</strong>
            <div>
              <button type="button" className="fvd-btn" onClick={onExport}>
                CSV
              </button>
              <button type="button" className="fvd-btn" onClick={onClear}>
                Clear
              </button>
            </div>
          </div>
          <table className="fvd-ws-table fvd-eds-integration-table">
            <thead>
              <tr>
                <th scope="col">Region</th>
                <th scope="col">Window ({unit})</th>
                <th scope="col">Bg</th>
                <th scope="col">Net ± 1σ</th>
                <th scope="col">%</th>
                <th scope="col">
                  <span className="fvd-visually-hidden">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {regions.map((r) => (
                <tr key={r.id}>
                  <td>
                    <button
                      type="button"
                      className="fvd-eds-region-name"
                      title={`Restore this window and frame it · measured on ${r.source}`}
                      onClick={() => onSelect(r)}
                    >
                      <span
                        className="fvd-eds-region-swatch"
                        style={{ background: colors(r.label) }}
                        aria-hidden="true"
                      />
                      {r.label}
                    </button>
                  </td>
                  <td>
                    {r.eLo.toFixed(3)}–{r.eHi.toFixed(3)}
                  </td>
                  <td>{r.bg === "bremsstrahlung" ? "brems" : r.bg}</td>
                  <td>{pm(r.net, r.sigma)}</td>
                  <td>{(r.fraction * 100).toFixed(2)}</td>
                  <td>
                    <button
                      type="button"
                      className="fvd-icon-btn"
                      aria-label={`Remove region ${r.label}`}
                      onClick={() => onRemove(r.id)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="fvd-ws-note">
            Regions are snapshots of the spectrum they were measured on ·
            current source: {source}
          </div>
        </>
      )}
    </section>
  );
}
