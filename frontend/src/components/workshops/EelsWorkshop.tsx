// EELS workshop (handoff §4 Inspector · EELS): spectrum plot with
// power-law background fit, signal-map extraction, edge quantify table.
// Operates on the active image (needs a spectral kind).

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeElnes,
  eelsBackground,
  eelsFit,
  eelsFitMap,
  eelsMap,
  eelsQuantify,
  eelsQuantifyMap,
  fetchSpectrum,
  type EelsBackgroundResult,
  type EelsEdge,
  type EelsFitResult,
  type EelsQuantResult,
  type ElnesResult,
  type Spectrum,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import {
  csvBaseName,
  downloadCsv,
  eelsQuantToCsv,
} from "../../lib/eelsQuantCsv";
import EelsAdvanced from "./EelsAdvanced";
import RegionPicker, { type Rect1 } from "./RegionPicker";

interface EdgeRow extends EelsEdge {
  key: number;
}

let edgeSeq = 0;

/** Common EELS edge onsets (eV) for the edge-ID overlay. */
const KNOWN_EDGES: [string, number][] = [
  ["Li-K", 55], ["B-K", 188], ["C-K", 284], ["N-K", 401], ["O-K", 532],
  ["F-K", 685], ["Na-K", 1072], ["Mg-K", 1305], ["Al-K", 1560],
  ["Si-K", 1839], ["Si-L2,3", 99], ["P-L2,3", 132], ["S-L2,3", 165],
  ["Ca-L2,3", 346], ["Ti-L2,3", 456], ["V-L2,3", 513], ["Cr-L2,3", 575],
  ["Mn-L2,3", 640], ["Fe-L2,3", 708], ["Co-L2,3", 779], ["Ni-L2,3", 855],
  ["Cu-L2,3", 931], ["Zn-L2,3", 1020], ["Sr-L2,3", 1940],
  ["La-M4,5", 832], ["Ce-M4,5", 883], ["Gd-M4,5", 1185],
];

