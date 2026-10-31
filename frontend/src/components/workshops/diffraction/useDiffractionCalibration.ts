// Diffraction workshop elliptical-distortion calibration flow (Diffraction
// #1), extracted verbatim from DiffractionWorkshop.tsx (MAIN_PLAN item 1,
// pin graduation). The body is unchanged; `setBusy` is threaded in because
// calibrate shares the workshop's single busy flag with detect/index/
// simulate, and `simPhase` is threaded in because calibrate falls back to
// the Simulate tab's selected phase when no known d-spacing is typed.
// `beginRequest` is the workshop's image-scoped request channel, so a fit
// that lands after the pattern changed is dropped like detect/index.

import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useState,
} from "react";

import type { RequestLease } from "../../../hooks/useLatestRequest";
import { diffractionCalibrate, type CalibrationResult } from "../../../lib/api";
import { useViewer } from "../../../store/viewer";

export interface DiffractionCalibrationState {
  calKnownD: string;
  setCalKnownD: Dispatch<SetStateAction<string>>;
  calib: CalibrationResult | null;
  calibrate: () => void;
}

export function useDiffractionCalibration(
  activeId: string | null,
  simPhase: string,
  minRadius: string,
  setStatus: (msg: string) => void,
  setBusy: Dispatch<SetStateAction<boolean>>,
  beginRequest: () => RequestLease,
): DiffractionCalibrationState {
  const [calKnownD, setCalKnownD] = useState("");
  const [calib, setCalib] = useState<CalibrationResult | null>(null);

  // a fit describes one pattern's ring geometry
  useEffect(() => setCalib(null), [activeId]);

  // ── elliptical-distortion calibration (Diffraction #1) ────────────
  const calibrate = useCallback(() => {
    if (!activeId) return;
    const sourceId = activeId;
    const request = beginRequest();
    const current = () =>
      request.isCurrent() && useViewer.getState().activeId === sourceId;
    const dKnown = Number(calKnownD);
    setBusy(true);
    diffractionCalibrate(sourceId, {
      dKnownAng: dKnown > 0 ? dKnown : undefined,
      standardPhase: dKnown > 0 ? undefined : simPhase || undefined,
      hkl: dKnown > 0 ? undefined : [1, 1, 1],
      rMin: Number(minRadius) || 5,
      signal: request.signal,
    })
      .then((r) => {
        if (!current()) return;
        setCalib(r);
        const e = r.ellipse;
        setStatus(
          `calibrate: ecc ${e.eccentricity.toFixed(3)} · ` +
            `a/b ${e.a.toFixed(1)}/${e.b.toFixed(1)} px · ` +
            `RMS ${r.rms_residual_px.toFixed(2)} px` +
            (r.camera_constant_px_ang
              ? ` · C ${r.camera_constant_px_ang.toFixed(1)} px·Å`
              : ""),
        );
      })
      .catch((e: Error) => {
        if (current()) setStatus(`calibrate: ${e.message}`);
      })
      .finally(() => {
        if (current()) setBusy(false);
      });
  }, [activeId, calKnownD, simPhase, minRadius, setStatus, setBusy, beginRequest]);

  return { calKnownD, setCalKnownD, calib, calibrate };
}
