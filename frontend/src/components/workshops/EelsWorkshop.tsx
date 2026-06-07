// EELS workshop (handoff §4 Inspector · EELS): spectrum plot with
// power-law background fit, signal-map extraction, edge quantify table.
// Operates on the active image (needs a spectral kind).

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  eelsBackground,
  eelsMap,
  eelsQuantify,
  fetchSpectrum,
  type EelsBackgroundResult,
  type EelsEdge,
  type EelsQuantResult,
  type Spectrum,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import EelsAdvanced from "./EelsAdvanced";

interface EdgeRow extends EelsEdge {
  key: number;
}

let edgeSeq = 0;

export default function EelsWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);

  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [fit, setFit] = useState<EelsBackgroundResult | null>(null);
  const [bgLo, setBgLo] = useState("");
  const [bgHi, setBgHi] = useState("");
  const [sigLo, setSigLo] = useState("");
  const [sigHi, setSigHi] = useState("");
  const [edges, setEdges] = useState<EdgeRow[]>([]);
  const [quant, setQuant] = useState<EelsQuantResult | null>(null);
  const plotHost = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const spectral = meta !== null && meta.kind !== "image";
  const isCube = meta?.kind === "spectrum_image";

  // load the spectrum whenever the active image changes
  useEffect(() => {
    setSpectrum(null);
    setFit(null);
    setQuant(null);
    if (!activeId || !spectral) return;
    let alive = true;
    fetchSpectrum(activeId)
      .then((s) => {
        if (!alive) return;
        setSpectrum(s);
        // seed sensible windows from the energy range
        const e0 = s.energy[0];
        const e1 = s.energy[s.energy.length - 1];
        const span = e1 - e0;
        setBgLo(fmtNum(e0 + 0.1 * span));
        setBgHi(fmtNum(e0 + 0.3 * span));
        setSigLo(fmtNum(e0 + 0.35 * span));
        setSigHi(fmtNum(e0 + 0.6 * span));
      })
      .catch((e: Error) => setStatus(`EELS: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [activeId, spectral, setStatus]);

  // (re)build the plot when spectrum or fit changes
  useEffect(() => {
    const host = plotHost.current;
    if (!host || !spectrum) return;
    plotRef.current?.destroy();
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    const series: uPlot.Series[] = [
      {},
      { label: "spectrum", stroke: "#8888aa", width: 1 },
    ];
    const data: uPlot.AlignedData = [spectrum.energy, spectrum.counts];
    if (fit) {
      series.push({ label: "background", stroke: "#d97706", width: 1 });
      series.push({ label: "signal", stroke: accent, width: 1.5 });
      (data as unknown as number[][]).push(fit.background, fit.signal);
    }
    plotRef.current = new uPlot(
      {
        width: host.clientWidth,
        height: 180,
        series,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      data,
      host,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [spectrum, fit]);

  const runFit = () => {
    if (!activeId) return;
    eelsBackground(activeId, [Number(bgLo), Number(bgHi)])
      .then(setFit)
      .catch((e: Error) => setStatus(`EELS fit: ${e.message}`));
  };

  const runMap = () => {
    if (!activeId) return;
    eelsMap(
      activeId,
      [Number(sigLo), Number(sigHi)],
      bgLo && bgHi ? [Number(bgLo), Number(bgHi)] : null,
    )
      .then((m) => {
        setStatus(`map registered: ${m.name}`);
        // surface the derived image in the library
        useViewer.setState((s) => ({
          images: { ...s.images, [m.id]: m },
          order: s.order.includes(m.id) ? s.order : [...s.order, m.id],
        }));
      })
      .catch((e: Error) => setStatus(`EELS map: ${e.message}`));
  };

  const addEdge = () =>
    setEdges((rows) => [
      ...rows,
      {
        key: ++edgeSeq,
        element: "",
        shell: "K",
        z: 0,
        onset_ev: 0,
        signal_window: [0, 0],
        bg_window: [Number(bgLo) || 0, Number(bgHi) || 0],
      },
    ]);

  const runQuantify = () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS quantify: add at least one edge row");
      return;
    }
    eelsQuantify(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
    )
      .then(setQuant)
      .catch((e: Error) => setStatus(`EELS quantify: ${e.message}`));
  };

  if (!spectral) {
    return (
      <div className="fvd-ws-empty">
        Select a spectrum or spectrum-image in the library.
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      <div ref={plotHost} className="fvd-ws-plot" />
      <div className="fvd-ws-row">
        <span className="k">Background</span>
        <input value={bgLo} onChange={(e) => setBgLo(e.target.value)} />
        <span>–</span>
        <input value={bgHi} onChange={(e) => setBgHi(e.target.value)} />
        <span className="k">{spectrum?.units ?? "eV"}</span>
        <button className="fvd-btn" onClick={runFit}>
          Fit
        </button>
      </div>
      {fit && (
        <div className="fvd-ws-note">
          power-law A·E<sup>−r</sup>: r = {fit.params["r"]?.toFixed(3)}
        </div>
      )}
      <div className="fvd-ws-row">
        <span className="k">Signal</span>
        <input value={sigLo} onChange={(e) => setSigLo(e.target.value)} />
        <span>–</span>
        <input value={sigHi} onChange={(e) => setSigHi(e.target.value)} />
        <span className="k">{spectrum?.units ?? "eV"}</span>
        <button className="fvd-btn" onClick={runMap} disabled={!isCube}>
          Map
        </button>
      </div>

      <div className="fvd-ws-section">
        <span>Edges</span>
        <button className="fvd-btn" onClick={addEdge}>
          + edge
        </button>
        <button
          className="fvd-btn"
          onClick={runQuantify}
          disabled={edges.length === 0}
        >
          Quantify
        </button>
      </div>
      {edges.map((row, i) => (
        <EdgeEditor
          key={row.key}
          row={row}
          onChange={(r) =>
            setEdges((rows) => rows.map((x, j) => (j === i ? r : x)))
          }
          onRemove={() =>
            setEdges((rows) => rows.filter((_, j) => j !== i))
          }
        />
      ))}
      {quant && (
        <table className="fvd-ws-table">
          <thead>
            <tr>
              <th>Element</th>
              <th>at%</th>
              <th>I</th>
            </tr>
          </thead>
          <tbody>
            {quant.elements.map((el, i) => (
              <tr key={el}>
                <td>{el}</td>
                <td>{quant.atomic_percent[i].toFixed(2)}</td>
                <td>{quant.intensity[i].toExponential(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <EelsAdvanced
        activeId={activeId}
        isCube={isCube}
        units={spectrum?.units ?? "eV"}
      />
    </div>
  );
}

function EdgeEditor({
  row,
  onChange,
  onRemove,
}: {
  row: EdgeRow;
  onChange: (r: EdgeRow) => void;
  onRemove: () => void;
}) {
  const num = (v: string) => Number(v) || 0;
  return (
    <div className="fvd-ws-edge">
      <input
        placeholder="El"
        value={row.element}
        style={{ width: 32 }}
        onChange={(e) => onChange({ ...row, element: e.target.value })}
      />
      <input
        placeholder="Z"
        value={row.z || ""}
        style={{ width: 32 }}
        onChange={(e) => onChange({ ...row, z: num(e.target.value) })}
      />
      <select
        value={row.shell}
        onChange={(e) => onChange({ ...row, shell: e.target.value })}
      >
        {["K", "L", "M"].map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      <input
        placeholder="onset"
        value={row.onset_ev || ""}
        style={{ width: 52 }}
        onChange={(e) => onChange({ ...row, onset_ev: num(e.target.value) })}
      />
      <input
        placeholder="sig lo"
        value={row.signal_window[0] || ""}
        style={{ width: 52 }}
        onChange={(e) =>
          onChange({
            ...row,
            signal_window: [num(e.target.value), row.signal_window[1]],
          })
        }
      />
      <input
        placeholder="sig hi"
        value={row.signal_window[1] || ""}
        style={{ width: 52 }}
        onChange={(e) =>
          onChange({
            ...row,
            signal_window: [row.signal_window[0], num(e.target.value)],
          })
        }
      />
      <button className="fvd-icon-btn" onClick={onRemove}>
        ✕
      </button>
    </div>
  );
}

function fmtNum(v: number): string {
  return Number(v.toPrecision(4)).toString();
}
