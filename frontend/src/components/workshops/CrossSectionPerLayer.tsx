import { useState } from "react";

import { analyzeGrainsByLayer } from "../../lib/api";
import type {
  CrossSectionGrainsSnapshot,
  CrossSectionLayersSnapshot,
} from "../../store/crossSection";
import { useCrossSection } from "../../store/crossSection";
import { useViewer } from "../../store/viewer";

type Roi = [number, number, number, number] | null;

interface Props {
  sourceId: string;
  roi: Roi;
  layers: CrossSectionLayersSnapshot;
  grains: CrossSectionGrainsSnapshot;
  selected: number[];
  onSelected: (value: number[]) => void;
}

function format(value: number, digits = 2): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export default function CrossSectionPerLayer({
  sourceId, roi, layers, grains, selected, onSelected,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const perLayer = useCrossSection((s) => s.perLayer);
  const setPerLayer = useCrossSection((s) => s.setPerLayer);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setActive = useViewer((s) => s.setActive);
  const setDisplay = useViewer((s) => s.setDisplay);
  const setStatus = useViewer((s) => s.setStatus);
  const current = perLayer?.sourceId === sourceId
    && perLayer.roi?.join(":") === roi?.join(":")
    && Boolean(perLayer.roi) === Boolean(roi)
    && perLayer.selectedLayerIndices.join(":") === selected.join(":")
    ? perLayer.result : null;

  const toggle = (index: number) => {
    onSelected(selected.includes(index)
      ? selected.filter((item) => item !== index)
      : [...selected, index].sort((a, b) => a - b));
  };
  const run = () => {
    setBusy(true);
    setError("");
    analyzeGrainsByLayer(grains.result.labels.id, layers.result, selected, roi)
      .then((result) => {
        ingestDerived([result.assignment]);
        setDisplay(result.assignment.id, { cmap: "label" }, { silent: true });
        setActive(sourceId);
        setPerLayer({ sourceId, roi, selectedLayerIndices: selected, result });
        setStatus(`cross-section: measured grains in ${result.layers.length} film layer(s)`);
      })
      .catch((cause: Error) => {
        setError(cause.message);
        setStatus(`cross-section layer grains: ${cause.message}`);
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="fvd-per-layer">
      <div className="fvd-ws-section">Choose film layers</div>
      <div className="fvd-ws-note">
        Keep deposited-film bands selected; clear vacuum, protective cap, and substrate.
      </div>
      <div className="fvd-layer-choices" aria-label="Film layers">
        {layers.result.layers.map((layer) => (
          <label key={layer.index} className={selected.includes(layer.index) ? "selected" : ""}>
            <input
              type="checkbox"
              checked={selected.includes(layer.index)}
              onChange={() => toggle(layer.index)}
            />
            Layer {layer.index + 1}
            <span>{format(layer.thickness)} {layers.result.unit}</span>
          </label>
        ))}
      </div>
      <button className="fvd-btn primary" disabled={busy || selected.length === 0} onClick={run}>
        {busy ? "Measuring…" : "Measure selected layers"}
      </button>
      {error && <div className="fvd-quality poor">{error}</div>}
      {current && (
        <>
          <div className="fvd-layer-grain-table-wrap">
            <table className="fvd-table fvd-layer-grain-table">
              <thead><tr>
                <th>Layer</th><th>grains</th><th>density</th><th>mean width</th><th>mean height</th>
                <th>aspect</th><th>shape angle</th><th>crossing</th>
              </tr></thead>
              <tbody>{current.layers.map((layer) => (
                <tr key={layer.index}>
                  <td>{layer.index + 1}</td>
                  <td>{layer.n_grains}</td>
                  <td>{current.unit === "px"
                    ? `${format(layer.density_per_mpx)} / Mpx`
                    : `${format(layer.density_per_unit2, 3)} / ${current.unit}²`}</td>
                  <td>{format(layer.mean_lateral_width)} {current.unit}</td>
                  <td>{format(layer.mean_depth_height)} {current.unit}</td>
                  <td>{format(layer.mean_aspect_ratio)}</td>
                  <td>{format(layer.mean_shape_angle_deg, 1)}°</td>
                  <td>{layer.cross_layer_grains}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="fvd-ws-row">
            <button className="fvd-btn" onClick={() => setActive(current.assignment.id)}>
              Show assignment map
            </button>
            <button className="fvd-btn" onClick={() => setActive(sourceId)}>Show source</button>
          </div>
          <div className="fvd-ws-note">
            Shape angle is morphological, not crystallographic. “Crossing” counts grains clipped by a reviewed interface.
          </div>
        </>
      )}
    </div>
  );
}
