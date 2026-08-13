// FourDWorkshop — dual real-space (nav) / reciprocal-space (pattern) viewer
// for 4D-STEM datasets (PLAN_4DSTEM #4). Left: a nav-image minimap you
// click/drag on to probe a scan position; right: the diffraction pattern at
// that position (the mean pattern initially), with the current aperture
// drawn as a ring; below: BF/ABF/ADF/custom aperture controls that drive
// POST /fourd/{id}/virtual-detector.
//
// Pattern-panel approach chosen: a plain <canvas> decoding the same
// normalized-uint16 raster the WebGL Stage's LUT shader consumes (the
// `encode_raster_u16` wire format — see ChannelComposite.tsx for the
// existing precedent this follows), NOT a second WebGL Stage. A 4D-STEM
// pattern is one flat raster with no pan/zoom/measure needs of its own, so
// the Stage's GPU pipeline would be pure overhead here.
//
// v1 shipped probe clicks handled entirely on this workshop's own nav
// minimap canvas. v2 (#14) additionally hooks the main Stage's capture
// modes: a "fourdnav" mode (store/viewer.ts) publishes a pixel picked on
// the nav image once it's showing on the Stage, useFourDNavProbeSync.ts
// converts it to a scan position, and FourDProbeMarker.tsx draws the
// on-stage crosshair — the same specnav/useSpectrumProbe.ts pattern the
// EELS/EDS workshops use for their main-Stage spectrum probe.

import { useState } from "react";

import { useFourD } from "../../store/fourd";
import { useViewer } from "../../store/viewer";
import FourDApertureControls from "./fourd/FourDApertureControls";
import FourDNavPanel from "./fourd/FourDNavPanel";
import FourDPatternPanel from "./fourd/FourDPatternPanel";
import FourDScanShape from "./fourd/FourDScanShape";
import { useFourDDatasetRefresh } from "./fourd/useFourDDatasetRefresh";
import { useFourDNavProbeSync } from "./fourd/useFourDNavProbeSync";
import { useFourDPatternFetch } from "./fourd/useFourDPatternFetch";

export default function FourDWorkshop() {
  const datasets = useFourD((s) => s.datasets);
  const selectedId = useFourD((s) => s.selectedId);
  const busyList = useFourD((s) => s.busyList);
  const busyNav = useFourD((s) => s.busyNav);
  const reshapeDataset = useFourD((s) => s.reshapeDataset);
  const status = useFourD((s) => s.status);
  const selectDataset = useFourD((s) => s.selectDataset);
  const closeDataset = useFourD((s) => s.closeDataset);
  const showNavImage = useFourD((s) => s.showNavImage);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const [closing, setClosing] = useState(false);

  // refetches on mount + whenever the tab regains focus/visibility (#14)
  useFourDDatasetRefresh();

  const handleClose = async () => {
    if (!selectedId) return;
    setClosing(true);
    try {
      await closeDataset(selectedId);
    } finally {
      setClosing(false);
    }
  };

  const fourdnavActive = captureMode === "fourdnav";
  const handleToggleProbeOnStage = () => {
    if (fourdnavActive) {
      setCaptureMode("none");
    } else {
      // ensure the nav image is the active Stage image BEFORE arming the
      // capture mode — useFourDNavProbeSync gates on exactly that match
      void showNavImage().then(() => setCaptureMode("fourdnav"));
    }
  };

  // debounced probe → /pattern fetch; a no-op while no dataset is selected
  useFourDPatternFetch(selectedId);
  // main-Stage fourdnav pixel → this workshop's probe (#14 v2)
  useFourDNavProbeSync();

  const meta = datasets.find((d) => d.id === selectedId) ?? null;

  if (datasets.length === 0) {
    return (
      <div className="fvd-ws-empty">
        {busyList ? (
          "Loading 4D-STEM datasets…"
        ) : status ? (
          // a failed /api/fourd list fetch (network error, 500, …) — surface
          // it instead of silently falling through to the generic empty
          // hint, which would otherwise read as "there's nothing to open"
          <p className="fvd-ws-note">{status}</p>
        ) : (
          <>
            <p>
              <strong>No 4D-STEM datasets are open.</strong>
            </p>
            <p>
              Open a .mib (Merlin/Medipix) or HyperSpy-4D (.hspy/.h5) file
              from File ▸ Open — a 4D-STEM file registers here instead of
              the normal image library.
            </p>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="fvd-ws">
      <div className="fvd-ws-row">
        <span className="k">dataset</span>
        <select
          aria-label="4D-STEM dataset"
          value={selectedId ?? ""}
          onChange={(e) => void selectDataset(e.target.value)}
        >
          <option value="" disabled>
            Choose…
          </option>
          {datasets.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.scan_shape.join("×")} scan, {d.det_shape.join("×")} det)
            </option>
          ))}
        </select>
        <button
          className="fvd-btn"
          disabled={!selectedId || busyNav}
          onClick={() => void showNavImage()}
          title="Register (or re-show) the nav image on the main Stage"
        >
          Show nav image
        </button>
        <button
          className={`fvd-btn${fourdnavActive ? " active" : ""}`}
          disabled={!selectedId || busyNav}
          aria-pressed={fourdnavActive}
          onClick={handleToggleProbeOnStage}
          title="Click (or drag) the nav image on the main Stage to move the probe"
        >
          {fourdnavActive ? "Stop probing" : "Probe on Stage"}
        </button>
        <button
          className="fvd-btn danger"
          disabled={!selectedId || closing}
          onClick={() => void handleClose()}
          title="Close this dataset and release its file handle (derived nav/map images stay open)"
        >
          Close
        </button>
      </div>

      {selectedId && (
        <>
          <FourDScanShape
            meta={meta}
            busy={busyNav}
            onApply={(rows, cols) => void reshapeDataset(rows, cols)}
          />
          <div className="fvd-fourd-panels">
            <FourDNavPanel />
            <FourDPatternPanel meta={meta} />
          </div>
          <FourDApertureControls
            detShape={meta ? [meta.det_shape[0], meta.det_shape[1]] : [256, 256]}
            detAxes={meta?.det_axes}
          />
        </>
      )}
    </div>
  );
}
