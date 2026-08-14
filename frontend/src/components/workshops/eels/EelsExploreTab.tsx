// EELS Explore tab: the shared SpectrumPlot (signal + pre-edge background
// windows, wheel/drag zoom, edge-onset markers, fit-curve overlay) plus the
// live net/gross/background readout — SPECTRAL_WORKSPACE_PLAN #13. Replaces
// the bespoke read-only uPlot this tab used to own; that plot still renders
// on the Quantify / Model-fit tabs (EelsWorkshop.tsx), where it draws the
// per-edge model-fit component curves this tab has no use for.
//
// The four numeric fields (bgLo/bgHi/sigLo/sigHi) stay the source of truth
// eelsRunners and the Fit/Map buttons read; a drag/nudge/shift-drag formats a
// window edge back into those strings with `fmtNum` (the same precision
// seedFitWindows seeds with), typing sets them directly. `sigWindow`/
// `bgWindow` below are the ordered, numeric views the plot and the
// client-side readout are computed from — ordering a typed "hi < lo" is
// normalised here rather than rewriting the text field mid-keystroke.
//
// SPECTRAL_WORKSPACE_PLAN #11 Wave 3: when a species is selected (via the
// SpeciesChips strip mounted here, or a Maps row click — both write the same
// store selection) these four fields ARE that species' windows, and every
// commit (drag release, preset click, typed blur) writes back through
// `setWindow`. A live drag stays purely local until it commits — see
// `commitWindows` below. With nothing selected this degrades exactly to the
// old spectrum-fraction-seeded, locally-edited behaviour.

import { useEffect, useMemo, useState } from "react";

import type { EelsBackgroundResult, Spectrum } from "../../../lib/api";
import type { PeakMarker } from "../../../lib/eds/peakMarkers";
import { formatCountTick } from "../../../lib/edsSpectrumDisplay";
import { integrateEdge } from "../../../lib/eels/integrate";
import {
  orderWindow,
  splitEdgeLabel,
  type EnergyWindow,
} from "../../../lib/spectrum/species";
import {
  presetWindows,
  type WindowPreset,
} from "../../../lib/spectrum/windowPresets";
import type { XRange } from "../../../lib/spectrum/zoomRange";
import {
  selectedSpeciesOf,
  speciesOf,
  useSpecies,
} from "../../../store/species";
import type { CaptureMode } from "../../../store/viewerTypes";
import SpeciesChips from "../../elemental/SpeciesChips";
import SpectrumPlot, {
  type SpectrumOverlay,
} from "../../spectrum/SpectrumPlot";
import SpectrumZoomBar from "../../spectrum/SpectrumZoomBar";
import WindowPresetBar from "../../spectrum/WindowPresetBar";
import RegionPicker, { type Rect1 } from "../RegionPicker";
import SpectrumNavigationControl from "../SpectrumNavigationControl";
import { fmtNum } from "../eelsWindows";
import { KNOWN_EDGES } from "./eelsEdges";

const MIN_ZOOM_CHANNELS = 6; // narrowest view the wheel / buttons may reach
const OVERLAY_ACCENT = "#a78bfa";

/** The shape a drag/preset/typed edit reports — signal always, background
 *  only when that half of the pair was the one that changed. */
type WindowsPatch = { signal: EnergyWindow; background?: EnergyWindow };

function pm(value: number, error: number): string {
  return `${formatCountTick(value)} ± ${formatCountTick(error)}`;
}

