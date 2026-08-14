// EDS Spectrum-Image explorer — UI parity with
// fermi-viewer/+fermiViewer/+spectrumImage/openSpectrumImageWorkshop.m
//
// Species-connected (Wave 2, SPECTRAL_WORKSPACE_PLAN #11): the window this
// tab tunes, the background model, and the beam energy are no longer local
// state — they are the SELECTED species' `windows.signal` and the image's
// shared `edsSettingsByImage`, the same values Maps extracts its montage
// with. Tuning a window here changes what Maps shows; ticking a species in
// Maps is what makes it available to tune here. `SpeciesChips` is the one
// selector for both surfaces — there is no second element picker.
//
// Layout, top to bottom:
//   Spectrum panel (source bar + uPlot) with zoom bar and integration readout
//   Species chips (selection — the connective tissue with Maps)
//   Integration readout, window controls (lo/hi, presets, lock, background, E0)
//   Element map, tinted by the selected species' colour
//   Pixel / ROI picker and CSV exports
//
// Spectrum acquisition lives in useEdsSpectrumSource; the energy window
// itself now lives in the species store (via useEdsEnergyWindow); the
// pinned-regions lifecycle in useEdsPinnedRegions and the status-bar
// hygiene in useEdsStatusReporter (both split out 2026-08-14); and
// background/beam-energy live in edsSettingsByImage — this component wires
// them together and owns only display state (zoom, log scale).

import { useCallback, useEffect, useMemo, useState } from "react";

