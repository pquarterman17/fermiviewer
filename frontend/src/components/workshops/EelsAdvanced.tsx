// EELS advanced section (plan #56): thickness map, ZLP alignment,
// Fourier-log deconvolution, Kramers-Kronig dielectric analysis and
// SVD/MSA decomposition — UI over the /eels/* advanced endpoints.

import { useEffect, useRef, useState } from "react";
import uPlot from "uplot";

import {
  eelsAlignZlp,
  eelsFourierLog,
  eelsKK,
  eelsRichardsonLucy,
  eelsSubpixelAlign,
  eelsSvd,
  eelsThickness,
  type KKResult,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

type AdvPlot =
  | { kind: "ssd"; energy: number[]; spectrum: number[]; ssd: number[] }
  | { kind: "kk"; r: KKResult };

export default function EelsAdvanced({
  activeId,
  isCube,
  units,
}: {
  activeId: string | null;
  isCube: boolean;
  units: string;
}) {
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);

  const [open, setOpen] = useState(false);
  const [zlpLo, setZlpLo] = useState("-5");
  const [zlpHi, setZlpHi] = useState("5");
  const [nIndex, setNIndex] = useState("");
  const [nComp, setNComp] = useState("8");
  const [denoise, setDenoise] = useState(false);
  const [rlIters, setRlIters] = useState("15");
  const [subpixel, setSubpixel] = useState(false);
  const [plot, setPlot] = useState<AdvPlot | null>(null);
  const [note, setNote] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const host = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);

  const zlp = (): [number, number] => [
    Number(zlpLo) || -5,
    Number(zlpHi) || 5,
  ];

  useEffect(() => {
    setPlot(null);
    setNote("");
  }, [activeId]);

  // render the SSD / KK plot
  useEffect(() => {
    const el = host.current;
    plotRef.current?.destroy();
    plotRef.current = null;
    if (!el || !plot) return;
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    let series: uPlot.Series[];
    let data: uPlot.AlignedData;
    if (plot.kind === "ssd") {
      series = [
        {},
        { label: "spectrum", stroke: "#8888aa", width: 1 },
        { label: "SSD", stroke: accent, width: 1.5 },
      ];
      data = [plot.energy, plot.spectrum, plot.ssd];
    } else {
      series = [
        {},
        { label: "ε₁", stroke: "#d97706", width: 1.2 },
        { label: "ε₂", stroke: accent, width: 1.2 },
        { label: "ELF", stroke: "#22c55e", width: 1 },
      ];
      data = [plot.r.energy, plot.r.eps1, plot.r.eps2, plot.r.elf];
    }
    plotRef.current = new uPlot(
      {
        width: el.clientWidth,
        height: 160,
        scales: { x: { time: false } }, // x is eV energy-loss, not a timestamp
        series,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
        ],
        legend: { show: false },
        cursor: { y: false },
      },
      data,
      el,
    );
    return () => {
      plotRef.current?.destroy();
      plotRef.current = null;
    };
  }, [plot]);

  if (!activeId) return null;

  const guard = (p: Promise<void>) => {
    setBusy(true);
    p.catch((e: Error) => setStatus(`EELS adv: ${e.message}`)).finally(() =>
      setBusy(false),
    );
  };

  const runThickness = () =>
    guard(
      eelsThickness(activeId, zlp()).then((r) => {
        ingestDerived([r.map]);
        setNote(
          `t/λ map — mean ${r.mean_t_over_lambda.toFixed(3)}, ` +
            `${(r.valid_fraction * 100).toFixed(0)}% valid`,
        );
      }),
    );

  const runAlign = () =>
    guard(
      (subpixel ? eelsSubpixelAlign(activeId) : eelsAlignZlp(activeId)).then(
        (r) => {
          ingestDerived([r.aligned]);
          setNote(
            `aligned${subpixel ? " (sub-pixel)" : ""} — max shift ` +
              `${subpixel ? r.max_shift.toFixed(2) : r.max_shift} ch, ` +
              `${(r.shifted_fraction * 100).toFixed(0)}% pixels moved`,
          );
        },
      ),
    );

  const runRichardsonLucy = () =>
    guard(
      eelsRichardsonLucy(activeId, zlp(), Number(rlIters) || 15).then((r) => {
        setPlot({
          kind: "ssd",
          energy: r.energy,
          spectrum: r.spectrum,
          ssd: r.deconvolved,
        });
        setNote(`Richardson–Lucy — ${r.iterations} iterations`);
      }),
    );

  const runFourierLog = () =>
    guard(
      eelsFourierLog(activeId, zlp()).then((r) => {
        setPlot({
          kind: "ssd",
          energy: r.energy,
          spectrum: r.spectrum,
          ssd: r.ssd,
        });
        setNote(`Fourier-log — t/λ ${r.t_over_lambda.toFixed(3)}`);
      }),
    );

  const runKK = () =>
    guard(
      eelsKK(activeId, {
        zlpWindow: zlp(),
        refractiveIndex: nIndex ? Number(nIndex) : undefined,
      }).then((r) => {
        setPlot({ kind: "kk", r });
        setNote(
          `KK — t ≈ ${r.thickness_nm.toFixed(1)} nm, ` +
            `t/λ ${r.t_over_lambda.toFixed(3)}`,
        );
      }),
    );

  const runSvd = () =>
    guard(
      eelsSvd(activeId, {
        nComponents: Number(nComp) || 0,
        denoise,
      }).then((r) => {
        const metas = [...r.score_maps, ...(r.denoised ? [r.denoised] : [])];
        if (metas.length) ingestDerived(metas);
        const top = r.explained
          .slice(0, 4)
          .map((v, i) => `PC${i + 1} ${v.toFixed(1)}%`)
          .join(" · ");
        setNote(`SVD — ${top}`);
      }),
    );

  return (
    <>
      <div className="fvd-ws-section">
        <span>Advanced</span>
        <button className="fvd-btn" onClick={() => setOpen(!open)}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <>
          <div className="fvd-ws-row">
            <span className="k">ZLP win</span>
            <input
              value={zlpLo}
              style={{ width: 44 }}
              onChange={(e) => setZlpLo(e.target.value)}
            />
            <span>–</span>
            <input
              value={zlpHi}
              style={{ width: 44 }}
              onChange={(e) => setZlpHi(e.target.value)}
            />
            <span className="k">{units}</span>
          </div>
          <div className="fvd-ws-row">
            <button
              className="fvd-btn"
              onClick={runThickness}
              disabled={busy || !isCube}
              title="Log-ratio t/λ map (cube)"
            >
              t/λ map
            </button>
            <button
              className="fvd-btn"
              onClick={runAlign}
              disabled={busy || !isCube}
              title="ZLP alignment (cube) — sub-pixel when checked"
            >
              Align ZLP
            </button>
            <label className="fvd-check" title="Parabolic-refined fractional-channel ZLP alignment (#10)">
              <input
                type="checkbox"
                checked={subpixel}
                onChange={(e) => setSubpixel(e.target.checked)}
              />
              sub-px
            </label>
            <button
              className="fvd-btn"
              onClick={runFourierLog}
              disabled={busy}
              title="Plural-scattering removal"
            >
              Fourier-log
            </button>
          </div>
          <div className="fvd-ws-row">
            <span className="k">RL iters</span>
            <input
              value={rlIters}
              style={{ width: 40 }}
              title="Richardson–Lucy iteration count"
              onChange={(e) => setRlIters(e.target.value)}
            />
            <button
              className="fvd-btn"
              onClick={runRichardsonLucy}
              disabled={busy}
              title="Richardson–Lucy deconvolution — recover resolution lost to the ZLP (#10)"
            >
              Richardson–Lucy
            </button>
          </div>
          <div className="fvd-ws-row">
            <span className="k">n</span>
            <input
              value={nIndex}
              placeholder="auto"
              style={{ width: 48 }}
              title="Refractive index for KK normalisation (blank = unnormalised)"
              onChange={(e) => setNIndex(e.target.value)}
            />
            <button className="fvd-btn" onClick={runKK} disabled={busy}>
              Kramers–Kronig
            </button>
          </div>
          <div className="fvd-ws-row">
            <span className="k">comps</span>
            <input
              value={nComp}
              style={{ width: 40 }}
              onChange={(e) => setNComp(e.target.value)}
            />
            <label className="fvd-check">
              <input
                type="checkbox"
                checked={denoise}
                onChange={(e) => setDenoise(e.target.checked)}
              />
              denoise
            </label>
            <button
              className="fvd-btn"
              onClick={runSvd}
              disabled={busy || !isCube}
            >
              SVD
            </button>
          </div>
          {note && <div className="fvd-ws-note">{note}</div>}
          {plot && <div ref={host} className="fvd-ws-plot" />}
        </>
      )}
    </>
  );
}
