// Diffraction workshop elliptical-distortion calibration flow (Diffraction
// #1), extracted verbatim from DiffractionWorkshop.tsx (MAIN_PLAN item 1,
// pin graduation). The body is unchanged; `setBusy` is threaded in because
// calibrate shares the workshop's single busy flag with detect/index/
// simulate, and `simPhase` is threaded in because calibrate falls back to
// the Simulate tab's selected phase when no known d-spacing is typed.

import { type Dispatch, type SetStateAction, useCallback, useState } from "react";

import { diffractionCalibrate, type CalibrationResult } from "../../../lib/api";

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
): DiffractionCalibrationState {
  const [calKnownD, setCalKnownD] = useState("");
  const [calib, setCalib] = useState<CalibrationResult | null>(null);

  // ── elliptical-distortion calibration (Diffraction #1) ────────────
  const calibrate = useCallback(() => {
    if (!activeId) return;
    const dKnown = Number(calKnownD);
    setBusy(true);
    diffractionCalibrate(activeId, {
      dKnownAng: dKnown > 0 ? dKnown : undefined,
      standardPhase: dKnown > 0 ? undefined : simPhase || undefined,
      hkl: dKnown > 0 ? undefined : [1, 1, 1],
      rMin: Number(minRadius) || 5,
    })
      .then((r) => {
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
      .catch((e: Error) => setStatus(`calibrate: ${e.message}`))
      .finally(() => setBusy(false));
  }, [activeId, calKnownD, simPhase, minRadius, setStatus, setBusy]);

  return { calKnownD, setCalKnownD, calib, calibrate };
}
