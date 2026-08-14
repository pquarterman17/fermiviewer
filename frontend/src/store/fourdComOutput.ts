// COM / DPC / iDPC output action for the FourD workshop (PLAN_4DSTEM #9) —
// split out of fourd.ts, mirroring viewerCloseImage.ts's
// createXAction(set, get) slice pattern, to keep fourd.ts under the
// 500-line ceiling. Unlike the aperture-based virtual-detector path
// (BF/ABF/ADF/Custom, `computeMap` in fourd.ts), these three modes share
// no radii/shape and don't all register the same number of maps — /com
// registers TWO images, /dpc THREE, /idpc ONE — so they get their own
// action here rather than being squeezed into computeMap's
// single-ImageMeta response shape.
//
// Only TYPES are imported from fourd.ts (`import type`, erased entirely at
// compile time), so this file never becomes a runtime import cycle with
// it even though fourd.ts imports THIS file's `createComOutputAction` at
// runtime.

import type { StateCreator } from "zustand";

import { computeCom, computeDpc, computeIdpc, FourDNotFoundError } from "../lib/api";
import type { ApertureMode, FourDState } from "./fourd";
import { useViewer } from "./viewer";

type Set = Parameters<StateCreator<FourDState>>[0];
type Get = Parameters<StateCreator<FourDState>>[1];

/** Cycles per scan pixel (fftfreq-native units; Nyquist == 0.5) — mirrors
 *  `calc/fourd/idpc.py`'s `DEFAULT_HIGH_PASS_CUTOFF`; keep the two in
 *  sync. This is a UI default only, always sent EXPLICITLY on the wire
 *  (never inferred server-side via an omitted field) — matching this
 *  store's own "every field always present" convention for request
 *  bodies elsewhere (see e.g. `computeMap` in fourd.ts). */
export const DEFAULT_HIGH_PASS_CUTOFF = 0.02;

/** COM/DPC/iDPC share the descan-center contract but carry none of
 *  BF/ABF/ADF/Custom's radii/shape fields — this is the aperture-mode
 *  segmented control's OTHER family, driven by `computeComOutput` below
 *  instead of `computeMap`. */
export function isComOutputMode(mode: ApertureMode): mode is "com" | "dpc" | "idpc" {
  return mode === "com" || mode === "dpc" || mode === "idpc";
}

/** Validate a COM/DPC/iDPC request against what the server will actually
 *  accept (mirrors ComRequest/DpcRequest/IdpcRequest in
 *  routes/fourd_com.py) — same "catch it before the wire" rationale as
 *  fourd.ts's own `apertureError`, kept as a SEPARATE function because
 *  these modes validate none of the radii/shape fields that one checks,
 *  and validate two fields (`mrad_per_px`/`high_pass_cutoff`) it has no
 *  concept of. Returns a user-facing reason, or null when safe to send. */
export function comOutputError(
  mode: ApertureMode,
  mradPerPx: number | null,
  highPassCutoff: number,
  autoCenter: boolean,
  centerKy: number | null,
  centerKx: number | null,
  detShape: readonly [number, number],
): string | null {
  if (!autoCenter) {
    if (
      centerKy == null || centerKx == null ||
      !Number.isFinite(centerKy) || !Number.isFinite(centerKx)
    ) {
      return "center (ky, kx) must be set when auto-center is off";
    }
    if (
      centerKy < 0 || centerKy > detShape[0] - 1 ||
      centerKx < 0 || centerKx > detShape[1] - 1
    ) {
      return "center (ky, kx) must be within the detector bounds";
    }
  }
  if (mode === "dpc" || mode === "idpc") {
    if (mradPerPx == null || !Number.isFinite(mradPerPx) || mradPerPx <= 0) {
      return "mrad/px calibration must be a value greater than 0";
    }
  }
  if (mode === "idpc" && (!Number.isFinite(highPassCutoff) || highPassCutoff < 0)) {
    return "high-pass cutoff must be 0 or greater";
  }
  return null;
}

export function createComOutputAction(
  set: Set,
  get: Get,
): Pick<FourDState, "computeComOutput"> {
  return {
    computeComOutput: async () => {
      const { selectedId, aperture, datasets, busyCompute } = get();
      if (!selectedId || busyCompute || !isComOutputMode(aperture.mode)) return;
      const mode = aperture.mode;
      const ds = datasets.find((d) => d.id === selectedId);
      const detShape: [number, number] = ds ? [ds.det_shape[0], ds.det_shape[1]] : [256, 256];
      const { mradPerPx, highPassCutoff, autoCenter, centerKy, centerKx } = aperture;
      const error = comOutputError(
        mode, mradPerPx, highPassCutoff, autoCenter, centerKy, centerKx, detShape,
      );
      if (error) {
        set({ status: `${mode}: ${error}` });
        return;
      }
      set({ busyCompute: true, status: `computing ${mode}…` });
      try {
        const dsName = ds?.name ?? selectedId;
        const center_ky = autoCenter ? null : centerKy;
        const center_kx = autoCenter ? null : centerKx;
        const name = `${mode}(${dsName})`;
        if (mode === "com") {
          const { comy, comx } = await computeCom(selectedId, { center_ky, center_kx, name });
          useViewer.getState().ingestDerived([comy, comx]);
        } else if (mode === "dpc") {
          // comOutputError already required mradPerPx to be a finite > 0
          // number for this mode — the cast reflects that already-checked
          // invariant rather than re-deriving it.
          const { magnitude, direction, divergence } = await computeDpc(selectedId, {
            center_ky, center_kx, mrad_per_px: mradPerPx as number, name,
          });
          useViewer.getState().ingestDerived([magnitude, direction, divergence]);
        } else {
          const meta = await computeIdpc(selectedId, {
            center_ky, center_kx, mrad_per_px: mradPerPx as number,
            high_pass_cutoff: highPassCutoff, name,
          });
          useViewer.getState().ingestDerived([meta]);
        }
        set({ status: `${mode} computed → ${name}` });
      } catch (e) {
        if (e instanceof FourDNotFoundError) await get().fetchDatasets();
        else set({ status: `${mode}: ${(e as Error).message}` });
      } finally {
        set({ busyCompute: false });
      }
    },
  };
}
