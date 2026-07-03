// EDS workshop (handoff §4 Inspector · EDS): element list, Cliff-Lorimer
// or ZAF quantification; derived at% maps register into the library.
// For SI cubes, the EDS Spectrum-Image explorer (EdsSpectrumImage) is
// shown as a collapsible section above the quantification controls.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeCompositionProfile,
  edsAutoAssign,
  edsQuantify,
  type CompositionProfileResult,
  type EdsQuantResult,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import { formatPlusMinus } from "../../lib/formatUncertainty";
import EdsComposite, { EDS_PALETTE, type Channel } from "./EdsComposite";
import EdsModelFit from "./EdsModelFit";
import EdsSpectrumImage from "./EdsSpectrumImage";

/** Per-element at% line plot for the composition profile (#46/A4). */
function CompProfilePlot({ r }: { r: CompositionProfileResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    const series: uPlot.Series[] = [
      { label: `d (${r.unit})` },
      ...r.elements.map((el, i) => ({
        label: el,
        stroke: EDS_PALETTE[i % EDS_PALETTE.length],
        width: 1.5,
        points: { show: false },
      })),
    ];
    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 160,
        scales: { x: { time: false } }, // x is distance, not a timestamp
        series,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: true },
        cursor: { y: false },
      },
      [r.distance, ...r.atomic_pct] as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 160 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [r]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}

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
  const [autoAssignBusy, setAutoAssignBusy] = useState(false);
  const [comp, setComp] = useState<CompositionProfileResult | null>(null);
  const [compBusy, setCompBusy] = useState(false);

  const isCube = meta?.kind === "spectrum_image";

  // #46 (A4): element-fraction line profile across the quantified maps,
  // along the most recent distance/profile measure drawn on the cube
  const runCompProfile = () => {
    if (!activeId || !meta || channels.length === 0) return;
    const s = useViewer.getState();
    const line = [...(s.measures[activeId] ?? [])]
      .reverse()
      .find(
        (m) =>
          (m.kind === "distance" || m.kind === "profile") &&
          m.pts.length === 2,
      );
    if (!line) {
      setStatus("comp profile: draw a Distance or Profile line on the cube first");
      return;
    }
    const w = meta.shape[1] ?? 1;
    const h = meta.shape[0] ?? 1;
    const a = { x: line.pts[0].x * w, y: line.pts[0].y * h };
    const b = { x: line.pts[1].x * w, y: line.pts[1].y * h };
    setCompBusy(true);
    analyzeCompositionProfile(
      channels.map((c) => c.id),
      channels.map((c) => c.el),
      a,
      b,
      { width: s.profileWidth },
    )
      .then((r) => {
        setComp(r);
        setStatus(`comp profile: ${r.elements.join(", ")} along ${
          Number(r.distance[r.distance.length - 1]?.toPrecision(4)) || 0
        } ${r.unit}`);
      })
      .catch((e: Error) => setStatus(`comp profile: ${e.message}`))
      .finally(() => setCompBusy(false));
  };

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
        // surface derived at% maps in the library — blank (absent-element)
        // maps come back null and are skipped so they don't clutter the strip
        const kept = r.maps
          .map((m, i) => ({ m, el: r.elements[i], i }))
          .filter((x): x is { m: (typeof r.maps)[number] & object; el: string; i: number } =>
            x.m != null,
          );
        useViewer.setState((s) => {
          const images = { ...s.images };
          const order = [...s.order];
          for (const { m } of kept) {
            if (!(m.id in images)) order.push(m.id);
            images[m.id] = m;
          }
          return { images, order };
        });
        setChannels(
          kept.map(({ m, el, i }) => ({
            id: m.id,
            el,
            color: EDS_PALETTE[i % EDS_PALETTE.length],
            intensity: 1,
            visible: true,
          })),
        );
        const nSkipped = r.maps.length - kept.length;
        setStatus(
          `EDS: quantified ${r.elements.join(", ")}` +
            (nSkipped > 0
              ? ` · ${nSkipped} blank map${nSkipped > 1 ? "s" : ""} skipped`
              : ""),
        );
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
      {/* SI explorer — always shown first for spectrum_image cubes */}
      <details open>
        <summary style={{ cursor: "pointer", padding: "4px 0", fontWeight: 500 }}>
          Spectrum-Image Explorer
        </summary>
        <EdsSpectrumImage />
      </details>
      <hr style={{ margin: "6px 0", border: "none", borderTop: "1px solid var(--border)" }} />

      <div className="fvd-ws-row">
        <span className="k">Elements</span>
        <input
          value={elements}
          style={{ flex: 1 }}
          placeholder="Fe, O, Si"
          onChange={(e) => setElements(e.target.value)}
        />
        <button
          className="fvd-btn"
          title="Auto-detect element lines from sum spectrum peaks (#44)"
          disabled={autoAssignBusy || !activeId}
          onClick={() => {
            if (!activeId) return;
            setAutoAssignBusy(true);
            edsAutoAssign(activeId)
              .then((r) => {
                const syms = r.assignments
                  .filter((a) => a.candidates.length > 0)
                  .map((a) => a.candidates[0].symbol);
                const unique = [...new Set(syms)];
                if (unique.length > 0) {
                  setElements(unique.join(", "));
                  setStatus(`EDS auto-assign: ${unique.join(", ")}`);
                } else {
                  setStatus("EDS auto-assign: no peaks detected above threshold");
                }
              })
              .catch((e: Error) => setStatus(`auto-assign: ${e.message}`))
              .finally(() => setAutoAssignBusy(false));
          }}
        >
          {autoAssignBusy ? "…" : "Auto-assign"}
        </button>
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
              <th>at% ± 1σ</th>
              <th>wt% ± 1σ</th>
              <th>k</th>
            </tr>
          </thead>
          <tbody>
            {result.elements.map((el, i) => (
              <tr key={el}>
                <td>{el}</td>
                <td>{result.lines[i]}</td>
                <td>
                  {formatPlusMinus(
                    result.mean_atomic_pct[i],
                    result.mean_atomic_pct_error?.[i] ?? 0,
                    2,
                  )}
                </td>
                <td>
                  {formatPlusMinus(
                    result.mean_weight_pct[i],
                    result.mean_weight_pct_error?.[i] ?? 0,
                    2,
                  )}
                </td>
                <td>{result.k_factors[i].toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {result &&
        (() => {
          const added = result.maps.filter(Boolean).length;
          return (
            <div className="fvd-ws-note">
              {added} at% map{added === 1 ? "" : "s"} added to the library.
            </div>
          );
        })()}
      {channels.length > 0 && (
        <div className="fvd-ws-row">
          <button
            className="fvd-btn"
            disabled={compBusy}
            title="Element-fraction line profile across the at% maps, along the last Distance/Profile measure (A4)"
            onClick={runCompProfile}
          >
            {compBusy ? "Profiling…" : "Comp Profile"}
          </button>
          {comp && (
            <button
              className="fvd-icon-btn"
              title="Close composition profile"
              onClick={() => setComp(null)}
            >
              ✕
            </button>
          )}
        </div>
      )}
      {comp && <CompProfilePlot r={comp} />}

      <details style={{ marginTop: 6 }}>
        <summary style={{ cursor: "pointer", padding: "4px 0", fontWeight: 500 }}>
          Model fit (continuum + peak deconvolution)
        </summary>
        <EdsModelFit activeId={activeId} elements={elements} />
      </details>

      <EdsComposite channels={channels} onChange={setChannels} />
    </div>
  );
}
