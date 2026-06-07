// EDS workshop (handoff §4 Inspector · EDS): element list, Cliff-Lorimer
// or ZAF quantification; derived at% maps register into the library.

import { useState } from "react";

import { edsQuantify, type EdsQuantResult } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import EdsComposite, { EDS_PALETTE, type Channel } from "./EdsComposite";

export default function EdsWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);

  const [elements, setElements] = useState("Fe, O");
  const [method, setMethod] = useState<"cliff-lorimer" | "zaf">(
    "cliff-lorimer",
  );
  const [thickness, setThickness] = useState("100");
  const [takeOff, setTakeOff] = useState("20");
  const [result, setResult] = useState<EdsQuantResult | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [busy, setBusy] = useState(false);

  const isCube = meta?.kind === "spectrum_image";

  const run = () => {
    if (!activeId) return;
    const els = elements
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean);
    if (els.length === 0) {
      setStatus("EDS: enter at least one element symbol");
      return;
    }
    setBusy(true);
    edsQuantify(activeId, els, {
      method,
      thicknessNm: Number(thickness) || 100,
      takeOffAngleDeg: Number(takeOff) || 20,
    })
      .then((r) => {
        setResult(r);
        // surface derived at% maps in the library
        useViewer.setState((s) => {
          const images = { ...s.images };
          const order = [...s.order];
          for (const m of r.maps) {
            if (!(m.id in images)) order.push(m.id);
            images[m.id] = m;
          }
          return { images, order };
        });
        setChannels(
          r.maps.map((m, i) => ({
            id: m.id,
            el: r.elements[i],
            color: EDS_PALETTE[i % EDS_PALETTE.length],
            intensity: 1,
            visible: true,
          })),
        );
        setStatus(`EDS: quantified ${r.elements.join(", ")}`);
      })
      .catch((e: Error) => setStatus(`EDS: ${e.message}`))
      .finally(() => setBusy(false));
  };

  if (!isCube) {
    return (
      <div className="fvd-ws-empty">
        Select an EDS spectrum-image cube in the library.
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-row">
        <span className="k">Elements</span>
        <input
          value={elements}
          style={{ flex: 1 }}
          placeholder="Fe, O, Si"
          onChange={(e) => setElements(e.target.value)}
        />
      </div>
      <div className="fvd-ws-row">
        <span className="k">Method</span>
        <div className="fvd-seg">
          {(["cliff-lorimer", "zaf"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${method === m ? " active" : ""}`}
              onClick={() => setMethod(m)}
            >
              {m === "cliff-lorimer" ? "Cliff–Lorimer" : "ZAF"}
            </button>
          ))}
        </div>
      </div>
      {method === "zaf" && (
        <div className="fvd-ws-row">
          <span className="k">t (nm)</span>
          <input
            value={thickness}
            style={{ width: 56 }}
            onChange={(e) => setThickness(e.target.value)}
          />
          <span className="k">take-off °</span>
          <input
            value={takeOff}
            style={{ width: 48 }}
            onChange={(e) => setTakeOff(e.target.value)}
          />
        </div>
      )}
      <div className="fvd-ws-row">
        <button className="fvd-btn" onClick={run} disabled={busy}>
          {busy ? "Quantifying…" : "Quantify"}
        </button>
      </div>

      {result && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>El</th>
              <th>Line</th>
              <th>at%</th>
              <th>wt%</th>
              <th>k</th>
            </tr>
          </thead>
          <tbody>
            {result.elements.map((el, i) => (
              <tr key={el}>
                <td>{el}</td>
                <td>{result.lines[i]}</td>
                <td>{result.mean_atomic_pct[i].toFixed(2)}</td>
                <td>{result.mean_weight_pct[i].toFixed(2)}</td>
                <td>{result.k_factors[i].toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {result && (
        <div className="fvd-ws-note">
          {result.maps.length} at% map{result.maps.length === 1 ? "" : "s"}{" "}
          added to the library.
        </div>
      )}
      <EdsComposite channels={channels} onChange={setChannels} />
    </div>
  );
}