export default function EelsWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const specnavPixel = useViewer((s) => s.specnavPixel);

  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [fit, setFit] = useState<EelsBackgroundResult | null>(null);
  const [bgLo, setBgLo] = useState("");
  const [bgHi, setBgHi] = useState("");
  const [sigLo, setSigLo] = useState("");
  const [sigHi, setSigHi] = useState("");
  const [edges, setEdges] = useState<EdgeRow[]>([]);
  const [quant, setQuant] = useState<EelsQuantResult | null>(null);
  const [fitResult, setFitResult] = useState<EelsFitResult | null>(null);
  const [elnes, setElnes] = useState<ElnesResult | null>(null);
  const [showEdges, setShowEdges] = useState(false);
  const [elementFilter, setElementFilter] = useState("");
  const [e0Kv, setE0Kv] = useState(200);
  const [betaMrad, setBetaMrad] = useState(10);
  const [quantMethod, setQuantMethod] = useState("powerlaw");
  const [explore, setExplore] = useState(false);
  const [pickMode, setPickMode] = useState<"region" | "pixel">("region");
  const [region, setRegion] = useState<Rect1 | null>(null);
  const plotHost = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const spectral = meta !== null && meta.kind !== "image";
  const isCube = meta?.kind === "spectrum_image";

  // load the spectrum whenever the active image / region changes
  useEffect(() => {
    setSpectrum(null);
    setFit(null);
    setQuant(null);
    setFitResult(null);
    if (!activeId || !spectral) return;
    let alive = true;
    fetchSpectrum(activeId, region ?? undefined)
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
  }, [activeId, spectral, region, setStatus]);

  // reset the explorer region when switching images
  useEffect(() => {
    setRegion(null);
    setExplore(false);
    setPickMode("region");
  }, [activeId]);

  // #10 specnav: a pixel picked on the MAIN stage drives the spectrum by
  // feeding the same `region` the in-panel picker uses (1×1 rect).
  useEffect(() => {
    if (!isCube || !specnavPixel) return;
    const [r, c] = specnavPixel;
    setRegion([r, c, r, c]);
  }, [specnavPixel, isCube]);

  // turn specnav off when the workshop unmounts (don't leave the stage armed)
  useEffect(
    () => () => {
      if (useViewer.getState().captureMode === "specnav")
        useViewer.getState().setCaptureMode("none");
    },
    [],
  );

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
    // model-fit overlay (#2): total model + power-law bg + per-edge components,
    // shown on the same energy axis as the summed spectrum
    if (fitResult && fitResult.energy.length === spectrum.energy.length) {
      series.push({ label: "model", stroke: accent, width: 1.5, dash: [4, 2] });
      series.push({ label: "bg (fit)", stroke: "#d97706", width: 1, dash: [2, 2] });
      (data as unknown as number[][]).push(fitResult.model, fitResult.background);
      const palette = ["#22d3ee", "#f472b6", "#fbbf24", "#34d399", "#c084fc"];
      fitResult.edges.forEach((ed, k) => {
        series.push({
          label: ed.element,
          stroke: palette[k % palette.length],
          width: 1,
        });
        (data as unknown as number[][]).push(ed.curve);
      });
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
        hooks: {
          draw: [
            (u) => {
              if (!showEdges) return;
              // edge-ID overlay: vertical markers at known onsets
              const ctx = u.ctx;
              const sc = u.scales["x"];
              const lo = sc?.min ?? 0;
              const hi = sc?.max ?? 0;
              ctx.save();
              ctx.strokeStyle = "rgba(244, 63, 94, 0.55)";
              ctx.fillStyle = "rgba(244, 63, 94, 0.9)";
              ctx.font = "10px monospace";
              const efLower = elementFilter.toLowerCase();
              for (const [name, ev] of KNOWN_EDGES) {
                if (efLower && !name.toLowerCase().startsWith(efLower)) continue;
                if (ev < lo || ev > hi) continue;
                const x = u.valToPos(ev, "x", true);
                ctx.beginPath();
                ctx.moveTo(x, u.bbox.top);
                ctx.lineTo(x, u.bbox.top + u.bbox.height);
                ctx.stroke();
                ctx.fillText(name, x + 2, u.bbox.top + 10);
              }
              ctx.restore();
            },
          ],
        },
      },
      data,
      host,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [spectrum, fit, fitResult, showEdges, elementFilter]);

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
      e0Kv,
      betaMrad,
      quantMethod,
    )
      .then(setQuant)
      .catch((e: Error) => setStatus(`EELS quantify: ${e.message}`));
  };

  const runQuantifyMaps = () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS maps: add at least one edge row");
      return;
    }
    eelsQuantifyMap(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
      quantMethod,
    )
      .then((r) => {
        useViewer.getState().ingestDerived(r.maps);
        setStatus(
          `EELS composition maps: ` +
            r.elements
              .map(
                (el, i) =>
                  `${el} ${r.mean_atomic_percent[i].toFixed(1)}%`,
              )
              .join(" · "),
        );
      })
      .catch((e: Error) => setStatus(`EELS maps: ${e.message}`));
  };

  // model-based simultaneous fit (#2): background + all edges in one fit,
  // at% from the fitted amplitude ratios (separates overlapping edges)
  const runModelFit = () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS fit: add at least one edge row");
      return;
    }
    const fitRange: [number, number] | null =
      bgLo && spectrum
        ? [Number(bgLo), spectrum.energy[spectrum.energy.length - 1]]
        : null;
    eelsFit(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
      fitRange,
    )
      .then((r) => {
        setFitResult(r);
        setStatus(
          `EELS fit · χ²ᵣ ${r.reduced_chi2.toExponential(2)} · ` +
            r.edges
              .map((ed) => `${ed.element} ${ed.atomic_percent.toFixed(1)}%`)
              .join(" · "),
        );
      })
      .catch((e: Error) => setStatus(`EELS fit: ${e.message}`));
  };

  const runModelFitMaps = () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS fit maps: add at least one edge row");
      return;
    }
    eelsFitMap(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
    )
      .then((r) => {
        useViewer.getState().ingestDerived(r.maps);
        setStatus(
          `EELS fit maps · ` +
            r.elements
              .map((el, i) => `${el} ${r.mean_atomic_percent[i].toFixed(1)}%`)
              .join(" · "),
        );
      })
      .catch((e: Error) => setStatus(`EELS fit maps: ${e.message}`));
  };

  const runElnes = () => {
    if (!activeId || edges.length === 0) {
      setStatus("ELNES: add an edge row first to define edge_onset");
      return;
    }
    const edge = edges[edges.length - 1];
    const onset = edge.onset_ev || 0;
    if (onset <= 0) {
      setStatus("ELNES: set edge onset (eV) in the edge row first");
      return;
    }
    const fitWin: [number, number] = [
      edge.bg_window[0] || onset - 100,
      edge.bg_window[1] || onset - 10,
    ];
    analyzeElnes(activeId, onset, fitWin)
      .then((r) => {
        setElnes(r);
        setStatus(
          `ELNES: jump ${r.edge_jump.toExponential(2)} · onset ${r.edge_onset.toFixed(1)} eV`,
        );
      })
      .catch((e: Error) => setStatus(`ELNES: ${e.message}`));
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
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={showEdges}
            onChange={(e) => setShowEdges(e.target.checked)}
          />
          Edge IDs
        </label>
        <span className="k">element</span>
        <input
          placeholder="all"
          value={elementFilter}
          style={{ width: 44 }}
          onChange={(e) => setElementFilter(e.target.value.trim())}
        />
        {isCube && (
          <label className="fvd-check">
            <input
              type="checkbox"
              checked={explore}
              onChange={(e) => {
                setExplore(e.target.checked);
                if (!e.target.checked) setRegion(null);
              }}
            />
            Region explorer
          </label>
        )}
        {isCube && (
          <label
            className="fvd-check"
            title="click or drag the main image to read its spectrum here"
          >
            <input
              type="checkbox"
              checked={captureMode === "specnav"}
              onChange={(e) =>
                setCaptureMode(e.target.checked ? "specnav" : "none")
              }
            />
            Navigate on image
          </label>
        )}
        {region && (
          <span className="k">
            {region[0] === region[2] && region[1] === region[3]
              ? `px [${region[0]},${region[1]}]`
              : `[${region[0]},${region[1]}]–[${region[2]},${region[3]}]`}
          </span>
        )}
      </div>
      {explore && isCube && (
        <div className="fvd-ws-row">
          <span className="k">pick</span>
          <div className="fvd-seg">
            {(["region", "pixel"] as const).map((m) => (
              <button
                key={m}
                className={`fvd-seg-btn${pickMode === m ? " active" : ""}`}
                title={
                  m === "pixel"
                    ? "click a single pixel to read its spectrum"
                    : "drag a box to average a region"
                }
                onClick={() => {
                  setPickMode(m);
                  setRegion(null); // switching mode starts fresh (full image)
                }}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      )}
      {explore && activeId && (
        <RegionPicker
          id={activeId}
          onRegion={setRegion}
          pixelMode={pickMode === "pixel"}
        />
      )}
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

      <div className="fvd-ws-row">
        <span className="k">E₀ kV</span>
        <input
          type="number"
          value={e0Kv}
          min={60}
          max={1000}
          step={10}
          style={{ width: 52 }}
          onChange={(e) => setE0Kv(Number(e.target.value) || 200)}
        />
        <span className="k">β mrad</span>
        <input
          type="number"
          value={betaMrad}
          min={1}
          max={100}
          step={1}
          style={{ width: 44 }}
          onChange={(e) => setBetaMrad(Number(e.target.value) || 10)}
        />
        <select
          value={quantMethod}
          onChange={(e) => setQuantMethod(e.target.value)}
        >
          <option value="powerlaw">power-law</option>
          <option value="exponential">exponential</option>
        </select>
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
        <button
          className="fvd-btn"
          title="Per-pixel at% composition maps (SI cubes)"
          onClick={runQuantifyMaps}
          disabled={edges.length === 0 || !isCube}
        >
          Maps
        </button>
        <button
          className="fvd-btn"
          title="Model fit: background + all edges fitted jointly (separates overlapping edges; at% from amplitude ratios with 1σ)"
          onClick={runModelFit}
          disabled={edges.length === 0}
        >
          Model fit
        </button>
        <button
          className="fvd-btn"
          title="Per-pixel model-fit at% maps (SI cubes)"
          onClick={runModelFitMaps}
          disabled={edges.length === 0 || !isCube}
        >
          Fit maps
        </button>
        <button
          className="fvd-btn"
          title="ELNES fine-structure extraction (uses last edge row's onset + bg window)"
          onClick={runElnes}
          disabled={edges.length === 0}
        >
          ELNES
        </button>
      </div>
      {fitResult && (
        <>
          <div className="fvd-ws-note">
            Model fit · χ²ᵣ {fitResult.reduced_chi2.toExponential(2)}
            {fitResult.success ? "" : " · (not converged)"}
          </div>
          <table className="fvd-ws-table">
            <thead>
              <tr>
                <th>Element</th>
                <th>at%</th>
                <th>amp ± 1σ</th>
              </tr>
            </thead>
            <tbody>
              {fitResult.edges.map((ed) => (
                <tr key={`${ed.element}-${ed.shell}`}>
                  <td>{ed.element}</td>
                  <td>{ed.atomic_percent.toFixed(2)}</td>
                  <td>
                    {ed.amplitude.toExponential(2)} ±{" "}
                    {ed.amplitude_error.toExponential(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {elnes && (
        <div className="fvd-ws-note">
          ELNES · edge jump {elnes.edge_jump.toExponential(2)} · onset{" "}
          {elnes.edge_onset.toFixed(1)} eV ·{" "}
          {elnes.relative_energy.length} pts
        </div>
      )}
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
        <>
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
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              onClick={() => {
                const base = csvBaseName(meta?.name);
                downloadCsv(
                  `${base}_eels_quant.csv`,
                  eelsQuantToCsv(quant, { imageName: meta?.name ?? (activeId ?? "") }),
                );
                setStatus(`EELS: exported ${quant.elements.length} elements`);
              }}
            >
              Export CSV
            </button>
          </div>
        </>
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
