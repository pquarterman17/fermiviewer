// EELS workshop (handoff §4 Inspector · EELS): spectrum plot with
// power-law background fit, signal-map extraction, edge quantify table.
// Operates on the active image (needs a spectral kind).

import { useEffect, useState } from "react";

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
import EelsFitOverlayPlot from "./eels/EelsFitOverlayPlot";
import { type EelsTab } from "./eels/eelsEdges";
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

  // The bespoke plot (EelsFitOverlayPlot) only mounts for Quantify /
  // Model-fit — Explore renders the shared SpectrumPlot instead
  // (EelsExploreTab) — so a tab switch away must unmount it rather than
  // leave a uPlot bound to a host React has unmounted; a tab switch back
  // remounts it.
  const showBespokePlot = tab === "Quantify" || tab === "Model fit";

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
      {showBespokePlot && spectrum && (
        <EelsFitOverlayPlot
          spectrum={spectrum}
          fit={fit}
          fitResult={fitResult}
          showEdges={showEdges}
          elementFilter={elementFilter}
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