export default function EelsExploreTab({
  activeId,
  spectrum,
  fit,
  isCube,
  bgLo,
  bgHi,
  sigLo,
  sigHi,
  setBgLo,
  setBgHi,
  setSigLo,
  setSigHi,
  runFit,
  runMap,
  showEdges,
  setShowEdges,
  elementFilter,
  setElementFilter,
  region,
  setRegion,
  captureMode,
  onToggleLive,
  specnavPixel,
}: {
  activeId: string | null;
  spectrum: Spectrum | null;
  fit: EelsBackgroundResult | null;
  isCube: boolean;
  bgLo: string;
  bgHi: string;
  sigLo: string;
  sigHi: string;
  setBgLo: (v: string) => void;
  setBgHi: (v: string) => void;
  setSigLo: (v: string) => void;
  setSigHi: (v: string) => void;
  runFit: () => void;
  runMap: () => void;
  showEdges: boolean;
  setShowEdges: (v: boolean) => void;
  elementFilter: string;
  setElementFilter: (v: string) => void;
  region: Rect1 | null;
  setRegion: (r: Rect1 | null) => void;
  captureMode: CaptureMode;
  onToggleLive: () => void;
  specnavPixel: [number, number] | null;
}) {
  const [explore, setExplore] = useState(false);
  const [pickMode, setPickMode] = useState<"region" | "pixel">("region");
  const [xRange, setXRange] = useState<XRange | null>(null);

  const imageId = activeId;
  const byImage = useSpecies((s) => s.byImage);
  const setWindow = useSpecies((s) => s.setWindow);
  const selected = useSpecies((s) => selectedSpeciesOf(s, imageId));
  const species = speciesOf(byImage, imageId);

  // An Explore tab opened straight from a fresh cube (no prior Maps visit,
  // or nothing picked there yet) should not present blank/default windows
  // when real species already exist — mirrors Maps' own "seed once" rule,
  // just for selection instead of the list itself.
  useEffect(() => {
    if (!imageId) return;
    if (useSpecies.getState().selectedByImage[imageId]) return;
    const first = species.find((s) => s.visible);
    if (first) useSpecies.getState().selectSpecies(imageId, first.id);
  }, [imageId, species]);

  const sigWindow = useMemo(
    () => orderWindow({ lo: Number(sigLo) || 0, hi: Number(sigHi) || 0 }),
    [sigLo, sigHi],
  );
  const bgWindow = useMemo(
    () =>
      bgLo !== "" && bgHi !== ""
        ? orderWindow({ lo: Number(bgLo) || 0, hi: Number(bgHi) || 0 })
        : null,
    [bgLo, bgHi],
  );

  // The edited windows ARE the selected species' windows — switching species
  // (a chip here, or a Maps row click, both write the same store selection)
  // swaps what this tab shows and edits. EelsWorkshop's fraction-based
  // `seedFitWindows` default only applies while nothing is selected — see
  // its own guard for the other half of this handshake.
  useEffect(() => {
    if (!selected || selected.modality !== "eels") return;
    setSigLo(fmtNum(selected.windows.signal.lo));
    setSigHi(fmtNum(selected.windows.signal.hi));
    if (selected.windows.background) {
      setBgLo(fmtNum(selected.windows.background.lo));
      setBgHi(fmtNum(selected.windows.background.hi));
    } else {
      setBgLo("");
      setBgHi("");
    }
  }, [selected, setBgLo, setBgHi, setSigLo, setSigHi]);

  const { bounds, minSpan } = useMemo(() => {
    const n = spectrum?.energy.length ?? 0;
    if (!spectrum || n < 2) return { bounds: [0, 1] as XRange, minSpan: 0 };
    const b: XRange = [spectrum.energy[0], spectrum.energy[n - 1]];
    return {
      bounds: b,
      minSpan: ((b[1] - b[0]) / (n - 1)) * MIN_ZOOM_CHANNELS,
    };
  }, [spectrum]);

  // Client-side readout — the same power-law/exponential background model
  // the Fit button and /eels/maps use, summed over the displayed spectrum
  // instead of per pixel. Recomputes on every drag frame; no round trip.
  const readout = useMemo(
    () =>
      spectrum
        ? integrateEdge(spectrum, sigWindow, bgWindow ?? undefined)
        : null,
    [spectrum, sigWindow, bgWindow],
  );

  // Known edge onsets inside the displayed range, filtered by the same
  // element-prefix box the retired canvas overlay used — now real
  // SpectrumPlot markers, so each edge draws in its element's registry
  // colour instead of one uniform red.
  const edgeMarkers = useMemo<PeakMarker[]>(() => {
    if (!showEdges || !spectrum || spectrum.energy.length === 0) return [];
    const lo = spectrum.energy[0];
    const hi = spectrum.energy[spectrum.energy.length - 1];
    const filter = elementFilter.toLowerCase();
    return KNOWN_EDGES.filter(([, ev]) => ev >= lo && ev <= hi)
      .filter(([name]) => !filter || name.toLowerCase().startsWith(filter))
      .map(([name, ev]) => ({
        energyKev: ev,
        label: name,
        symbol: splitEdgeLabel(name).symbol,
        kind: "selected" as const,
      }));
  }, [showEdges, elementFilter, spectrum]);

  // The last Fit result's background/signal curves, drawn over the spectrum
  // exactly like the retired bespoke plot did on this tab.
  const overlays = useMemo<SpectrumOverlay[]>(() => {
    if (
      !fit ||
      !spectrum ||
      fit.background.length !== spectrum.energy.length ||
      fit.signal.length !== spectrum.energy.length
    ) {
      return [];
    }
    return [
      { label: "background", values: fit.background, color: "#d97706" },
      { label: "signal", values: fit.signal, color: OVERLAY_ACCENT },
    ];
  }, [fit, spectrum]);

  // Sync all four fields from whichever window a drag/nudge/shift-drag
  // touched. Idempotent for the untouched window: seedFitWindows already
  // writes fmtNum's canonical form, so re-formatting an unchanged value
  // yields the same string back. LOCAL ONLY — this runs on every live drag
  // frame, and a frame-rate write into the species store is not what
  // "commit" means (see commitWindows below).
  const handleWindowsChange = (w: WindowsPatch) => {
    setSigLo(fmtNum(w.signal.lo));
    setSigHi(fmtNum(w.signal.hi));
    if (w.background) {
      setBgLo(fmtNum(w.background.lo));
      setBgHi(fmtNum(w.background.hi));
    }
  };

  /** A commit — drag release, preset click, or a typed field losing focus.
   *  Updates the fields locally AND, when a species is selected, writes
   *  through to the store: Maps' live net and the EELS map extraction both
   *  key on the species' windows, so this is what makes an Explore edit
   *  show up there immediately (SPECTRAL_WORKSPACE_PLAN #11 Wave 3). With
   *  nothing selected (no species yet, or a plain non-species workflow) it
   *  degrades to exactly the old local-only behaviour. */
  const commitWindows = (w: WindowsPatch) => {
    handleWindowsChange(w);
    if (imageId && selected) {
      setWindow(imageId, selected.id, "signal", w.signal);
      if (w.background) setWindow(imageId, selected.id, "background", w.background);
    }
  };

  /** The four text fields have no per-keystroke commit — a half-typed
   *  number is not a window edit — so typing commits on blur, from
   *  whatever the fields currently parse to (sigWindow/bgWindow already
   *  track bgLo/bgHi/sigLo/sigHi, ordered). */
  const commitTyped = () =>
    commitWindows({ signal: sigWindow, background: bgWindow ?? undefined });

  /** A width preset is measured from the ONSET, which for an EELS signal
   *  window is its lower bound: the edge is a step, so the window's start is
   *  the physical landmark and only its extent is a choice. Re-placing the
   *  pre-edge background under it comes free from `eelsDefaultWindows` — the
   *  same placement a fresh species is born with. */
  const applyPreset = (preset: WindowPreset) =>
    commitWindows(presetWindows("eels", sigWindow.lo, preset));

  return (
    <>
      {imageId && (
        <SpeciesChips
          imageId={imageId}
          emptyHint="No species yet — identify or add elements from the Maps tab."
        />
      )}
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
        {region && (
          <span className="k">
            {region[0] === region[2] && region[1] === region[3]
              ? `px [${region[0]},${region[1]}]`
              : `[${region[0]},${region[1]}]–[${region[2]},${region[3]}]`}
          </span>
        )}
      </div>
      {isCube && (
        <SpectrumNavigationControl
          active={captureMode === "specnav"}
          pixel={specnavPixel}
          onToggle={onToggleLive}
        />
      )}
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
      {spectrum && (
        <>
          <SpectrumPlot
            spec={spectrum}
            label="EELS spectrum"
            eLo={sigWindow.lo}
            eHi={sigWindow.hi}
            background={bgWindow}
            onDragWindowsLive={handleWindowsChange}
            onDragWindowsCommit={commitWindows}
            markers={edgeMarkers}
            overlays={overlays}
            xRange={xRange}
            minSpan={minSpan}
            onXRangeChange={setXRange}
          />
          <SpectrumZoomBar
            range={xRange}
            bounds={bounds}
            minSpan={minSpan}
            unit={spectrum.units}
            onChange={setXRange}
          />
        </>
      )}
      {readout ? (
        <div className="fvd-ws-note">
          Net {pm(readout.net, readout.sigma)} · gross{" "}
          {formatCountTick(readout.gross)} · bg{" "}
          {formatCountTick(readout.background_counts)} · {readout.channels} ch
          {readout.note && <> · {readout.note}</>}
        </div>
      ) : (
        <div className="fvd-ws-note">No channels in the signal window.</div>
      )}
      <div className="fvd-ws-row">
        <span className="k">Background</span>
        <input value={bgLo} onChange={(e) => setBgLo(e.target.value)} onBlur={commitTyped} />
        <span>–</span>
        <input value={bgHi} onChange={(e) => setBgHi(e.target.value)} onBlur={commitTyped} />
        <span className="k">{spectrum?.units ?? "eV"}</span>
        <button
          className="fvd-btn"
          onClick={runFit}
          title="Fit the power-law background over the selected window"
        >
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
        <input value={sigLo} onChange={(e) => setSigLo(e.target.value)} onBlur={commitTyped} />
        <span>–</span>
        <input value={sigHi} onChange={(e) => setSigHi(e.target.value)} onBlur={commitTyped} />
        <span className="k">{spectrum?.units ?? "eV"}</span>
        <button
          className="fvd-btn"
          onClick={runMap}
          disabled={!isCube}
          title="Extract a signal-intensity map over the signal window (SI cube)"
        >
          Map
        </button>
      </div>

      <WindowPresetBar
        modality="eels"
        anchorEnergy={sigWindow.lo}
        width={sigWindow.hi - sigWindow.lo}
        onPreset={applyPreset}
      />
    </>
  );
}
