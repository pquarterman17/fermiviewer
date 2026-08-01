// Template match + GPA modes, split out of StructureWorkshop.tsx
// (repo-health #33). Moved verbatim; only imports now point one directory up.

import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { analyzeGpa, analyzeTemplate, imageFft } from "../../../lib/api";
import { useViewer, type Measure } from "../../../store/viewer";
import Preview from "../StructurePreview";

const NO_MEASURES: Measure[] = [];

// ── Template match ───────────────────────────────────────────────────

export function TemplateMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const meta = useViewer((s) => s.images[id] ?? null);
  // useShallow: the .filter() returns a fresh array each call; without a
  // shallow compare this selector re-renders every store tick (the
  // documented zustand black-screen class).
  const rois = useViewer(
    useShallow((s) =>
      (s.measures[id] ?? NO_MEASURES).filter((m) => m.kind === "roi"),
    ),
  );
  const [thresh, setThresh] = useState("0.7");
  const [matches, setMatches] = useState<[number, number][]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMatches([]);
    setNote("");
  }, [id]);

  const run = () => {
    if (!meta || rois.length === 0) return;
    const roi = rois[rois.length - 1];
    const [h, w] = meta.shape;
    const r0 = Math.max(
      1,
      Math.round(Math.min(roi.pts[0].y, roi.pts[1].y) * h + 0.5),
    );
    const c0 = Math.max(
      1,
      Math.round(Math.min(roi.pts[0].x, roi.pts[1].x) * w + 0.5),
    );
    const th = Math.max(
      1,
      Math.round(Math.abs(roi.pts[1].y - roi.pts[0].y) * h),
    );
    const tw = Math.max(
      1,
      Math.round(Math.abs(roi.pts[1].x - roi.pts[0].x) * w),
    );
    setBusy(true);
    analyzeTemplate(id, [r0, c0, th, tw], Number(thresh) || 0.7)
      .then((r) => {
        setMatches(r.locations);
        const top = r.scores.length ? Math.max(...r.scores) : 0;
        setNote(`${r.n_matches} matches · top score ${top.toFixed(3)}`);
      })
      .catch((e: Error) => setStatus(`template: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <Preview
        id={id}
        markers={matches.map(([r, c]) => ({ x: c, y: r }))}
        color="#f59e0b"
      />
      <div className="fvd-ws-row">
        <span className="k">thr</span>
        <input
          value={thresh}
          style={{ width: 44 }}
          onChange={(e) => setThresh(e.target.value)}
        />
        <button
          className="fvd-btn primary"
          onClick={run}
          disabled={busy || rois.length === 0}
          title={
            rois.length
              ? "Template-match the latest ROI motif across the image"
              : "draw an ROI around the motif first (R)"
          }
        >
          {busy ? "Matching…" : "Match ROI template"}
        </button>
      </div>
      <div className="fvd-ws-note">
        {rois.length === 0
          ? "Draw an ROI (R) around the motif to use as template."
          : note || `template = latest of ${rois.length} ROI(s)`}
      </div>
    </>
  );
}

// ── GPA (2-click g-vector picks on the FFT) ──────────────────────────

export function GpaMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const meta = useViewer((s) => s.images[id] ?? null);
  const [fftId, setFftId] = useState<string | null>(null);
  const [spots, setSpots] = useState<[number, number][]>([]);
  const [mean, setMean] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFftId(null);
    setSpots([]);
    setMean(null);
    let stale = false;
    imageFft(id)
      .then((m) => {
        if (!stale) setFftId(m.id);
      })
      .catch((e: Error) => setStatus(`gpa: ${e.message}`));
    return () => {
      stale = true;
    };
  }, [id, setStatus]);

  const onClick = (rc: [number, number]) => {
    const next = [...spots, rc].slice(-2) as [number, number][];
    setSpots(next);
    setMean(null);
    if (next.length === 2 && meta) {
      // FFT centre at floor(N/2)+1 (1-based, the pinned convention)
      const cr = Math.floor(meta.shape[0] / 2) + 1;
      const cc = Math.floor(meta.shape[1] / 2) + 1;
      const g = (s: [number, number]): [number, number] => [
        s[1] - cc, // gx (cols)
        s[0] - cr, // gy (rows)
      ];
      setBusy(true);
      analyzeGpa(id, g(next[0]), g(next[1]))
        .then((r) => {
          ingestDerived(r.maps);
          setMean(r.mean);
          setStatus(`GPA: εxx, εyy, εxy, ω maps registered`);
        })
        .catch((e: Error) => setStatus(`gpa: ${e.message}`))
        .finally(() => setBusy(false));
    }
  };

  return (
    <>
      {fftId && (
        <Preview
          id={fftId}
          markers={spots.map(([r, c]) => ({ x: c, y: r }))}
          color="var(--capture)"
          onClick={onClick}
        />
      )}
      <div className="fvd-ws-note">
        {busy
          ? "Computing strain maps…"
          : spots.length < 2
            ? `Click ${2 - spots.length} non-collinear g spot${
                spots.length === 1 ? "" : "s"
              } on the FFT.`
            : "Click again to restart."}
      </div>
      {mean && (
        <div className="fvd-ws-note">
          ε̄xx {fmtMean(mean["exx"])} · ε̄yy {fmtMean(mean["eyy"])} · ε̄xy{" "}
          {fmtMean(mean["exy"])} · ω̄ {fmtMean(mean["rotation"])} rad
        </div>
      )}
    </>
  );
}

function fmtMean(v: number | undefined): string {
  return v === undefined ? "—" : v.toExponential(2);
}
