// EELS workshop (handoff §4 Inspector · EELS): spectrum plot with
// power-law background fit, signal-map extraction, edge quantify table.
// Operates on the active image (needs a spectral kind).

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  fetchSpectrum,
  type EelsBackgroundResult,
  type EelsFitResult,
  type EelsQuantResult,
  type ElnesResult,
  type Spectrum,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import EelsAdvanced from "./EelsAdvanced";
import { type EdgeRow } from "./EelsEdgeEditor";
import EelsExploreTab from "./eels/EelsExploreTab";
import { KNOWN_EDGES, type EelsTab } from "./eels/eelsEdges";
import EelsQuantifyPanel from "./eels/EelsQuantifyPanel";
import {
  makeAddEdge,
  makeRunElnes,
  makeRunFit,
  makeRunMap,
  makeRunModelFit,
  makeRunModelFitMaps,
  makeRunQuantify,
  type EelsRunnersCtx,
} from "./eels/eelsRunners";
import { seedFitWindows } from "./eelsWindows";
import type { Rect1 } from "./RegionPicker";
import { useProbeRegionToken } from "./useProbeRegionToken";
import PlotContextSurface from "../plots/PlotContextSurface";
import { useSpectrumProbe } from "./useSpectrumProbe";
import { useEelsQuantMapJob } from "./useEelsQuantMapJob";