import { type Spectrum } from "../../lib/api";
import { useEdsPeakMarkers } from "../../hooks/useEdsPeakMarkers";
import type { EdsMapBackground } from "../../lib/eds/background";
import { integrateWindow } from "../../lib/eds/integrate";
import { frameWindow, type XRange } from "../../lib/spectrum/zoomRange";
import {
  elementMapCsv,
  integrationRegionsCsv,
  spectrumCsv,
} from "../../lib/edsExploreCsv";
import {
  edsSettingsOf,
  selectedSpeciesOf,
  speciesOf,
  useSpecies,
} from "../../store/species";
import { useViewer } from "../../store/viewer";
import SpeciesChips from "../elemental/SpeciesChips";
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
import { useEdsElementMap } from "./useEdsElementMap";
import { useEdsPinnedRegions } from "./useEdsPinnedRegions";
import { useEdsSpectrumSource } from "./useEdsSpectrumSource";
import { useEdsStatusReporter } from "./useEdsStatusReporter";

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
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const specnavPixel = useViewer((s) => s.specnavPixel);

  // Species selection, windows and per-image EDS settings all come from the
  // shared store — Maps and this tab read and write the same slice.
  const byImage = useSpecies((s) => s.byImage);
  const selectedByImage = useSpecies((s) => s.selectedByImage);
  const selectSpeciesStore = useSpecies((s) => s.selectSpecies);
  const edsSettingsByImage = useSpecies((s) => s.edsSettingsByImage);
  const setEdsSettingsStore = useSpecies((s) => s.setEdsSettings);

  const species = speciesOf(byImage, activeId);
  const selected = selectedSpeciesOf({ byImage, selectedByImage }, activeId);
  const edsSettings = edsSettingsOf(edsSettingsByImage, activeId);
  const bgMode = edsSettings.bg;
  const e0Kev = edsSettings.e0Kev;

  // spectrum display
  const [logScale, setLogScale] = useState(false);
  const [spectrumExpanded, setSpectrumExpanded] = useState(false);
  const [showPeaks, setShowPeaks] = useState(true);
  const [xRange, setXRange] = useState<XRange | null>(null);

  const isCube = meta?.kind === "spectrum_image";

  // Status hygiene (guard + teardown retraction) lives in the hook.
  const { stillOpen, reportEds } = useEdsStatusReporter(activeId);
  const { mapResult, mapBusy, recomputeMap } = useEdsElementMap({
    imageId: activeId,
    e0Kev,
    isOpen: stillOpen,
    onStatus: reportEds,
  });

  const energyWindow = useEdsEnergyWindow({
    imageId: activeId,
    species: selected,
    bgMode,
    recomputeMap,
    onStatus: (message) => reportEds(activeId, message),
  });
  const { eLo, eHi } = energyWindow;

  // A new cube brings a new energy axis: the previous zoom doesn't describe
  // it. (The pinned integrations reset inside useEdsPinnedRegions.)
  useEffect(() => {
    setXRange(null);
  }, [activeId]);

  // Nothing selected on this image, but it has species? Pick the first
  // visible one — the same "never face a blank tab" rule Maps' auto-ID
  // follows. A no-op once something is selected, so this is safe to run on
  // every species-list change (window edits included).
  useEffect(() => {
    if (!activeId || selected || species.length === 0) return;
    const next = species.find((s) => s.visible) ?? species[0];
    selectSpeciesStore(activeId, next.id);
  }, [activeId, selected, species, selectSpeciesStore]);

  const { displaySpectrum, label, source, busy, showSum, showRegion } =
    useEdsSpectrumSource({
      imageId: activeId,
      enabled: isCube,
      probePixel: specnavPixel,
      probeActive: captureMode === "specnav",
      isOpen: stillOpen,
      onStatus: reportEds,
      // Window init used to happen here (anchor to the first acquisition
      // element, or a free default). That is now the species store's job —
      // the auto-select effect above runs independently of when the
      // spectrum itself finishes loading.
      onLoaded: () => {},
    });

  const peakMarkers = useEdsPeakMarkers(
    activeId,
    selected?.symbol ?? null,
    displaySpectrum?.energy ?? null,
    showPeaks && isCube,
  );

  const { bounds, minSpan } = useMemo(
    () => energyBounds(displaySpectrum),
    [displaySpectrum],
  );

  // The integral of whatever spectrum is displayed, under the same background
  // model the element map uses — recomputed locally so dragging the window
  // never costs a request. Null with nothing selected: there is no window to
  // integrate over.
  const integration = useMemo(
    () =>
      displaySpectrum && selected
        ? integrateWindow(displaySpectrum, eLo, eHi, bgMode, { e0Kev })
        : null,
    [displaySpectrum, selected, eLo, eHi, bgMode, e0Kev],
  );

  const handleWindowsLive = useCallback(
    (w: { signal: { lo: number; hi: number } }) =>
      energyWindow.live(w.signal.lo, w.signal.hi),
    [energyWindow],
  );
  const handleWindowsCommit = useCallback(
    (w: { signal: { lo: number; hi: number } }) =>
      energyWindow.commit(w.signal.lo, w.signal.hi),
    [energyWindow],
  );

  const handleBgChange = (mode: EdsMapBackground) => {
    if (!activeId) return;
    setEdsSettingsStore(activeId, { bg: mode });
    recomputeMap(eLo, eHi, mode);
  };

  // Pin / restore lifecycle (including restore's species re-creation and
  // background handoff) lives in the hook.
  const pins = useEdsPinnedRegions({
    imageId: activeId,
    integration,
    selected,
    sourceLabel: label,
    bounds,
    minSpan,
    onFrame: setXRange,
  });

  const { libraryBusy, addToLibrary } = useEdsDerivedMap({
    imageId: activeId,
    eLo,
    eHi,
    bg: bgMode,
    e0Kev,
    element: selected?.symbol ?? "(custom)",
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
  // Nothing selected: park the plot's window marker at the left edge rather
  // than feed it a meaningless committed value, and drop the drag handlers —
  // there is no species to write a drag to.
  const plotLo = selected ? eLo : bounds[0];
  const plotHi = selected ? eHi : bounds[0];

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
              eLo={plotLo}
              eHi={plotHi}
              {...(selected
                ? {
                    onDragWindowsLive: handleWindowsLive,
                    onDragWindowsCommit: handleWindowsCommit,
                  }
                : {})}
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

      <div className="fvd-ws-row" style={{ alignItems: "flex-start" }}>
        <span className="k">Species</span>
        <SpeciesChips
          imageId={activeId ?? ""}
          emptyHint="No species yet — identify or add them in the Maps tab."
        />
      </div>

      {/* Unconditional, even with nothing selected: the pinned-regions table
          is how a restore reaches a species the user removed — see
          useEdsPinnedRegions. Its own live-integration row already shows a
          quiet "No channels…" state when `integration` is null (nothing
          selected, or no spectrum yet), matching every other
          window-dependent surface below. */}
      <EdsIntegrationPanel
        current={integration}
        element={selected?.symbol ?? "(custom)"}
        unit={unit}
        source={label}
        regions={pins.regions}
        onAdd={pins.addRegion}
        onRemove={pins.removeRegion}
        onClear={pins.clearRegions}
        onSelect={pins.restoreRegion}
        onExport={() =>
          downloadCsv(integrationRegionsCsv(pins.regions), "eds_integrations.csv")
        }
      />

      {selected ? (
        <>
          <EdsWindowControls
            eLo={eLo}
            eHi={eHi}
            onWindow={energyWindow.commit}
            onZoomToWindow={() =>
              setXRange(frameWindow(eLo, eHi, bounds, minSpan))
            }
            anchorKev={energyWindow.anchorKev}
            onPreset={energyWindow.applyPreset}
            onFit={() => energyWindow.applyFit(displaySpectrum)}
            fitDisabled={!displaySpectrum}
            lineKev={selected.energy}
            locked={energyWindow.locked}
            onLocked={energyWindow.setLocked}
            bgMode={bgMode}
            onBgMode={handleBgChange}
            e0Kev={e0Kev}
            onE0Kev={(v) => {
              if (!activeId) return;
              setEdsSettingsStore(activeId, { e0Kev: v });
              if (v > eHi) recomputeMap(eLo, eHi, "bremsstrahlung", v);
            }}
            showPeaks={showPeaks}
            onShowPeaks={setShowPeaks}
          />

          {mapResult && (
            <EdsElementMap
              result={mapResult}
              element={selected.symbol}
              busy={mapBusy}
              libraryBusy={libraryBusy}
              onAddToLibrary={addToLibrary}
            />
          )}
        </>
      ) : (
        <div className="fvd-ws-empty">
          {species.length === 0
            ? "No species yet — add elements in the Maps tab, then tune their windows here."
            : "Pick a species above to tune its window."}
        </div>
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
