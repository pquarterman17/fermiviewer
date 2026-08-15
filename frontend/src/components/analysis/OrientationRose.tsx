// SVG half-rose of particle orientation angles (SHAPE_ANALYSIS_PLAN.md item
// 3, Convention 3). Orientation is AXIAL — skimage's regionprops convention
// is the angle between the ROW axis and the ellipse major axis, range
// (-π/2, π/2], period π (a rod at +80° is the SAME rod at −100°). The rose
// therefore spans exactly (-90°, 90°] and is NEVER mirrored into a full
// circle: mirroring would double-count every particle visually, since the
// data has no second, independent half to show. It is also MORPHOLOGICAL
// orientation, not crystallographic — lib/crossSectionReport.ts draws the
// same distinction for grain shape angle ("Shape angle is morphological and
// is not crystallographic orientation.").
//
// Near-circular particles (eccentricity < 0.2) are excluded from the
// binning — a circle has no well-defined major axis, so its "orientation"
// is measurement noise, not signal — and reported separately as a count
// rather than silently dropped.
//
// Rendering follows the plain-SVG chart idiom used elsewhere in
// components/workshops (e.g. LayersMultiCompare's MetricChart): a viewBox'd
// <svg role="img">, theme tokens for stroke/fill (var(--border),
// var(--accent)), text via fill="currentColor" so it follows the
// surrounding text color in both themes.

import { useMemo } from "react";

const N_BINS = 18;
const BIN_WIDTH_DEG = 180 / N_BINS;
const NEAR_CIRCULAR_ECC = 0.2;
const R_MAX = 78;
const CX = 100;
const CY = 96;
const VIEW_H = 118;

export interface OrientedParticle {
  orientation_rad: number;
  eccentricity: number;
}

export interface RoseBin {
  /** bin center, degrees, within (-90, 90]. */
  angleDeg: number;
  count: number;
}

export interface RoseResult {
  /** always `nBins` entries, ordered −90°→90°. */
  bins: RoseBin[];
  /** particles binned (eccentricity >= 0.2). */
  n: number;
  /** near-circular particles (eccentricity < 0.2), excluded from `bins`. */
  excluded: number;
}

/** Bin orientations into an axial half-rose over (-90°, 90°]. A particle's
 *  bin is chosen from its raw angle alone — angles are never folded onto
 *  the opposite sign, so a +80° particle and a −80° particle always land
 *  in different bins (the whole point of an axial, non-mirrored rose). */
export function binOrientations(
  particles: OrientedParticle[],
  nBins = N_BINS,
): RoseResult {
  const binWidth = 180 / nBins;
  const bins: RoseBin[] = Array.from({ length: nBins }, (_, i) => ({
    angleDeg: -90 + binWidth * (i + 0.5),
    count: 0,
  }));
  let excluded = 0;
  let n = 0;
  for (const p of particles) {
    if (p.eccentricity < NEAR_CIRCULAR_ECC) {
      excluded += 1;
      continue;
    }
    const deg = (p.orientation_rad * 180) / Math.PI;
    let idx = Math.floor((deg + 90) / binWidth);
    if (idx < 0) idx = 0;
    if (idx >= nBins) idx = nBins - 1;
    bins[idx].count += 1;
    n += 1;
  }
  return { bins, n, excluded };
}

/** Point on the half-rose at `angleDeg` (0° = up, ±90° = the baseline
 *  ends) and radius `r`, in the SVG's local coordinate space. */
function petalPoint(angleDeg: number, r: number): [number, number] {
  const rad = (angleDeg * Math.PI) / 180;
  return [CX + r * Math.sin(rad), CY - r * Math.cos(rad)];
}

function arcPath(r: number): string {
  const [x1, y1] = petalPoint(-90, r);
  const [x2, y2] = petalPoint(90, r);
  return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`;
}

export default function OrientationRose({
  particles,
}: {
  particles: OrientedParticle[];
}) {
  const rose = useMemo(() => binOrientations(particles), [particles]);
  const maxCount = Math.max(1, ...rose.bins.map((b) => b.count));

  return (
    <section>
      <div
        className="fvd-ws-note"
        title="Angle to the image row axis (skimage regionprops convention), not crystallographic orientation. Axial: a rod at +80° is the same rod at −100°, so this half-rose is never mirrored into a full circle."
      >
        Orientation rose (axial, morphological)
      </div>
      <svg
        viewBox={`0 0 200 ${VIEW_H}`}
        role="img"
        aria-label="Particle orientation half-rose"
        className="fvd-ws-plot"
        style={{ width: "100%", height: 150 }}
      >
        <line
          x1={CX - R_MAX}
          y1={CY}
          x2={CX + R_MAX}
          y2={CY}
          stroke="var(--border)"
        />
        {[0.25, 0.5, 0.75, 1].map((frac) => (
          <path
            key={frac}
            d={arcPath(frac * R_MAX)}
            fill="none"
            stroke="var(--border-soft)"
          />
        ))}
        {rose.bins.map((bin) => {
          const r = (bin.count / maxCount) * R_MAX;
          if (r <= 0) return null;
          const startDeg = bin.angleDeg - BIN_WIDTH_DEG / 2;
          const endDeg = bin.angleDeg + BIN_WIDTH_DEG / 2;
          const [x1, y1] = petalPoint(startDeg, r);
          const [x2, y2] = petalPoint(endDeg, r);
          return (
            <path
              key={bin.angleDeg}
              data-testid={`rose-bin-${bin.angleDeg}`}
              data-count={bin.count}
              d={`M ${CX} ${CY} L ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2} Z`}
              fill="var(--accent)"
              fillOpacity={0.75}
              stroke="var(--accent)"
              strokeWidth={0.5}
            />
          );
        })}
        {[-90, -45, 0, 45, 90].map((deg) => {
          const [x, y] = petalPoint(deg, R_MAX + 12);
          return (
            <text
              key={deg}
              x={x}
              y={y}
              textAnchor="middle"
              fontSize="9"
              fill="currentColor"
            >
              {deg}°
            </text>
          );
        })}
      </svg>
      <div className="fvd-ws-note">
        N={rose.n}
        {rose.excluded > 0 &&
          ` · ${rose.excluded} near-circular excluded (eccentricity < ${NEAR_CIRCULAR_ECC})`}
      </div>
    </section>
  );
}
