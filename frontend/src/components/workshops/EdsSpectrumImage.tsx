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

import { useCallback, useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  edsElementMap,
  edsLineEnergy,
  fetchSpectrum,
  type EdsElementMapResult,
  type Spectrum,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import RegionPicker, { type Rect1 } from "./RegionPicker";

const HALF_WIN = 0.085; // keV, default half-window (matches MATLAB halfWin)

type BgMode = "linear" | "none" | "bremsstrahlung";

// ── spectrum uPlot ────────────────────────────────────────────────────

function SpectrumPlot({
  spec,
  label,
  eLo,
  eHi,
  onDragWindow,
}: {
  spec: Spectrum;
  label: string;
  eLo: number;
  eHi: number;
  onDragWindow: (lo: number, hi: number) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const dragRef = useRef<number | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || spec.energy.length === 0) return;
    plotRef.current?.destroy();

    const u = new uPlot(
      {
        width: host.clientWidth || 320,
        height: 160,
        title: label,
        // energy axis is keV, not a timestamp — uPlot defaults x to a time
        // scale, which renders small keV values as clock/date labels
        scales: { x: { time: false } },
        series: [
          { label: `E (${spec.units})` },
          {
            label: "Counts",
            stroke: "#333",
            width: 1,
            points: { show: false },
          },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u2) => {
              const ctx = u2.ctx;
              const x0 = u2.valToPos(eLo, "x");
              const x1 = u2.valToPos(eHi, "x");
              const y0 = u2.bbox.top;
              const y1 = u2.bbox.top + u2.bbox.height;
              ctx.save();
              ctx.globalAlpha = 0.15;
              ctx.fillStyle = "#3b82f6";
              ctx.fillRect(
                x0 + u2.bbox.left,
                y0,
                x1 - x0,
                y1 - y0,
              );
              ctx.globalAlpha = 1;
              ctx.strokeStyle = "#2563eb";
              ctx.lineWidth = 1.5;
              ctx.beginPath();
              ctx.moveTo(x0 + u2.bbox.left, y0);
              ctx.lineTo(x0 + u2.bbox.left, y1);
              ctx.moveTo(x1 + u2.bbox.left, y0);
              ctx.lineTo(x1 + u2.bbox.left, y1);
              ctx.stroke();
              ctx.restore();
            },
          ],
        },
      } satisfies uPlot.Options,
      [
        spec.energy as unknown as number[],
        spec.counts as unknown as number[],
      ] as uPlot.AlignedData,
      host,
    );
    plotRef.current = u;

    // drag-to-set-window on the over element — matches MATLAB onSpecDown/Up
    const canvas = host.querySelector("canvas");
    if (!canvas) return;

    const onDown = (e: MouseEvent) => {
      dragRef.current = u.posToVal(e.offsetX - u.bbox.left, "x");
    };
    const onUp = (e: MouseEvent) => {
      if (dragRef.current == null) return;
      const x1 = u.posToVal(e.offsetX - u.bbox.left, "x");
      const lo = Math.min(dragRef.current, x1);
      const hi = Math.max(dragRef.current, x1);
      if (hi - lo > 1e-6) onDragWindow(lo, hi);
      dragRef.current = null;
    };
    canvas.addEventListener("mousedown", onDown);
    canvas.addEventListener("mouseup", onUp);

    const ro = new ResizeObserver(() => {
      if (u && host.clientWidth > 0)
        u.setSize({ width: host.clientWidth, height: 160 });
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      canvas.removeEventListener("mousedown", onDown);
      canvas.removeEventListener("mouseup", onUp);
      u.destroy();
      plotRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, label, eLo, eHi]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}

// ── element-map canvas ────────────────────────────────────────────────

