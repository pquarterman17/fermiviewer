// EDS quantification: Cliff–Lorimer or ZAF over the whole field, plus the
// element-fraction profile across the resulting at% maps.
//
// Extracted from EdsWorkshop when the workshop became the modality-agnostic
// Elemental Analysis shell — this is one of the two tabs whose contents are
// genuinely EDS physics and cannot be shared with EELS.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeCompositionProfile,
  edsAutoAssign,
  edsQuantify,
  type CompositionProfileResult,
  type EdsQuantResult,
} from "../../lib/api";
import { sigmaBand } from "../../lib/charts/sigmaBand";
import { useElementColors } from "../../lib/elemental/elementColors";
import { formatPlusMinus } from "../../lib/formatUncertainty";
import { useViewer } from "../../store/viewer";
import PlotContextSurface from "../plots/PlotContextSurface";

/** Per-element at% line plot for the composition profile (#46/A4), each line
 *  wearing a shaded ±1σ band (ANALYSIS_PRESENTATION_PLAN #3) whenever the
 *  route could recompute per-point sigma. Exported (not just used locally)
 *  so it can be tested directly off a `CompositionProfileResult` fixture,
 *  without mounting the whole panel's store/API-dependent parent. */
export function CompProfilePlot({ r }: { r: CompositionProfileResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const colors = useElementColors();

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();

    const n = r.elements.length;
    // Main lines occupy series[1..n] — the SAME indices they always have,
    // so legend-click → series toggling for an element is unaffected by
    // whether bands get appended after them.
    const mainSeries: uPlot.Series[] = r.elements.map((el) => ({
      label: el,
      stroke: colors(el),
      width: 1.5,
      points: { show: false },
    }));

    const sigmaRows = r.atomic_percent_error;
    const bandSeries: uPlot.Series[] = [];
    const bandData: (number | null)[][] = [];
    const bands: uPlot.Band[] = [];
    if (sigmaRows) {
      r.elements.forEach((el, i) => {
        const hiIdx = 1 + n + bandSeries.length;
        const loIdx = hiIdx + 1;
        const cfg = sigmaBand(r.atomic_pct[i], sigmaRows[i], colors(el), hiIdx, loIdx, {
          label: `${el} ±1σ`,
        });
        bandSeries.push(...cfg.series);
        bandData.push(...cfg.data);
        bands.push(cfg.band);
      });
    }

    const series: uPlot.Series[] = [
      { label: `d (${r.unit})` },
      ...mainSeries,
      ...bandSeries,
    ];
    const data = [r.distance, ...r.atomic_pct, ...bandData] as uPlot.AlignedData;

    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 160,
        scales: { x: { time: false } }, // x is distance, not a timestamp
        series,
        bands,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: true },
        cursor: { y: false },
      },
      data,
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
  }, [r, colors]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label="Composition profile"
      filename="eds-composition-profile.png"
      className="fvd-ws-plot"
    />
  );
}

export default function EdsQuantifyPanel({
  elements,
  onElements,
  onResult,
}: {
  elements: string;
  onElements: (value: string) => void;
  /** Lifted so the Maps legend can switch from net counts to at%. */
  onResult: (result: EdsQuantResult | null) => void;
}) {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);

  const [method, setMethod] = useState<"cliff-lorimer" | "zaf">("cliff-lorimer");
  const [thickness, setThickness] = useState("100");
  const [takeOff, setTakeOff] = useState("20");
  const [result, setResult] = useState<EdsQuantResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [autoAssignBusy, setAutoAssignBusy] = useState(false);
  const [comp, setComp] = useState<CompositionProfileResult | null>(null);
  const [compBusy, setCompBusy] = useState(false);

  /** at% maps registered by the last quantify run — the only maps a
   *  *composition* profile can legitimately run across. */
  const quantMaps = (result?.maps ?? [])
    .map((m, i) => ({ m, el: result?.elements[i] ?? "" }))
    .filter((x): x is { m: NonNullable<typeof x.m>; el: string } => x.m != null);

  const runCompProfile = () => {
    if (!activeId || !meta || quantMaps.length === 0) return;
    const s = useViewer.getState();
    const line = [...(s.measures[activeId] ?? [])]
      .reverse()
      .find(
        (m) =>
          (m.kind === "distance" || m.kind === "profile") && m.pts.length === 2,
      );
    if (!line) {
      setStatus(
        "comp profile: draw a Distance or Profile line on the cube first",
      );
      return;
    }
    const w = meta.shape[1] ?? 1;
    const h = meta.shape[0] ?? 1;
    const a = { x: line.pts[0].x * w, y: line.pts[0].y * h };
    const b = { x: line.pts[1].x * w, y: line.pts[1].y * h };
    setCompBusy(true);
    analyzeCompositionProfile(
      activeId,
      quantMaps.map((c) => c.m.id),
      quantMaps.map((c) => c.el),
      a,
      b,
      { width: s.profileWidth },
    )
      .then((r) => {
        setComp(r);
        setStatus(
          `comp profile: ${r.elements.join(", ")} along ${
            Number(r.distance[r.distance.length - 1]?.toPrecision(4)) || 0
          } ${r.unit}`,
        );
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
        onResult(r);
        // blank (absent-element) maps come back null and are skipped so they
        // don't clutter the library strip
        const kept = r.maps.filter(Boolean);
        useViewer.setState((s) => {
          const images = { ...s.images };
          const order = [...s.order];
          for (const m of kept) {
            if (m && !(m.id in images)) order.push(m.id);
            if (m) images[m.id] = m;
          }
          return { images, order };
        });
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

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Elements</span>
        <input
          value={elements}
          style={{ flex: 1 }}
          placeholder="Fe, O, Si"
          onChange={(e) => onElements(e.target.value)}
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
                const unique = [
                  ...new Set(
                    r.assignments
                      .filter((a) => a.candidates.length > 0)
                      .map((a) => a.candidates[0].symbol),
                  ),
                ];
                if (unique.length > 0) {
                  onElements(unique.join(", "));
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
              title={
                m === "zaf"
                  ? "ZAF matrix-corrected quantification"
                  : "Cliff–Lorimer thin-film k-factor"
              }
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
        <button
          className="fvd-btn"
          onClick={run}
          disabled={busy}
          title="Quantify composition and derive at% element maps"
        >
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
      {result && (
        <div className="fvd-ws-note">
          {quantMaps.length} at% map{quantMaps.length === 1 ? "" : "s"} added to
          the library.
        </div>
      )}
      {quantMaps.length > 0 && (
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
    </>
  );
}
