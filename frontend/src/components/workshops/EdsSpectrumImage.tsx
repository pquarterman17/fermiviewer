// EDS Spectrum-Image explorer — UI parity with
// fermi-viewer/+fermiViewer/+spectrumImage/openSpectrumImageWorkshop.m
//
// Layout, top to bottom:
//   Spectrum panel (source bar + uPlot) with zoom bar and integration readout
//   Element picker (periodic table / dropdown) with that element's colour
//   Window lo/hi spinners (keV) and the background-mode toggle
//   Element map, tinted by the element's colour
//   Pixel / ROI picker and CSV exports
//
// Spectrum acquisition lives in useEdsSpectrumSource; the energy window,
// background model, map extraction and integration stay here because they are
// all views over whichever spectrum that hook has resolved.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { edsLineEnergy, type Spectrum } from "../../lib/api";
import { useEdsPeakMarkers } from "../../hooks/useEdsPeakMarkers";
import { integrateWindow } from "../../lib/eds/integrate";
import {
  makeRegion,
  upsertRegion,
  type IntegrationRegion,
} from "../../lib/spectrum/regions";
import { frameWindow, type XRange } from "../../lib/spectrum/zoomRange";
import {
  elementMapCsv,
  integrationRegionsCsv,
  spectrumCsv,
} from "../../lib/edsExploreCsv";
import { useViewer } from "../../store/viewer";
import EdsElementPicker from "../elemental/ElementPicker";
import EdsElementMap from "./EdsElementMap";
import EdsWindowControls from "./EdsWindowControls";
import EdsIntegrationPanel from "../spectrum/IntegrationPanel";
import EdsSpectrumPanel from "../spectrum/SpectrumPanel";
import EdsSpectrumSourcePicker from "./EdsSpectrumSourcePicker";
import SpectrumPlot from "../spectrum/SpectrumPlot";
import EdsSpectrumZoomBar from "../spectrum/SpectrumZoomBar";
import type { Rect1 } from "./RegionPicker";
import { useEdsDerivedMap } from "./useEdsDerivedMap";
import { useEdsEnergyWindow } from "./useEdsEnergyWindow";
import { type EdsMapBackground, useEdsElementMap } from "./useEdsElementMap";
import { useEdsSpectrumSource } from "./useEdsSpectrumSource";

const HALF_WIN = 0.085; // keV, default half-window (matches MATLAB halfWin)
const MIN_ZOOM_CHANNELS = 6; // narrowest view the wheel / buttons may reach

// ── helpers ───────────────────────────────────────────────────────────