function MapCanvas({ result }: { result: EdsElementMapResult }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [h, w] = result.shape;
  const flat = result.map.flat();
  const vmax = Math.max(...flat, 1);

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

  // recompute map on window/bg change
  const recomputeMap = useCallback(
    (lo: number, hi: number, bg: BgMode) => {
      if (!activeId) return;
      setMapBusy(true);
      edsElementMap(activeId, lo, hi, {
        bg,
        e0Kev: bg === "bremsstrahlung" ? e0Kev : undefined,
      })
        .then((r) => {
          setMapResult(r);
          setStatus(
            `EDS map: ${lo.toFixed(3)}–${hi.toFixed(3)} keV (${bg}), ` +
              `${r.total_counts.toFixed(0)} counts`,
          );
        })
        .catch((e: Error) => setStatus(`EDS map: ${e.message}`))
        .finally(() => setMapBusy(false));
    },
    [activeId, setStatus, e0Kev],
  );

  // fetch sum spectrum on mount / cube change
  useEffect(() => {
    if (!activeId || !isCube) return;
    fetchSpectrum(activeId).then((s) => {
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
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, isCube]);

  // #10 specnav: a pixel picked on the MAIN stage drives the spectrum (1×1 ROI)
  useEffect(() => {
    if (!isCube || !specnavPixel || !activeId) return;
    const [r, c] = specnavPixel;
    const rect: Rect1 = [r, c, r, c];
    fetchSpectrum(activeId, rect)
      .then((s) => {
        setSpectrum(s);
        setSpecLabel(`px [${r}, ${c}]`);
        setRoi(rect);
      })
      .catch((e: Error) => setStatus(`EDS spectrum: ${e.message}`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [specnavPixel, isCube, activeId]);

  // turn specnav off when the workshop unmounts (don't leave the stage armed)
  useEffect(
    () => () => {
      if (useViewer.getState().captureMode === "specnav")
        useViewer.getState().setCaptureMode("none");
    },
    [],
  );

  const handleElementChange = (sym: string) => {
    setSelElem(sym);
    if (sym === "(custom)") return;
    edsLineEnergy(sym)
      .then(({ energy_kev, line }) => {
        const lo = energy_kev - HALF_WIN;
        const hi = energy_kev + HALF_WIN;
        setELo(lo);
        setEHi(hi);
        recomputeMap(lo, hi, bgMode);
        setStatus(`EDS: ${sym} ${line}α at ${energy_kev.toFixed(3)} keV`);
      })
      .catch((e: Error) => setStatus(`EDS line-energy: ${e.message}`));
  };

  const handleWindowChange = (lo: number, hi: number) => {
    const lo2 = Math.min(lo, hi);
    const hi2 = Math.max(lo, hi);
    setELo(lo2);
    setEHi(hi2);
    setSelElem("(custom)");
    recomputeMap(lo2, hi2, bgMode);
    // refresh window patch on spectrum
    if (activeId) {
      fetchSpectrum(
        activeId,
        roi ?? undefined,
      ).then((s) => setSpectrum(s));
    }
  };

  const handleBgChange = (mode: BgMode) => {
    setBgMode(mode);
    recomputeMap(eLo, eHi, mode);
  };

  const handleRoi = (rect: Rect1 | null) => {
    setRoi(rect);
    if (!activeId) return;
    fetchSpectrum(activeId, rect ?? undefined)
      .then((s) => {
        setSpectrum(s);
        setSpecLabel(
          rect
            ? `ROI [${rect[0]}:${rect[2]}, ${rect[1]}:${rect[3]}]`
            : "Sum spectrum",
        );
      })
      .catch((e: Error) => setStatus(`EDS spectrum: ${e.message}`));
  };

  const handleShowSum = () => {
    if (!activeId) return;
    setRoi(null);
    fetchSpectrum(activeId)
      .then((s) => {
        setSpectrum(s);
        setSpecLabel("Sum spectrum");
      })
      .catch((e: Error) => setStatus(`EDS sum: ${e.message}`));
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
            <div className="fvd-ws-row">
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
                Navigate on main image
              </label>
            </div>
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
