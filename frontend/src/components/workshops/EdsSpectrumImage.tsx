// EDS Spectrum-Image explorer — UI parity with
// fermi-viewer/+fermiViewer/+spectrumImage/openSpectrumImageWorkshop.m
//
// Controls (left-to-right, MATLAB order):
//   Element dropdown → snaps energy window to the element's principal line
//   Window lo/hi spinners (keV)
//   Background-mode toggle (linear / none)
//   Live spectrum plot (uPlot) with draggable window patch
//   Sum spectrum button
//   Pixel-click / ROI-drag → spectrum (via RegionPicker)
//   Element-map CSV export / spectrum CSV export

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  edsElementMap,
  edsLineEnergy,
  fetchSpectrum,
  type EdsElementMapResult,
  type Spectrum,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import SpectrumPlot from "./EdsSpectrumPlot";
import RegionPicker, { type Rect1 } from "./RegionPicker";
import SpectrumNavigationControl from "./SpectrumNavigationControl";
import { useSpectrumProbe } from "./useSpectrumProbe";

const HALF_WIN = 0.085; // keV, default half-window (matches MATLAB halfWin)

type BgMode = "linear" | "none" | "bremsstrahlung";

// ── element-map canvas ────────────────────────────────────────────────

function MapCanvas({ result }: { result: EdsElementMapResult }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [h, w] = result.shape;
  // iterative max — Math.max(...flat) spreads every element as a call
  // argument and throws a RangeError once the map crosses ~65k px
  const vmax = useMemo(() => {
    let m = 1;
    for (const row of result.map) {
      for (const v of row) {
        if (v > m) m = v;
      }
    }
    return m;
  }, [result.map]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    cv.width = w;
    cv.height = h;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(w, h);
    for (let i = 0; i < h * w; i++) {
      const row = Math.floor(i / w);
      const col = i % w;
      const v = Math.min(255, Math.round((result.map[row][col] / vmax) * 255));
      // hot colormap approximation: black→red→yellow→white
      const r = Math.min(255, v * 3);
      const g = Math.max(0, Math.min(255, v * 3 - 255));
      const b = Math.max(0, Math.min(255, v * 3 - 510));
      img.data[i * 4] = r;
      img.data[i * 4 + 1] = g;
      img.data[i * 4 + 2] = b;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [result, h, w, vmax]);

  return (
    <canvas
      ref={canvasRef}
      title={`${result.e_lo.toFixed(3)}–${result.e_hi.toFixed(3)} keV (${result.bg} bg)`}
      style={{ width: "100%", imageRendering: "pixelated", display: "block" }}
    />
  );
}

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

  // energy window state
  const [eLo, setELo] = useState(0.5);
  const [eHi, setEHi] = useState(1.5);
  const [bgMode, setBgMode] = useState<BgMode>("linear");
  const [e0Kev, setE0Kev] = useState(30); // beam energy for bremsstrahlung bg

  // element picker
  const elements: string[] = Array.isArray(meta?.meta?.elements)
    ? (meta.meta.elements as string[])
    : [];
  const [selElem, setSelElem] = useState("(custom)");

  // spectrum display
  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [specLabel, setSpecLabel] = useState("Sum spectrum");

  // map
  const [mapResult, setMapResult] = useState<EdsElementMapResult | null>(null);
  const [mapBusy, setMapBusy] = useState(false);

  // ROI
  const [roi, setRoi] = useState<Rect1 | null>(null);

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

  // recompute map on window/bg change
  const recomputeMap = useCallback(
    (lo: number, hi: number, bg: BgMode) => {
      const id = activeId;
      if (!id) return;
      setMapBusy(true);
      edsElementMap(id, lo, hi, {
        bg,
        e0Kev: bg === "bremsstrahlung" ? e0Kev : undefined,
      })
        .then((r) => {
          if (!stillOpen(id)) return; // image removed mid-request; drop result
          setMapResult(r);
          reportEds(
            id,
            `EDS map: ${lo.toFixed(3)}–${hi.toFixed(3)} keV (${bg}), ` +
              `${r.total_counts.toFixed(0)} counts`,
          );
        })
        .catch((e: Error) => reportEds(id, `EDS map: ${e.message}`))
        .finally(() => setMapBusy(false));
    },
    [activeId, reportEds, stillOpen, e0Kev],
  );

  // fetch sum spectrum on mount / cube change
  useEffect(() => {
    if (!activeId || !isCube) return;
    const id = activeId;
    let cancelled = false;
    fetchSpectrum(id)
      .then((s) => {
        if (cancelled || !stillOpen(id)) return;
        setSpectrum(s);
        setSpecLabel("Sum spectrum");
        // initialise window to first element or default
        if (elements.length > 0) {
          handleElementChange(elements[0]);
        } else {
          const lo = 0.5;
          const hi = 1.5;
          setELo(lo);
          setEHi(hi);
          recomputeMap(lo, hi, "linear");
        }
      })
      .catch((e: Error) => reportEds(id, `EDS spectrum: ${e.message}`));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, isCube]);

  useSpectrumProbe({
    imageId: activeId,
    pixel: specnavPixel,
    enabled: isCube && captureMode === "specnav",
    onSpectrum: (next, rect) => {
      setSpectrum(next);
      setSpecLabel(`px [${rect[0]}, ${rect[1]}]`);
      setRoi(rect);
    },
    onError: (e) => reportEds(activeId, `EDS spectrum: ${e.message}`),
  });

  const handleElementChange = (sym: string) => {
    setSelElem(sym);
    if (sym === "(custom)") return;
    const id = activeId;
    edsLineEnergy(sym)
      .then(({ energy_kev, line }) => {
        if (!stillOpen(id)) return;
        const lo = energy_kev - HALF_WIN;
        const hi = energy_kev + HALF_WIN;
        setELo(lo);
        setEHi(hi);
        recomputeMap(lo, hi, bgMode);
        reportEds(id, `EDS: ${sym} ${line}α at ${energy_kev.toFixed(3)} keV`);
      })
      .catch((e: Error) => reportEds(id, `EDS line-energy: ${e.message}`));
  };

  const handleWindowChange = (lo: number, hi: number) => {
    const lo2 = Math.min(lo, hi);
    const hi2 = Math.max(lo, hi);
    setELo(lo2);
    setEHi(hi2);
    setSelElem("(custom)");
    recomputeMap(lo2, hi2, bgMode);
    // refresh window patch on spectrum
    const id = activeId;
    if (id) {
      fetchSpectrum(id, roi ?? undefined)
        .then((s) => {
          if (stillOpen(id)) setSpectrum(s);
        })
        .catch((e: Error) => reportEds(id, `EDS spectrum: ${e.message}`));
    }
  };

  const handleBgChange = (mode: BgMode) => {
    setBgMode(mode);
    recomputeMap(eLo, eHi, mode);
  };

  const handleRoi = (rect: Rect1 | null) => {
    setRoi(rect);
    const id = activeId;
    if (!id) return;
    fetchSpectrum(id, rect ?? undefined)
      .then((s) => {
        if (!stillOpen(id)) return;
        setSpectrum(s);
        setSpecLabel(
          rect
            ? `ROI [${rect[0]}:${rect[2]}, ${rect[1]}:${rect[3]}]`
            : "Sum spectrum",
        );
      })
      .catch((e: Error) => reportEds(id, `EDS spectrum: ${e.message}`));
  };

  const handleShowSum = () => {
    const id = activeId;
    if (!id) return;
    setRoi(null);
    fetchSpectrum(id)
      .then((s) => {
        if (!stillOpen(id)) return;
        setSpectrum(s);
        setSpecLabel("Sum spectrum");
      })
      .catch((e: Error) => reportEds(id, `EDS sum: ${e.message}`));
  };

  const exportMapCsv = () => {
    if (!mapResult) return;
    const rows = mapResult.map
      .map((row) => row.map((v) => v.toFixed(4)).join(","))
      .join("\n");
    const header = `# EDS element map ${mapResult.e_lo.toFixed(3)}-${mapResult.e_hi.toFixed(3)} keV (${mapResult.bg} bg)\n`;
    downloadCsv(header + rows, "eds_map.csv");
  };

  const exportSpectrumCsv = () => {
    if (!spectrum) return;
    const header = `energy_${spectrum.units},counts\n`;
    const rows = spectrum.energy
      .map((e, i) => `${e.toFixed(6)},${spectrum.counts[i].toFixed(6)}`)
      .join("\n");
    downloadCsv(header + rows, "eds_spectrum.csv");
  };

  if (!isCube) {
    return (
      <div className="fvd-ws-empty">
        Select an EDS spectrum-image cube in the library.
      </div>
    );
  }

  const ddItems = ["(custom)", ...elements];

  return (
    <div className="fvd-ws">
      {/* Element picker */}
      <div className="fvd-ws-row">
        <span className="k">Element</span>
        <select
          value={selElem}
          style={{ flex: 1 }}
          onChange={(e) => handleElementChange(e.target.value)}
        >
          {ddItems.map((el) => (
            <option key={el} value={el}>
              {el}
            </option>
          ))}
        </select>
      </div>

      {/* Energy window */}
      <div className="fvd-ws-row">
        <span className="k">Window (keV)</span>
        <input
          type="number"
          step={0.05}
          value={eLo.toFixed(3)}
          style={{ width: 72 }}
          onChange={(e) => handleWindowChange(Number(e.target.value), eHi)}
          title="Energy window low (keV)"
        />
        <span style={{ padding: "0 4px" }}>–</span>
        <input
          type="number"
          step={0.05}
          value={eHi.toFixed(3)}
          style={{ width: 72 }}
          onChange={(e) => handleWindowChange(eLo, Number(e.target.value))}
          title="Energy window high (keV)"
        />
      </div>

      {/* Background mode toggle */}
      <div className="fvd-ws-row">
        <span className="k">Background</span>
        <div className="fvd-seg">
          {(["linear", "none", "bremsstrahlung"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${bgMode === m ? " active" : ""}`}
              title={
                m === "bremsstrahlung"
                  ? "Physical Kramers continuum (per-pixel amplitude fit)"
                  : `${m} background`
              }
              onClick={() => handleBgChange(m)}
            >
              {m === "bremsstrahlung" ? "brems" : m}
            </button>
          ))}
        </div>
        {bgMode === "bremsstrahlung" && (
          <>
            <span className="k">E₀ (keV)</span>
            <input
              type="number"
              value={e0Kev}
              style={{ width: 56 }}
              title="Beam energy — Duane–Hunt continuum cutoff"
              onChange={(e) => {
                const v = Number(e.target.value) || 0;
                setE0Kev(v);
                if (v > eHi) recomputeMap(eLo, eHi, "bremsstrahlung");
              }}
            />
          </>
        )}
        <button
          className="fvd-btn"
          style={{ marginLeft: "auto" }}
          onClick={handleShowSum}
          title="Show sum spectrum of the whole cube"
        >
          Sum spectrum
        </button>
      </div>

      {/* Live spectrum plot (drag to set window) */}
      {spectrum && (
        <SpectrumPlot
          spec={spectrum}
          label={specLabel}
          eLo={eLo}
          eHi={eHi}
          onDragWindow={handleWindowChange}
        />
      )}

      {/* Element map canvas */}
      <div className="fvd-ws-row">
        <span className="k">
          {mapBusy
            ? "Computing…"
            : mapResult
              ? `Map (${mapResult.e_lo.toFixed(3)}–${mapResult.e_hi.toFixed(3)} keV)`
              : "Map"}
        </span>
      </div>
      {mapResult && <MapCanvas result={mapResult} />}

      {/* ROI picker — drag on the element map preview */}
      {activeId && (
        <>
          <div className="fvd-ws-row">
            <span className="k">
              Click pixel / drag ROI on the preview to select spectrum source:
            </span>
          </div>
          <RegionPicker id={activeId} onRegion={handleRoi} />
          {isCube && (
            <SpectrumNavigationControl
              active={captureMode === "specnav"}
              pixel={specnavPixel}
              onToggle={() =>
                setCaptureMode(captureMode === "specnav" ? "none" : "specnav")
              }
            />
          )}
        </>
      )}

      {/* Export */}
      <div className="fvd-ws-row">
        <button
          className="fvd-btn"
          disabled={!mapResult}
          onClick={exportMapCsv}
          title="Export the current element map as CSV"
        >
          Export map CSV
        </button>
        <button
          className="fvd-btn"
          disabled={!spectrum}
          onClick={exportSpectrumCsv}
          title="Export the displayed spectrum as CSV"
        >
          Export spectrum CSV
        </button>
      </div>
    </div>
  );
}
