// The Layers workshop's three server round-trips: Analyze, an interface
// edit, and Level (rotate, then re-analyze the rotated copy).
//
// Split out of `LayersWorkshop.tsx` so the request ownership lives in one
// place. Analyze and edits describe one image and analysis region, so they
// share a channel scoped to both: a response that lands after either
// changes is dropped (result, error and busy reset alike). Level hands the
// analysis over to the rotated copy it creates, so it cannot live in that
// source-scoped channel; it checks the image it is waiting on instead, and
// Analyze/edit supersede it.

import { type Dispatch, type SetStateAction } from "react";

import type { AnalysisRoi } from "../../../hooks/useAnalysisRoi";
import { useLatestRequest } from "../../../hooks/useLatestRequest";
import {
  analyzeLayers,
  applyFilter,
  editLayers,
  type LayersResult,
} from "../../../lib/api";
import { useViewer } from "../../../store/viewer";

export interface LayersRunParams {
  axis: "auto" | "y" | "x";
  modality: "haadf" | "eels" | "bf" | "df";
  sensitivity: string;
  nLayers: string;
  waviness: boolean;
  decurtain: boolean;
  saveResult: boolean;
}

export function useLayersRuns({
  activeId,
  roi,
  roiKey,
  result,
  tiltDeg,
  params,
  setBusy,
  setStatus,
  applyResult,
}: {
  activeId: string | null;
  roi: AnalysisRoi | null;
  roiKey: string;
  result: LayersResult | null;
  tiltDeg: number | null;
  params: LayersRunParams;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setStatus: (msg: string) => void;
  applyResult: (r: LayersResult, imageId: string, roi: AnalysisRoi | null) => void;
}) {
  const layersRequest = useLatestRequest(`${activeId ?? ""}|${roiKey}`);
  const levelRequest = useLatestRequest(null);
  const { axis, modality, sensitivity, nLayers, waviness, decurtain, saveResult } = params;

  const settle = <T>(
    promise: Promise<T>,
    current: () => boolean,
    label: string,
    onResult: (value: T) => void,
  ) => {
    setBusy(true);
    promise
      .then((value) => {
        if (current()) onResult(value);
      })
      .catch((e: Error) => {
        if (current()) setStatus(`${label}: ${e.message}`);
      })
      .finally(() => {
        if (current()) setBusy(false);
      });
  };

  /** A lease on the source-scoped channel; Level is superseded by it. */
  const sourceLease = (sourceId: string) => {
    const request = layersRequest.begin();
    levelRequest.invalidate();
    const current = () =>
      request.isCurrent() && useViewer.getState().activeId === sourceId;
    return { signal: request.signal, current };
  };

  const run = (tilt: number | null = tiltDeg) => {
    if (!activeId) return;
    const sourceId = activeId;
    const { signal, current } = sourceLease(sourceId);
    settle(
      analyzeLayers(sourceId, {
        tiltDeg: tilt,
        roi,
        axis,
        modality,
        sensitivity: Number(sensitivity) || 0.3,
        nLayers: Number(nLayers) || 0,
        waviness,
        reduce: decurtain ? "median" : "mean",
        destripe: decurtain,
        record: saveResult,
        signal,
      }),
      current,
      "Layers",
      (r) => applyResult(r, sourceId, roi),
    );
  };

  // recompute from an edited interface list (add / remove)
  const recompute = (positions: number[]) => {
    if (!activeId || !result) return;
    const sourceId = activeId;
    const { signal, current } = sourceLease(sourceId);
    settle(
      editLayers(sourceId, positions, {
        // the SAME tilt this result was collapsed along: the positions are
        // depths in that profile, so re-measuring under another angle would
        // read them against a different frame and move every one of them
        tiltDeg: result.applied_tilt_deg ?? null,
        roi,
        axis: result.axis === "x" ? "x" : "y",
        waviness,
        reduce: decurtain ? "median" : "mean",
        destripe: decurtain,
        // An edited run saves as its own record when saving is on, rather
        // than replacing the detected one: the distance between the two is
        // the finding (see routes/_layers_result.py).
        record: saveResult,
        signal,
      }),
      current,
      "Layers edit",
      (r) => applyResult(r, sourceId, roi),
    );
  };

  // rotate the image so layers become axis-aligned, then re-analyze it
  const levelImage = () => {
    if (!activeId || !result || result.tilt_deg == null) return;
    const angle = result.tilt_deg;     // + tilt levels (verified by the route test)
    const request = levelRequest.begin();
    layersRequest.invalidate();
    let waitingOn = activeId;
    const current = () =>
      request.isCurrent() && useViewer.getState().activeId === waitingOn;
    const levelled = applyFilter(activeId, "rotate", { angle }).then((meta) => {
      if (!current()) return;
      const viewer = useViewer.getState();
      viewer.ingestDerived([meta]);
      viewer.setActive(meta.id);
      waitingOn = meta.id;
      return analyzeLayers(meta.id, {
        axis,
        modality,
        sensitivity: Number(sensitivity) || 0.3,
        nLayers: Number(nLayers) || 0,
        waviness,
        reduce: decurtain ? "median" : "mean",
        destripe: decurtain,
      }).then((r) => {
        if (current()) applyResult(r, meta.id, null);
      });
    });
    settle(levelled, current, "Level", () => undefined);
  };

  return { run, recompute, levelImage };
}
