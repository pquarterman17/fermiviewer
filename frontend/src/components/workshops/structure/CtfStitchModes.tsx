// CTF + Stitch modes, split out of StructureWorkshop.tsx (repo-health #33).
// Moved verbatim; only imports now point one/two directories up.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  analyzeCtf,
  analyzeStitch,
  type CtfResult,
} from "../../../lib/api";
import { useViewer } from "../../../store/viewer";
import PlotContextSurface from "../../plots/PlotContextSurface";

// ── CTF ──────────────────────────────────────────────────────────────

export function CtfMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [kv, setKv] = useState("200");
  const [cs, setCs] = useState("1.2");
  const [pxA, setPxA] = useState("1.0");
  const [res, setRes] = useState<CtfResult | null>(null);
  const [busy, setBusy] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => setRes(null), [id]);

  useEffect(() => {
    const el = host.current;
    plotRef.current?.destroy();
    plotRef.current = null;
    if (!el || !res) return;
    const accent =
      getComputedStyle(document.documentElement)
        .getPropertyValue("--accent")
        .trim() || "#a78bfa";
    plotRef.current = new uPlot(
      {
        width: el.clientWidth,
        height: 160,
        scales: { x: { time: false } }, // x is spatial frequency, not time
        series: [
          {},
          { label: "power", stroke: "#8888aa", width: 1 },
          { label: "CTF² fit", stroke: accent, width: 1.5 },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      [res.radial_freq, res.radial_power, res.ctf_fit],
      el,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [res]);

  const run = () => {
    setBusy(true);
    analyzeCtf(id, {
      voltageKv: Number(kv) || 200,
      csMm: Number(cs) || 1.2,
      pixelSizeA: Number(pxA) || 1,
    })
      .then(setRes)
      .catch((e: Error) => setStatus(`ctf: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">kV</span>
        <input
          value={kv}
          style={{ width: 44 }}
          onChange={(e) => setKv(e.target.value)}
        />
        <span className="k">Cs mm</span>
        <input
          value={cs}
          style={{ width: 40 }}
          onChange={(e) => setCs(e.target.value)}
        />
        <span className="k">Å/px</span>
        <input
          value={pxA}
          style={{ width: 44 }}
          onChange={(e) => setPxA(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy}
          title="Fit the CTF to estimate defocus (Δf), λ and R²"
        >
          {busy ? "Fitting…" : "Estimate"}
        </button>
      </div>
      {res && (
        <div className="fvd-ws-note">
          Δf = {res.defocus_nm.toFixed(1)} nm · R² = {res.r_squared.toFixed(3)}{" "}
          · λ = {res.lambda_a.toFixed(4)} Å
        </div>
      )}
      {res && <PlotContextSurface ref={host} plotRef={plotRef} label="CTF radial fit" filename="ctf-radial-fit.png" className="fvd-ws-plot" />}
    </>
  );
}

// ── Stitch ───────────────────────────────────────────────────────────

export function StitchMode() {
  const selected = useViewer((s) => s.selected);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);
  const [layout, setLayout] = useState("horizontal");
  const [overlap, setOverlap] = useState("0.2");
  const [busy, setBusy] = useState(false);

  const run = () => {
    setBusy(true);
    analyzeStitch(selected, {
      layout,
      overlapFrac: Number(overlap) || 0.2,
    })
      .then((r) => {
        ingestDerived([r.mosaic]);
        setStatus(`stitched ${selected.length} tiles → ${r.mosaic.name}`);
      })
      .catch((e: Error) => setStatus(`stitch: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {["horizontal", "vertical", "grid"].map((l) => (
            <button
              key={l}
              className={`fvd-seg-btn${layout === l ? " active" : ""}`}
              onClick={() => setLayout(l)}
              title={`Arrange tiles in a ${l} layout`}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-ws-row">
        <span className="k">overlap</span>
        <input
          value={overlap}
          style={{ width: 44 }}
          onChange={(e) => setOverlap(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || selected.length < 2}
          title="Stitch the selected tiles into one mosaic"
        >
          {busy ? "Stitching…" : `Stitch ${selected.length} tiles`}
        </button>
      </div>
      <div className="fvd-ws-note">
        ⌘-click tiles in the filmstrip (equal sizes required), in acquisition
        order.
      </div>
    </>
  );
}
