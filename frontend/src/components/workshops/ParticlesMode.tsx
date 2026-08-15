// Particles mode — live threshold preview, then a counted particle table.
// Extracted from StructureWorkshop so the mode owns its own controls (and
// to keep that module under its size cap).

import { useEffect, useMemo, useRef, useState } from "react";

import {
  analyzeParticles,
  efdSimilarity,
  fetchData16,
  type ParticleRow,
  type Raster16,
  type ShapeClass,
} from "../../lib/api";
import {
  PARTICLE_METRIC_OPTIONS,
  pickParticleMetricValues,
  type ParticleMetric,
} from "../../lib/populationHistogram";
import { useViewer } from "../../store/viewer";
import OrientationRose from "../analysis/OrientationRose";
import PopulationHistogram from "../analysis/PopulationHistogram";
import { useResults } from "../overlays/ResultsWindow";
import ParticlesTable, { type SimilarityState } from "./ParticlesTable";

const VIEW_W = 300;

// Shape classes are advisory heuristics on the 2D PROJECTION only
// (SHAPE_ANALYSIS_PLAN.md Convention 6) — a rod viewed end-on projects as
// a disk, so no 2D image can refute that reading. Nothing elsewhere in the
// app filters or auto-corrects by class; the per-class count line below
// carries that caveat as a tooltip rather than hiding it.
const SHAPE_CLASSES: ShapeClass[] = [
  "sphere-like",
  "rod-like",
  "intermediate",
  "aggregate",
];
const SHAPE_CLASS_CAVEAT =
  "Shape classes are advisory heuristics on the 2D projection only — e.g. a rod viewed end-on projects as a disk. Thresholds are visible/tunable server-side; nothing is filtered or auto-corrected by class.";

/** Per-class particle counts, for the advisory count line below the
 *  table (SHAPE_ANALYSIS_PLAN.md item 3, Convention 6). */
export function countShapeClasses(
  particles: ParticleRow[],
): Record<ShapeClass, number> {
  const counts: Record<ShapeClass, number> = {
    "sphere-like": 0,
    "rod-like": 0,
    intermediate: 0,
    aggregate: 0,
  };
  for (const p of particles) counts[p.shape_class] += 1;
  return counts;
}

