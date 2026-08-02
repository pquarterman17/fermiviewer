// Diffraction-pattern panel: the mean pattern (or the pattern at the probed
// scan position), drawn on canvas through a grayscale LUT, with the current
// aperture rendered as an SVG ring overlay — a preview only; the server
// computes the authoritative mask when Compute map runs.

import { useEffect, useRef } from "react";

import { isAxisCalibrated, type FourDMeta } from "../../../lib/api";
import { useFourD, type FourDAperture, type FourDProbe } from "../../../store/fourd";
import { apertureCenterPreview, drawRaster16 } from "./fourdRaster";

const VIEW_W = 260;

/** Probe readout: pixel position, plus calibrated scan units when the
 *  dataset's scan_axes carry them (AxisCal: value = (index − origin) × scale). */
export function probeLabel(probe: FourDProbe | null, meta: FourDMeta | null): string {
  if (!probe) return "mean pattern";
  const base = `probe (${probe.y}, ${probe.x}) px`;
  if (!meta) return base;
  const [ay, ax] = meta.scan_axes;
  if (!ay || !ax || !(isAxisCalibrated(ay) || isAxisCalibrated(ax))) return base;
  const py = (probe.y - ay.origin) * ay.scale;
  const px = (probe.x - ax.origin) * ax.scale;
  const unit = ay.units || ax.units;
  return `${base} = (${py.toPrecision(4)}, ${px.toPrecision(4)}) ${unit}`;
}

function ApertureRing({
  aperture,
  center,
  scale,
}: {
  aperture: FourDAperture;
  center: { cy: number; cx: number };
  scale: number;
}) {
  const cx = center.cx * scale;
  const cy = center.cy * scale;
  const stroke = "var(--capture, #35e0c2)";
  return (
    <>
      <circle cx={cx} cy={cy} r={Math.max(1, aperture.outerR * scale)}
        fill="none" stroke={stroke} strokeWidth={1.5} />
      {aperture.shape === "annulus" && (
        <circle cx={cx} cy={cy} r={Math.max(1, aperture.innerR * scale)}
          fill="none" stroke={stroke} strokeWidth={1.5} strokeDasharray="3 2" />
      )}
      <circle cx={cx} cy={cy} r={1.5} fill={stroke} stroke="none" />
    </>
  );
}

export default function FourDPatternPanel({ meta }: { meta: FourDMeta | null }) {
  const patternRaster = useFourD((s) => s.patternRaster);
  const meanRaster = useFourD((s) => s.meanRaster);
  const busyPattern = useFourD((s) => s.busyPattern);
  const probe = useFourD((s) => s.probe);
  const aperture = useFourD((s) => s.aperture);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!patternRaster || !canvasRef.current) return;
    drawRaster16(canvasRef.current, patternRaster);
  }, [patternRaster]);

  if (!patternRaster) {
    return (
      <div className="fvd-ws-empty">
        {busyPattern ? "Loading pattern…" : "Select a dataset to load its mean pattern."}
      </div>
    );
  }

  const scale = VIEW_W / patternRaster.w;
  const viewH = patternRaster.h * scale;
  // det_shape aspect must survive regardless of what the surrounding flex
  // layout does (e.g. extra note/warning text pushing the column taller
  // after a Compute run can shrink a fixed-height flex item's main axis —
  // that's what turned the 144×144 pattern into a wide rectangle). Drive
  // sizing from CSS aspect-ratio instead of a static pixel height so the
  // browser always re-derives height from width, and pin flex-shrink: 0
  // (in .fvd-ws-pattern, 07-preferences-workshops.css) so it's never
  // squeezed away from that size in the first place.
  const aspectRatio = `${patternRaster.w} / ${patternRaster.h}`;
  const center = apertureCenterPreview(aperture, patternRaster, meanRaster);

  return (
    <div className="fvd-ws-fourd-pattern">
      <div className="fvd-ws-pattern" style={{ width: VIEW_W, aspectRatio }}>
        <canvas
          ref={canvasRef}
          style={{ width: VIEW_W, aspectRatio, imageRendering: "pixelated" }}
        />
        {center && (
          <svg width={VIEW_W} height={viewH} pointerEvents="none">
            <ApertureRing aperture={aperture} center={center} scale={scale} />
          </svg>
        )}
      </div>
      <div className="fvd-ws-note">
        {probeLabel(probe, meta)}
        {busyPattern && " · updating…"}
      </div>
    </div>
  );
}
