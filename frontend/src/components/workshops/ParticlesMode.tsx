// Particles mode — live threshold preview, then a counted particle table.
// Extracted from StructureWorkshop so the mode owns its own controls (and
// to keep that module under its size cap).

import { useEffect, useRef, useState } from "react";

import { analyzeParticles, fetchData16, type Raster16 } from "../../lib/api";
import { pickSizeValues } from "../../lib/populationHistogram";
import { useViewer } from "../../store/viewer";
import PopulationHistogram from "../analysis/PopulationHistogram";
import { useResults } from "../overlays/ResultsWindow";

const VIEW_W = 300;

export default function ParticlesMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [thresh, setThresh] = useState(0.5); // normalized vs raster range
  const [polarity, setPolarity] = useState<"bright" | "dark">("bright");
  const [minArea, setMinArea] = useState("5");
  // Watershed splitting separates touching particles. The menu dialog that
  // used to own this option was replaced by this mode, so without the toggle
  // agglomerated particles can only ever be counted as one blob.
  const [watershed, setWatershed] = useState(false);
  const [busy, setBusy] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rasterRef = useRef<Raster16 | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  // size-distribution feed (#6/audit R6): equivalent diameter, calibrated
  // when the image has a pixel size, else px — see pickSizeValues
  const [sizePop, setSizePop] = useState<{ values: number[]; unit: string } | null>(
    null,
  );

  // fetch the raw raster once per image
  useEffect(() => {
    rasterRef.current = null;
    setDims(null);
    setSizePop(null);
    let stale = false;
    fetchData16(id)
      .then((r) => {
        if (stale) return;
        rasterRef.current = r;
        setDims({ w: r.w, h: r.h });
      })
      .catch((e: Error) => setStatus(`particles: ${e.message}`));
    return () => {
      stale = true;
    };
  }, [id, setStatus]);

  // live preview: grayscale base + tinted mask at the threshold
  useEffect(() => {
    const r = rasterRef.current;
    const cv = canvasRef.current;
    if (!r || !cv || !dims) return;
    cv.width = r.w;
    cv.height = r.h;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(r.w, r.h);
    const cut = thresh * 65535;
    for (let i = 0; i < r.w * r.h; i++) {
      const v = r.data[i];
      const g = v >> 8;
      const hit = polarity === "bright" ? v >= cut : v <= cut;
      const o = i * 4;
      img.data[o] = hit ? 244 : g;
      img.data[o + 1] = hit ? 63 : g;
      img.data[o + 2] = hit ? 94 : g;
      img.data[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [thresh, polarity, dims]);

  const count = () => {
    const r = rasterRef.current;
    if (!r) return;
    setBusy(true);
    // slider is normalized — the endpoint wants real intensity
    const realThr = r.vmin + thresh * (r.vmax - r.vmin);
    analyzeParticles(id, {
      threshold: realThr,
      polarity,
      minArea: Number(minArea) || 1,
      watershed,
    })
      .then((res) => {
        const s = useViewer.getState();
        s.ingestDerived([res.labels]);
        s.setStatus(`particles: ${res.n_particles} found`);
        setSizePop(
          pickSizeValues(
            res.particles.map((p) => p.equiv_diameter),
            res.particles.map((p) => p.diameter_calibrated),
            res.unit,
          ),
        );
        useResults.getState().show({
          title: `Particles (${res.n_particles}) — ${res.unit}`,
          columns: ["id", "area", "equiv ⌀", "mean I", "cx", "cy"],
          rows: res.particles.map((p) => [
            p.id,
            p.area,
            Number(p.equiv_diameter.toPrecision(4)),
            Number(p.mean_intensity.toPrecision(4)),
            Number(p.centroid[0].toFixed(1)),
            Number(p.centroid[1].toFixed(1)),
          ]),
        });
      })
      .catch((e: Error) => setStatus(`particles: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const viewH = dims ? (dims.h / dims.w) * VIEW_W : VIEW_W;
  return (
    <>
      <div className="fvd-ws-pattern" style={{ width: VIEW_W, height: viewH }}>
        <canvas
          ref={canvasRef}
          style={{
            width: VIEW_W,
            height: viewH,
            imageRendering: "pixelated",
          }}
        />
      </div>
      <div className="fvd-ws-row">
        <span className="k">thr</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.005}
          value={thresh}
          style={{ flex: 1 }}
          onChange={(e) => setThresh(Number(e.target.value))}
        />
        <span className="k">{thresh.toFixed(3)}</span>
      </div>
      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {(["bright", "dark"] as const).map((p) => (
            <button
              key={p}
              className={`fvd-seg-btn${polarity === p ? " active" : ""}`}
              onClick={() => setPolarity(p)}
              title={`Detect ${p} particles on a ${p === "bright" ? "dark" : "bright"} background`}
            >
              {p}
            </button>
          ))}
        </div>
        <span className="k">min px</span>
        <input
          value={minArea}
          style={{ width: 40 }}
          onChange={(e) => setMinArea(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={count}
          disabled={busy}
          title="Count particles above the threshold and list area/centroid"
        >
          {busy ? "Counting…" : "Count"}
        </button>
      </div>
      <label
        className="k"
        style={{ display: "flex", alignItems: "center", gap: 4 }}
        title="Split touching particles with a watershed on the distance transform"
      >
        <input
          type="checkbox"
          checked={watershed}
          onChange={(e) => setWatershed(e.target.checked)}
        />
        Split touching particles
      </label>
      {sizePop && sizePop.values.length > 0 && (
        <PopulationHistogram
          values={sizePop.values}
          unit={sizePop.unit}
          title="Particle size distribution"
          filename="particle_size_distribution.png"
        />
      )}
    </>
  );
}