function downloadCsv(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Full energy extent and channel width of a spectrum, for the zoom limits. */
function energyBounds(spec: Spectrum | null) {
  const n = spec?.energy.length ?? 0;
  if (!spec || n < 2) return { bounds: [0, 1] as XRange, minSpan: 0 };
  const bounds: XRange = [spec.energy[0], spec.energy[n - 1]];
  return {
    bounds,
    minSpan: ((bounds[1] - bounds[0]) / (n - 1)) * MIN_ZOOM_CHANNELS,
  };
}

// ── main component ────────────────────────────────────────────────────

export default function EdsSpectrumImage() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const setStatus = useViewer((s) => s.setStatus);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const specnavPixel = useViewer((s) => s.specnavPixel);

  // energy window state (the window itself lives in useEdsEnergyWindow)
  const [bgMode, setBgMode] = useState<EdsMapBackground>("linear");
  const [e0Kev, setE0Kev] = useState(30); // beam energy for bremsstrahlung bg

  // element picker
  const elements: string[] = Array.isArray(meta?.meta?.elements)
    ? (meta.meta.elements as string[])
    : [];
  const [selElem, setSelElem] = useState("(custom)");

  // spectrum display
  const [logScale, setLogScale] = useState(false);
  const [spectrumExpanded, setSpectrumExpanded] = useState(false);
  const [showPeaks, setShowPeaks] = useState(true);
  const [xRange, setXRange] = useState<XRange | null>(null);
  const [regions, setRegions] = useState<IntegrationRegion[]>([]);

  const isCube = meta?.kind === "spectrum_image";

  // Only surface an EDS status/error for an image that is still open. A slow
  // element-map or spectrum request over a big BCF cube can resolve or reject
  // AFTER the user removed the file; without this guard its .then/.catch would
  // strand a message in the global status bar that closeImage already cleared.
  const stillOpen = useCallback(
    (id: string | null): id is string =>
      !!id && !!useViewer.getState().images[id],
    [],
  );
  // Track the last status this explorer wrote so we can retract exactly it on
  // teardown — never a message some other panel put in the bar.
  const lastEdsStatus = useRef<string | null>(null);
  const reportEds = useCallback(
    (id: string | null, msg: string) => {
      if (stillOpen(id)) {
        lastEdsStatus.current = msg;
        setStatus(msg);
      }
    },
    [stillOpen, setStatus],
  );
  const { mapResult, mapBusy, recomputeMap } = useEdsElementMap({
    imageId: activeId,
    e0Kev,
    isOpen: stillOpen,
    onStatus: reportEds,
  });

  const energyWindow = useEdsEnergyWindow({
    bgMode,
    recomputeMap,
    onUnbind: () => setSelElem("(custom)"),
    onStatus: (message) => reportEds(activeId, message),
  });
  const { eLo, eHi } = energyWindow;

  // When the active cube is removed or switched away, clear the status line if
  // it still shows the message this explorer last wrote: an EDS error must not
  // outlive the file it referred to (the reported "errors didn't clear" bug).
  useEffect(() => {
    return () => {
      const st = useViewer.getState();
      if (lastEdsStatus.current && st.status === lastEdsStatus.current) {
        st.setStatus("ready");
      }
    };
  }, [activeId]);

  // A new cube brings a new energy axis and new pixels: neither the previous
  // zoom nor the previous integrations describe it.
  useEffect(() => {
    setXRange(null);
    setRegions([]);
  }, [activeId]);

  const handleElementChange = useCallback(
    (sym: string) => {
      setSelElem(sym);
      if (sym === "(custom)") {
        energyWindow.release(eLo, eHi);
        return;
      }
      const id = activeId;
      edsLineEnergy(sym)
        .then(({ energy_kev, line }) => {
          if (!stillOpen(id)) return;
          energyWindow.anchor(energy_kev, energy_kev - HALF_WIN, energy_kev + HALF_WIN);
          reportEds(id, `EDS: ${sym} ${line}α at ${energy_kev.toFixed(3)} keV`);
        })
        .catch((e: Error) => reportEds(id, `EDS line-energy: ${e.message}`));
    },
    [activeId, eHi, eLo, energyWindow, reportEds, stillOpen],
  );

  const onSpectrumLoaded = useCallback(() => {
    if (elements.length > 0) {
      handleElementChange(elements[0]);
    } else {
      energyWindow.release(0.5, 1.5, "linear");
    }
    // `elements` is derived fresh each render from meta; keying on its content
    // keeps this from re-running the window init on unrelated re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements.join(","), handleElementChange, energyWindow.release]);

  const { displaySpectrum, label, source, busy, showSum, showRegion } =
    useEdsSpectrumSource({
      imageId: activeId,
      enabled: isCube,
      probePixel: specnavPixel,
      probeActive: captureMode === "specnav",
      isOpen: stillOpen,
      onStatus: reportEds,
      onLoaded: onSpectrumLoaded,
    });

  const peakMarkers = useEdsPeakMarkers(
    activeId,
    selElem,
    displaySpectrum?.energy ?? null,
    showPeaks && isCube,
  );

  const { bounds, minSpan } = useMemo(
    () => energyBounds(displaySpectrum),
    [displaySpectrum],
  );

  // The integral of whatever spectrum is displayed, under the same background
  // model the element map uses — recomputed locally so dragging the window
  // never costs a request.
  const integration = useMemo(
    () =>
      displaySpectrum
        ? integrateWindow(displaySpectrum, eLo, eHi, bgMode, { e0Kev })
        : null,
    [displaySpectrum, eLo, eHi, bgMode, e0Kev],
  );

  const handleWindowChange = energyWindow.commit;
  // Mid-drag frames: the overlay and the client-side integration follow the
  // cursor; the element map waits for the commit.
  const handleWindowLive = energyWindow.live;

  const handleBgChange = (mode: EdsMapBackground) => {
    setBgMode(mode);
    recomputeMap(eLo, eHi, mode);
  };

  const addRegion = () => {
    if (!integration) return;
    setRegions((prev) =>
      upsertRegion(prev, makeRegion(integration, selElem, label)),
    );
  };

  // Restoring a pinned region puts its window back and frames it, so the
  // number in the table and the peak on screen are the same measurement.
  const restoreRegion = (region: IntegrationRegion) => {
    setSelElem(region.label.match(/^[A-Z][a-z]?$/) ? region.label : "(custom)");
    setBgMode(region.bg);
    // Restoring a pinned region means "put exactly THIS window back", so it
    // arrives unanchored: a stale line from a previously picked element would
    // otherwise let the lock yank the restored window off its own position.
    energyWindow.release(region.eLo, region.eHi, region.bg);
    setXRange(frameWindow(region.eLo, region.eHi, bounds, minSpan));
  };

  const { libraryBusy, addToLibrary } = useEdsDerivedMap({
    imageId: activeId,
    eLo,
    eHi,
    bg: bgMode,
    e0Kev,
    element: selElem,
    isOpen: stillOpen,
    onStatus: reportEds,
  });

  const handleRoi = (rect: Rect1 | null) => showRegion(rect);

  const exportMapCsv = () => {
    if (mapResult) downloadCsv(elementMapCsv(mapResult), "eds_map.csv");
  };

  const exportSpectrumCsv = () => {
    if (displaySpectrum)
      downloadCsv(spectrumCsv(displaySpectrum), "eds_spectrum.csv");
  };

  if (!isCube) {
    return (
      <div className="fvd-ws-empty">
        Select an EDS spectrum-image cube in the library.
      </div>
    );
  }

  const unit = displaySpectrum?.units || "keV";

  return (
    <div className="fvd-ws">
      <EdsSpectrumPanel
        source={source}
        label={label}
        busy={busy}
        liveActive={captureMode === "specnav"}
        logScale={logScale}
        expanded={spectrumExpanded}
        energyUnit={unit}
        onShowSum={showSum}
        onToggleLive={() =>
          setCaptureMode(captureMode === "specnav" ? "none" : "specnav")
        }
        onShowPicker={() =>
          document
            .getElementById("eds-spectrum-picker")
            ?.scrollIntoView({ block: "nearest" })
        }
        onToggleLog={() => setLogScale((on) => !on)}
        onToggleExpanded={() => setSpectrumExpanded((on) => !on)}
      >
        {displaySpectrum && (
          <>
            <SpectrumPlot
              spec={displaySpectrum}
              label={label}
              eLo={eLo}
              eHi={eHi}
              onDragWindow={handleWindowChange}
              onDragWindowLive={handleWindowLive}
              markers={peakMarkers}
              height={spectrumExpanded ? 360 : 260}
              logScale={logScale}
              onExportCsv={exportSpectrumCsv}
              xRange={xRange}
              minSpan={minSpan}
              onXRangeChange={setXRange}
            />
            <EdsSpectrumZoomBar
              range={xRange}
              bounds={bounds}
              minSpan={minSpan}
              unit={unit}
              onChange={setXRange}
            />
          </>
        )}
      </EdsSpectrumPanel>

      <EdsIntegrationPanel
        current={integration}
        element={selElem}
        unit={unit}
        source={label}
        regions={regions}
        onAdd={addRegion}
        onRemove={(id) => setRegions((prev) => prev.filter((r) => r.id !== id))}
        onClear={() => setRegions([])}
        onSelect={restoreRegion}
        onExport={() =>
          downloadCsv(integrationRegionsCsv(regions), "eds_integrations.csv")
        }
      />

      {/* Element picker — periodic table by default, dropdown via toggle */}
      <div className="fvd-ws-row" style={{ alignItems: "flex-start" }}>
        <span className="k">Element</span>
        <EdsElementPicker
          selected={selElem}
          elements={elements}
          onSelect={handleElementChange}
        />
      </div>

      <EdsWindowControls
        eLo={eLo}
        eHi={eHi}
        onWindow={handleWindowChange}
        onZoomToWindow={() => setXRange(frameWindow(eLo, eHi, bounds, minSpan))}
        anchorKev={energyWindow.anchorKev}
        onPreset={energyWindow.applyPreset}
        onFit={() => energyWindow.applyFit(displaySpectrum)}
        fitDisabled={!displaySpectrum}
        lineKev={energyWindow.lineKev}
        locked={energyWindow.locked}
        onLocked={energyWindow.setLocked}
        bgMode={bgMode}
        onBgMode={handleBgChange}
        e0Kev={e0Kev}
        onE0Kev={(v) => {
          setE0Kev(v);
          if (v > eHi) recomputeMap(eLo, eHi, "bremsstrahlung", v);
        }}
        showPeaks={showPeaks}
        onShowPeaks={setShowPeaks}
      />

      {mapResult && (
        <EdsElementMap
          result={mapResult}
          element={selElem}
          busy={mapBusy}
          libraryBusy={libraryBusy}
          onAddToLibrary={addToLibrary}
        />
      )}

      {activeId && (
        <EdsSpectrumSourcePicker
          imageId={activeId}
          liveActive={isCube && captureMode === "specnav"}
          livePixel={specnavPixel}
          mapReady={!!mapResult}
          spectrumReady={!!displaySpectrum}
          onRegion={handleRoi}
          onToggleLive={() =>
            setCaptureMode(captureMode === "specnav" ? "none" : "specnav")
          }
          onExportMap={exportMapCsv}
          onExportSpectrum={exportSpectrumCsv}
        />
      )}
    </div>
  );
}
