// Per-interface roughness detail card (CROSS_SECTION_LAYERS #13):
// the "detail on demand" behind the layer table's quick numbers. Shows the
// rigorous trace metrology — σ_w with its bootstrap CI, correlation length ξ,
// Hurst exponent H, the σ_chem decomposition — plus the roughness power
// spectral density with the projection-limited region shaded when the user
// supplies an approximate foil thickness.

import { useEffect, useRef } from "react";
import uPlot from "uplot";

import { type LayerInterface } from "../../lib/api";

function PsdPlot({
  wavelength,
  power,
  unit,
  foilT,
}: {
  wavelength: number[];
  power: number[];
  unit: string;
  foilT: number | null;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    plotRef.current?.destroy();
    // ascending wavelength for uPlot; log-log needs strictly positive values
    const pairs = wavelength
      .map((wl, i) => [wl, power[i]] as const)
      .filter(([wl, p]) => wl > 0 && p > 0)
      .sort((a, b) => a[0] - b[0]);
    if (pairs.length < 4) return;
    const xs = pairs.map((p) => p[0]);
    const ys = pairs.map((p) => p[1]);
    const accent =
      getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() ||
      "#a78bfa";
    plotRef.current = new uPlot(
      {
        width: host.clientWidth || 300,
        height: 140,
        // x is a lateral wavelength, not a timestamp; log-log is the natural
        // space for a roughness PSD (self-affine → straight-line tail)
        scales: { x: { time: false, distr: 3 }, y: { distr: 3 } },
        series: [
          { label: `λ (${unit})` },
          { label: "PSD", stroke: accent, width: 1.5, points: { show: false } },
        ],
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" }, size: 56 },
        ],
        legend: { show: false },
        cursor: { y: false },
        hooks: {
          draw: [
            (u) => {
              // wavelengths shorter than the foil thickness are averaged
              // along the beam (projection) — shade them as untrustworthy
              if (foilT == null || foilT <= xs[0]) return;
              const ctx = u.ctx;
              const xEnd = u.valToPos(Math.min(foilT, xs[xs.length - 1]), "x", true);
              ctx.save();
              ctx.fillStyle = "rgba(245, 158, 11, 0.12)";
              ctx.fillRect(
                u.bbox.left,
                u.bbox.top,
                Math.max(0, xEnd - u.bbox.left),
                u.bbox.height,
              );
              ctx.restore();
            },
          ],
        },
      },
      [xs, ys] as uPlot.AlignedData,
      host,
    );
    const ro = new ResizeObserver(() => {
      if (plotRef.current && host.clientWidth > 0) {
        plotRef.current.setSize({ width: host.clientWidth, height: 140 });
      }
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [wavelength, power, unit, foilT]);

  return <div ref={hostRef} className="fvd-ws-plot" />;
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toFixed(digits);

export default function LayersRoughnessDetail({
  iface,
  index,
  unit,
  foilT,
}: {
  iface: LayerInterface;
  index: number;
  unit: string;
  foilT: number | null;
}) {
  const r = iface.roughness;
  if (!r) {
    return (
      <div className="fvd-ws-note">
        Enable <b>waviness (σ_w)</b> and re-analyze to trace this interface.
      </div>
    );
  }
  const lowQuality = r.quality < 0.9;
  // the metric-tile label CSS uppercases — σ→Σ reads wrong, keep greek as-is
  const kStyle = { textTransform: "none" as const };
  return (
    <div data-testid={`iface-detail-${index}`}>
      <div className="fvd-metrics">
        <div className="fvd-metric">
          <span className="v">
            {fmt(iface.sigma_w)}
            {r.sigma_ci && (
              <span className="dim" style={{ fontSize: 10 }}>
                {" "}
                [{fmt(r.sigma_ci[0])}–{fmt(r.sigma_ci[1])}]
              </span>
            )}
          </span>
          <span className="k" style={kStyle}>σ_w ({unit}) · 95% CI</span>
        </div>
        <div className="fvd-metric">
          <span className="v">{fmt(r.xi, r.xi != null && r.xi < 10 ? 1 : 0)}</span>
          <span className="k" style={kStyle}>corr. length ξ ({unit})</span>
        </div>
        <div className="fvd-metric">
          <span className="v">{fmt(r.hurst)}</span>
          <span className="k" style={kStyle}>Hurst H</span>
        </div>
        <div
          className="fvd-metric"
          title="Intrinsic (chemical) diffuseness: sqrt(σ_erf² − σ_w²). The erf width on the averaged profile convolves grading with waviness; this removes the waviness part. Projection-limited — an upper bound on true grading."
        >
          <span className="v">{fmt(r.sigma_chem)}</span>
          <span className="k" style={kStyle}>σ_chem ({unit})</span>
        </div>
      </div>
      <div className="fvd-ws-note" style={{ fontSize: 10 }}>
        trace: {(r.quality * 100).toFixed(0)}% of columns OK
        {lowQuality && " ⚠ noisy trace — treat σ_w with care"}
        {" · "}raw σ {fmt(r.sigma_raw)} − noise floor {fmt(r.noise_floor)} {unit}
        {" · "}detrended (tilt/bow removed)
      </div>
      {r.psd_wavelength.length > 3 && (
        <>
          <PsdPlot
            wavelength={r.psd_wavelength}
            power={r.psd_power}
            unit={unit}
            foilT={foilT}
          />
          <div className="fvd-ws-note" style={{ fontSize: 10 }}>
            Roughness spectrum (log–log). σ_w is a <b>lower bound</b>: lateral
            wavelengths shorter than the foil thickness are projection-smeared
            {foilT != null && " (shaded region)"}.
          </div>
        </>
      )}
    </div>
  );
}
