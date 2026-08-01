// runFit / runMap / addEdge / runQuantify / runModelFit / runModelFitMaps /
// runElnes factories, split out of EelsWorkshop.tsx in the repo-health #33
// decomposition. Bodies moved verbatim; the only change is threading an
// explicit EelsRunnersCtx instead of closing over component state directly
// — EelsWorkshop.tsx builds the ctx each render (as these closures already
// were, being plain non-memoized consts) and the button call sites are
// unchanged.

import type { Dispatch, SetStateAction } from "react";

import {
  analyzeElnes,
  eelsBackground,
  eelsFit,
  eelsFitMap,
  eelsMap,
  eelsQuantify,
  type EelsBackgroundResult,
  type EelsFitResult,
  type EelsQuantResult,
  type ElnesResult,
  type Spectrum,
} from "../../../lib/api";
import { useViewer } from "../../../store/viewer";
import type { EdgeRow } from "../EelsEdgeEditor";

let edgeSeq = 0;

export interface EelsRunnersCtx {
  activeId: string | null;
  spectrum: Spectrum | null;
  bgLo: string;
  bgHi: string;
  sigLo: string;
  sigHi: string;
  edges: EdgeRow[];
  e0Kv: number;
  betaMrad: number;
  quantMethod: string;
  setFit: (r: EelsBackgroundResult | null) => void;
  setQuant: (r: EelsQuantResult | null) => void;
  setFitResult: (r: EelsFitResult | null) => void;
  setElnes: (r: ElnesResult | null) => void;
  setEdges: Dispatch<SetStateAction<EdgeRow[]>>;
  setStatus: (msg: string) => void;
}

export function makeRunFit(ctx: EelsRunnersCtx) {
  const { activeId, bgLo, bgHi, setFit, setStatus } = ctx;
  return () => {
    if (!activeId) return;
    const startId = activeId;
    eelsBackground(activeId, [Number(bgLo), Number(bgHi)])
      .then((r) => {
        if (useViewer.getState().activeId === startId) setFit(r);
      })
      .catch((e: Error) => setStatus(`EELS fit: ${e.message}`));
  };
}

export function makeRunMap(ctx: EelsRunnersCtx) {
  const { activeId, sigLo, sigHi, bgLo, bgHi, setStatus } = ctx;
  return () => {
    if (!activeId) return;
    eelsMap(
      activeId,
      [Number(sigLo), Number(sigHi)],
      bgLo && bgHi ? [Number(bgLo), Number(bgHi)] : null,
    )
      .then((m) => {
        // ingestDerived (not a raw setState) seeds history/undo/displayPrefs
        // and bumps derivedTick, same as every other workshop's derived image
        useViewer.getState().ingestDerived([m]);
        setStatus(`map registered: ${m.name}`);
      })
      .catch((e: Error) => setStatus(`EELS map: ${e.message}`));
  };
}

export function makeAddEdge(ctx: EelsRunnersCtx) {
  const { bgLo, bgHi, setEdges } = ctx;
  return () =>
    setEdges((rows) => [
      ...rows,
      {
        key: ++edgeSeq,
        element: "",
        shell: "K",
        z: 0,
        onset_ev: 0,
        signal_window: [0, 0],
        bg_window: [Number(bgLo) || 0, Number(bgHi) || 0],
      },
    ]);
}

export function makeRunQuantify(ctx: EelsRunnersCtx) {
  const { activeId, edges, e0Kv, betaMrad, quantMethod, setQuant, setStatus } =
    ctx;
  return () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS quantify: add at least one edge row");
      return;
    }
    const startId = activeId;
    eelsQuantify(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
      quantMethod,
    )
      .then((r) => {
        if (useViewer.getState().activeId === startId) setQuant(r);
      })
      .catch((e: Error) => setStatus(`EELS quantify: ${e.message}`));
  };
}

// model-based simultaneous fit (#2): background + all edges in one fit,
// at% from the fitted amplitude ratios (separates overlapping edges)
export function makeRunModelFit(ctx: EelsRunnersCtx) {
  const {
    activeId,
    edges,
    bgLo,
    spectrum,
    e0Kv,
    betaMrad,
    setFitResult,
    setStatus,
  } = ctx;
  return () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS fit: add at least one edge row");
      return;
    }
    const fitRange: [number, number] | null =
      bgLo && spectrum
        ? [Number(bgLo), spectrum.energy[spectrum.energy.length - 1]]
        : null;
    const startId = activeId;
    eelsFit(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
      fitRange,
    )
      .then((r) => {
        if (useViewer.getState().activeId !== startId) return;
        setFitResult(r);
        setStatus(
          `EELS fit · χ²ᵣ ${r.reduced_chi2.toExponential(2)} · ` +
            r.edges
              .map((ed) => `${ed.element} ${ed.atomic_percent.toFixed(1)}%`)
              .join(" · "),
        );
      })
      .catch((e: Error) => setStatus(`EELS fit: ${e.message}`));
  };
}

export function makeRunModelFitMaps(ctx: EelsRunnersCtx) {
  const { activeId, edges, e0Kv, betaMrad, setStatus } = ctx;
  return () => {
    if (!activeId) return;
    const clean = edges.filter((e) => e.element && e.z > 0);
    if (clean.length === 0) {
      setStatus("EELS fit maps: add at least one edge row");
      return;
    }
    eelsFitMap(
      activeId,
      clean.map(({ key: _key, ...e }) => e),
      e0Kv,
      betaMrad,
    )
      .then((r) => {
        useViewer.getState().ingestDerived(r.maps);
        setStatus(
          `EELS fit maps · ` +
            r.elements
              .map((el, i) => `${el} ${r.mean_atomic_percent[i].toFixed(1)}%`)
              .join(" · "),
        );
      })
      .catch((e: Error) => setStatus(`EELS fit maps: ${e.message}`));
  };
}

export function makeRunElnes(ctx: EelsRunnersCtx) {
  const { activeId, edges, setElnes, setStatus } = ctx;
  return () => {
    if (!activeId || edges.length === 0) {
      setStatus("ELNES: add an edge row first to define edge_onset");
      return;
    }
    const edge = edges[edges.length - 1];
    const onset = edge.onset_ev || 0;
    if (onset <= 0) {
      setStatus("ELNES: set edge onset (eV) in the edge row first");
      return;
    }
    const fitWin: [number, number] = [
      edge.bg_window[0] || onset - 100,
      edge.bg_window[1] || onset - 10,
    ];
    const startId = activeId;
    analyzeElnes(activeId, onset, fitWin)
      .then((r) => {
        if (useViewer.getState().activeId !== startId) return;
        setElnes(r);
        setStatus(
          `ELNES: jump ${r.edge_jump.toExponential(2)} · onset ${r.edge_onset.toFixed(1)} eV`,
        );
      })
      .catch((e: Error) => setStatus(`ELNES: ${e.message}`));
  };
}
