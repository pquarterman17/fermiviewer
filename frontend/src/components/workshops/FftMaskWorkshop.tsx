// FFT mask editor (checklist J / plan #11 closer): click spots on the
// live FFT to place circular pass/reject masks, then inverse-transform
// via /analyze/fft-mask. The backend mirrors conjugate-symmetric
// partners, so one click per spot pair suffices.

import { useEffect, useState } from "react";

import { analyzeFftMask, imageFft, renderUrl } from "../../lib/api";
import { useViewer } from "../../store/viewer";

const VIEW_W = 300;

interface Mask {
  row: number; // 1-based FFT px
  col: number;
  radius: number;
}

export default function FftMaskWorkshop() {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const ingest = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);

  const measures = useViewer((s) =>
    s.activeId ? (s.measures[s.activeId] ?? null) : null,
  );

  const [fftId, setFftId] = useState<string | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(
    null,
  );
  const [masks, setMasks] = useState<Mask[]>([]);
  const [radius, setRadius] = useState("6");
  const [mode, setMode] = useState<"pass" | "reject">("pass");
  const [local, setLocal] = useState(false); // live/local FFT of the ROI
  const [busy, setBusy] = useState(false);

  // a derived FFT view of the active image powers the editor; the
  // source image (not the FFT) is what /analyze/fft-mask filters
  const isImage = meta?.kind === "image";
  const sourceLooksFft = meta?.name.startsWith("FFT(") ?? false;

  // latest ROI rect (1-based) for the local-FFT toggle
  const roi = (measures ?? []).filter((m) => m.kind === "roi").at(-1);
  const roiRect: [number, number, number, number] | null =
    roi && meta
      ? [
          Math.round(Math.min(roi.pts[0].y, roi.pts[1].y) * meta.shape[0]) + 1,
          Math.round(Math.min(roi.pts[0].x, roi.pts[1].x) * meta.shape[1]) + 1,
          Math.round(Math.max(roi.pts[0].y, roi.pts[1].y) * meta.shape[0]),
          Math.round(Math.max(roi.pts[0].x, roi.pts[1].x) * meta.shape[1]),
        ]
      : null;
  const rectKey = roiRect?.join(",") ?? "";

  useEffect(() => {
    setFftId(null);
    setNatural(null);
    setMasks([]);
    if (!activeId || !isImage || sourceLooksFft) return;
    let stale = false;
    const rect = local && roiRect ? roiRect : undefined;
    imageFft(activeId, rect)
      .then((m) => {
        if (!stale) setFftId(m.id);
      })
      .catch((e: Error) => setStatus(`fft: ${e.message}`));
    return () => {
      stale = true;
    };
    // rectKey stands in for roiRect (fresh array per render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, isImage, sourceLooksFft, local, rectKey, setStatus]);

  if (!isImage || sourceLooksFft) {
    return (
      <div className="fvd-ws-empty">
        Select a real-space 2D image — the editor shows its FFT.
      </div>
    );
  }

  const scale = natural ? VIEW_W / natural.w : 0;
  const viewH = natural ? natural.h * scale : VIEW_W;

  const onClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!natural) return;
    const r = e.currentTarget.getBoundingClientRect();
    const col = (e.clientX - r.left) / scale + 0.5; // 1-based centre
    const row = (e.clientY - r.top) / scale + 0.5;
    setMasks((ms) => [
      ...ms,
      { row, col, radius: Math.max(1, Number(radius) || 6) },
    ]);
  };

  const apply = () => {
    if (!activeId || masks.length === 0) return;
    setBusy(true);
    analyzeFftMask(
      activeId,
      masks.map((m) => [m.row, m.col, m.radius]),
      mode,
    )
      .then((r) => {
        ingest([r.image]);
        setStatus(`Fourier filter → ${r.image.name}`);
      })
      .catch((e: Error) => setStatus(`fft-mask: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <div className="fvd-ws">
      <div
        className="fvd-ws-pattern"
        style={{ width: VIEW_W, height: viewH, cursor: "crosshair" }}
        onClick={onClick}
      >
        {fftId && (
          <img
            src={renderUrl(fftId)}
            alt="fft"
            width={VIEW_W}
            draggable={false}
            onLoad={(e) => {
              const el = e.currentTarget;
              setNatural({ w: el.naturalWidth, h: el.naturalHeight });
            }}
          />
        )}
        {natural && (
          <svg width={VIEW_W} height={viewH} pointerEvents="none">
            {masks.map((m, i) => (
              <circle
                key={i}
                cx={(m.col - 0.5) * scale}
                cy={(m.row - 0.5) * scale}
                r={Math.max(2, m.radius * scale)}
                fill="none"
                stroke={mode === "pass" ? "var(--capture)" : "#f43f5e"}
                strokeWidth={1.5}
              />
            ))}
          </svg>
        )}
      </div>

      <div className="fvd-ws-row">
        <label
          className={`fvd-check${roiRect ? "" : " disabled"}`}
          title={roiRect ? "" : "draw an ROI on the image first (R)"}
        >
          <input
            type="checkbox"
            checked={local && roiRect !== null}
            disabled={!roiRect}
            onChange={(e) => setLocal(e.target.checked)}
          />
          Live FFT of ROI
        </label>
      </div>
      <div className="fvd-ws-row">
        <span className="k">radius</span>
        <input
          value={radius}
          style={{ width: 44 }}
          onChange={(e) => setRadius(e.target.value)}
        />
        <div className="fvd-seg">
          {(["pass", "reject"] as const).map((m) => (
            <button
              key={m}
              className={`fvd-seg-btn${mode === m ? " active" : ""}`}
              onClick={() => setMode(m)}
            >
              {m}
            </button>
          ))}
        </div>
      </div>

      <div className="fvd-ws-row">
        <span className="k">
          {masks.length} mask{masks.length === 1 ? "" : "s"}
        </span>
        <button
          className="fvd-btn"
          disabled={masks.length === 0}
          onClick={() => setMasks((ms) => ms.slice(0, -1))}
        >
          Undo
        </button>
        <button
          className="fvd-btn"
          disabled={masks.length === 0}
          onClick={() => setMasks([])}
        >
          Clear
        </button>
        <button
          className="fvd-btn primary"
          disabled={busy || masks.length === 0 || local}
          title={
            local
              ? "masks apply to the full-image FFT — switch Live FFT off"
              : ""
          }
          onClick={apply}
        >
          {busy ? "Filtering…" : "Apply"}
        </button>
      </div>
    </div>
  );
}