export default function EelsWorkshop({
  tab,
}: {
  /** Navigation is owned by the Elemental Analysis shell, which renders the
   *  single tab strip shared with EDS. This component deliberately holds no
   *  tab state — two strips for one workspace is what the merge removed. */
  tab: EelsTab;
}) {
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
  const [region, setRegion] = useState<Rect1 | null>(null);
  const plotHost = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const spectral = meta !== null && meta.kind !== "image";
  const isCube = meta?.kind === "spectrum_image";

  // The probe publishes its own spectrum, so skip exactly that one reload.
  const probeRegion = useProbeRegionToken();

  // load the spectrum whenever the active image / region changes
  useEffect(() => {
    if (!activeId || !spectral) return;
    if (probeRegion.consumeIfMatches(region)) return;
    setSpectrum(null);
    setFit(null);
    setQuant(null);
    setFitResult(null);
    let alive = true;
    fetchSpectrum(activeId, region ?? undefined)
      .then((s) => {
        if (!alive) return;
        setSpectrum(s);
        const w = seedFitWindows(s.energy);
        setBgLo(w.bgLo);
        setBgHi(w.bgHi);
        setSigLo(w.sigLo);
        setSigHi(w.sigHi);
      })
      .catch((e: Error) => setStatus(`EELS: ${e.message}`));
    return () => {
      alive = false;
    };
  }, [activeId, spectral, region, setStatus]);

  // reset the explorer region when switching images
  useEffect(() => {
    probeRegion.clear(); // a token from the previous image is meaningless
    setRegion(null);
  }, [activeId]);

  useSpectrumProbe({
    imageId: activeId,
    pixel: specnavPixel,
    enabled: isCube && captureMode === "specnav",
    onSpectrum: (next, rect) => {
      probeRegion.mark(rect);
      setSpectrum(next);
      setRegion(rect);
      setFit(null);
      setQuant(null);
      setFitResult(null);
    },
    onError: (e) => setStatus(`EELS: ${e.message}`),
  });

  // (re)build the bespoke plot when spectrum, fit, or the active tab's
  // visibility changes. The host div exists only for Quantify / Model-fit —
  // Explore renders the shared SpectrumPlot instead (EelsExploreTab) — so a
  // tab switch away must destroy this instance rather than leave a uPlot
  // bound to a host React has unmounted; a tab switch back must rebuild it.
  const showBespokePlot = tab === "Quantify" || tab === "Model fit";
  useEffect(() => {
    const host = plotHost.current;
    if (!host || !spectrum || !showBespokePlot) return;
    plotRef.current?.destroy();
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    const series: uPlot.Series[] = [
      {},
      { label: "spectrum", stroke: "#8888aa", width: 1 },
    ];
    const data: uPlot.AlignedData = [spectrum.energy, spectrum.counts];
    if (
      fit &&
      fit.background.length === spectrum.energy.length &&
      fit.signal.length === spectrum.energy.length
    ) {
      series.push({ label: "background", stroke: "#d97706", width: 1 });
      series.push({ label: "signal", stroke: accent, width: 1.5 });
      (data as unknown as number[][]).push(fit.background, fit.signal);
    }
    // model-fit overlay (#2): total model + power-law bg + per-edge components,
    // shown on the same energy axis as the summed spectrum
    if (fitResult && fitResult.energy.length === spectrum.energy.length) {
      series.push({ label: "model", stroke: accent, width: 1.5, dash: [4, 2] });
      series.push({
        label: "bg (fit)",
        stroke: "#d97706",
        width: 1,
        dash: [2, 2],
      });
      (data as unknown as number[][]).push(
        fitResult.model,
        fitResult.background,
      );
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
        scales: { x: { time: false } }, // x is eV energy-loss, not a timestamp
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
                if (efLower && !name.toLowerCase().startsWith(efLower))
                  continue;
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
  }, [spectrum, fit, fitResult, showEdges, elementFilter, showBespokePlot]);

  // built fresh each render (these were already plain non-memoized consts,
  // so the factory call sites below are semantically unchanged)
  const runnersCtx: EelsRunnersCtx = {
    activeId,
    spectrum,
    bgLo,
    bgHi,
    sigLo,
    sigHi,
    edges,
    e0Kv,
    betaMrad,
    quantMethod,
    setFit,
    setQuant,
    setFitResult,
    setElnes,
    setEdges,
    setStatus,
  };
  const runFit = makeRunFit(runnersCtx);
  const runMap = makeRunMap(runnersCtx);
  const addEdge = makeAddEdge(runnersCtx);
  const runQuantify = makeRunQuantify(runnersCtx);
  const runModelFit = makeRunModelFit(runnersCtx);
  const runModelFitMaps = makeRunModelFitMaps(runnersCtx);
  const runElnes = makeRunElnes(runnersCtx);

  const quantMapJob = useEelsQuantMapJob({
    activeId, edges, e0Kv, betaMrad, method: quantMethod,
  });

  if (!spectral) {
    return (
      <div className="fvd-ws-empty">
        Select a spectrum or spectrum-image in the library.
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      {showBespokePlot && (
        <PlotContextSurface
          ref={plotHost}
          plotRef={plotRef}
          label="EELS spectrum"
          filename="eels-spectrum.png"
          className="fvd-ws-plot"
        />
      )}
      {tab === "Explore" && (
        <EelsExploreTab
          activeId={activeId}
          spectrum={spectrum}
          fit={fit}
          isCube={isCube}
          bgLo={bgLo}
          bgHi={bgHi}
          sigLo={sigLo}
          sigHi={sigHi}
          setBgLo={setBgLo}
          setBgHi={setBgHi}
          setSigLo={setSigLo}
          setSigHi={setSigHi}
          runFit={runFit}
          runMap={runMap}
          showEdges={showEdges}
          setShowEdges={setShowEdges}
          elementFilter={elementFilter}
          setElementFilter={setElementFilter}
          region={region}
          setRegion={setRegion}
          captureMode={captureMode}
          onToggleLive={() =>
            setCaptureMode(captureMode === "specnav" ? "none" : "specnav")
          }
          specnavPixel={specnavPixel}
        />
      )}
      {(tab === "Quantify" || tab === "Model fit") && (
        <EelsQuantifyPanel
          tab={tab}
          isCube={isCube}
          e0Kv={e0Kv}
          setE0Kv={setE0Kv}
          betaMrad={betaMrad}
          setBetaMrad={setBetaMrad}
          quantMethod={quantMethod}
          setQuantMethod={setQuantMethod}
          addEdge={addEdge}
          edges={edges}
          setEdges={setEdges}
          runQuantify={runQuantify}
          quantMapJob={quantMapJob}
          runModelFit={runModelFit}
          runModelFitMaps={runModelFitMaps}
          runElnes={runElnes}
          fitResult={fitResult}
          elnes={elnes}
          quant={quant}
          meta={meta}
          activeId={activeId}
          setStatus={setStatus}
        />
      )}
      <div hidden={tab !== "Advanced"}>
        <EelsAdvanced
          activeId={activeId}
          isCube={isCube}
          units={spectrum?.units ?? "eV"}
          tabbed
          visible={tab === "Advanced"}
        />
      </div>
    </div>
  );
}