// Segmentation params captured from the DISPLAYED particle run. "Find
// similar" must resend exactly these — not whatever the threshold/
// polarity/min-area/watershed controls happen to show right now, which
// the user may have nudged since Count last ran (SHAPE_ANALYSIS_PLAN Wave
// 2: "reuse whatever state produced the current particles; do not
// re-derive defaults").
interface RunParams {
  threshold: number | null;
  polarity: "bright" | "dark";
  minArea: number;
  watershed: boolean;
}

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
  // population feed (#6/audit R6, extended by SHAPE_ANALYSIS_PLAN item 3):
  // the full per-particle rows from the last run, plus which metric the
  // picker below currently shows. pickParticleMetricValues resolves
  // calibrated-vs-px (lengths) or unit "" (dimensionless) from these.
  const [particles, setParticles] = useState<ParticleRow[]>([]);
  const [unit, setUnit] = useState("px");
  const [metric, setMetric] = useState<ParticleMetric>("equiv_diameter");
  // exact segmentation params that produced `particles` above — see
  // RunParams. Null until the first successful Count.
  const [runParams, setRunParams] = useState<RunParams | null>(null);
  // "find similar" result mode (SHAPE_ANALYSIS_PLAN Wave 2); null = the
  // normal particle table.
  const [similarity, setSimilarity] = useState<SimilarityState | null>(null);
  const [simBusyId, setSimBusyId] = useState<number | null>(null);

  // fetch the raw raster once per image
  useEffect(() => {
    rasterRef.current = null;
    setDims(null);
    setParticles([]);
    // A new image invalidates any similarity ranking from the old one —
    // stale distances against a different segmentation are wrong data.
    setSimilarity(null);
    setRunParams(null);
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
    // Re-running the analysis exits similarity mode immediately (not just
    // on success) — even a failed re-run means the on-screen params no
    // longer match what similarity was ranked against.
    setSimilarity(null);
    // slider is normalized — the endpoint wants real intensity
    const realThr = r.vmin + thresh * (r.vmax - r.vmin);
    const params: RunParams = {
      threshold: realThr,
      polarity,
      minArea: Number(minArea) || 1,
      watershed,
    };
    analyzeParticles(id, params)
      .then((res) => {
        const s = useViewer.getState();
        s.ingestDerived([res.labels]);
        s.setStatus(`particles: ${res.n_particles} found`);
        setParticles(res.particles);
        setUnit(res.unit);
        setRunParams(params);
        useResults.getState().show({
          title: `Particles (${res.n_particles}) — ${res.unit}`,
          columns: [
            "id",
            "area",
            "equiv ⌀",
            "mean I",
            "cx",
            "cy",
            "circ.",
            "AR",
            "class",
          ],
          rows: res.particles.map((p) => [
            p.id,
            p.area,
            Number(p.equiv_diameter.toPrecision(4)),
            Number(p.mean_intensity.toPrecision(4)),
            Number(p.centroid[0].toFixed(1)),
            Number(p.centroid[1].toFixed(1)),
            Number(p.circularity.toFixed(2)),
            p.aspect_ratio == null ? null : Number(p.aspect_ratio.toFixed(2)),
            p.shape_class,
          ]),
        });
      })
      .catch((e: Error) => setStatus(`particles: ${e.message}`))
      .finally(() => setBusy(false));
  };

  // Rank every particle from the displayed run by EFD shape distance to
  // `refId`, reusing runParams verbatim (not the live threshold/polarity/
  // min-area/watershed controls, which may have moved since Count last
  // ran). A 422 (undescribable reference) surfaces via the same status
  // idiom as every other failure here; the table stays exactly as it was.
  const findSimilar = (refId: number) => {
    if (!runParams) return;
    setSimBusyId(refId);
    efdSimilarity(id, {
      threshold: runParams.threshold,
      polarity: runParams.polarity,
      minArea: runParams.minArea,
      watershed: runParams.watershed,
      refId,
    })
      .then((res) => {
        setSimilarity({ refId, ranked: res.ranked, skipped: res.skipped });
        setStatus(
          `find similar: ranked ${res.ranked.length} · skipped ${res.skipped.length}`,
        );
      })
      .catch((e: Error) => setStatus(`find similar: ${e.message}`))
      .finally(() => setSimBusyId(null));
  };

  const clearSimilarity = () => setSimilarity(null);

  // resolved population for the metric picker below (calibrated-vs-px for
  // the two length metrics, unit "" for the two dimensionless ones)
  const pop = useMemo(
    () =>
      particles.length > 0
        ? pickParticleMetricValues(particles, metric, unit)
        : null,
    [particles, metric, unit],
  );
  const classCounts = useMemo(() => countShapeClasses(particles), [particles]);
  const metricLabel =
    PARTICLE_METRIC_OPTIONS.find((o) => o.value === metric)?.label ?? metric;

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
      {particles.length > 0 && (
        <>
          <div className="fvd-ws-row">
            <span className="k">metric</span>
            <select
              aria-label="Population metric"
              value={metric}
              style={{ flex: 1 }}
              onChange={(e) => setMetric(e.target.value as ParticleMetric)}
            >
              {PARTICLE_METRIC_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          {pop && pop.values.length > 0 && (
            <PopulationHistogram
              values={pop.values}
              unit={pop.unit}
              title={`Particle ${metricLabel.toLowerCase()} distribution`}
              filename="particle_size_distribution.png"
            />
          )}
          {pop && pop.excluded > 0 && (
            <div className="fvd-ws-note">
              {pop.excluded} particle(s) excluded — no aspect ratio (degenerate
              minor axis)
            </div>
          )}
          <OrientationRose particles={particles} />
          <div className="fvd-ws-note" title={SHAPE_CLASS_CAVEAT}>
            {SHAPE_CLASSES.map((c) => `${classCounts[c]} ${c}`).join(" · ")}
          </div>
          <ParticlesTable
            particles={particles}
            similarity={similarity}
            busyId={simBusyId}
            onFindSimilar={findSimilar}
            onClear={clearSimilarity}
          />
        </>
      )}
    </>
  );
}
