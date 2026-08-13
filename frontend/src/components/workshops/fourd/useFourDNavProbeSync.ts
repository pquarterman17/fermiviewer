// Bridges the main-Stage "fourdnav" capture-mode pixel (store/viewer.ts)
// into this workshop's own probe state (store/fourd.ts's FourDProbe) —
// PLAN_4DSTEM #14 v2, the flagged follow-up to FourDWorkshop's v1 ("probe
// clicks are handled entirely on this workshop's own nav minimap canvas").
// Mirrors how useSpectrumProbe.ts consumes specnavPixel for the EELS/EDS
// workshops.
//
// The nav image registered on the main Stage (store/fourd.ts's
// showNavImage) has EXACTLY scan_shape pixels — it's the detector-summed
// intensity at every probe position — so a fourdnav pixel picked on it is
// already a scan position; only the 1-based -> 0-based conversion
// (pointerDecisions.ts's scanPositionFromPixel) applies, no calibration.
//
// Gated on the nav image genuinely being the active Stage image
// (activeId === navMeta.id): captureMode stays "fourdnav" even if the user
// switches the active image to something else, and a pixel picked on an
// unrelated image must not be reinterpreted as a 4D scan position.

import { useEffect } from "react";

import { scanPositionFromPixel } from "../../Stage/pointerDecisions";
import { useFourD } from "../../../store/fourd";
import { useViewer } from "../../../store/viewer";

export function useFourDNavProbeSync(): void {
  const captureMode = useViewer((s) => s.captureMode);
  const fourdNavPixel = useViewer((s) => s.fourdNavPixel);
  const activeId = useViewer((s) => s.activeId);
  const navMeta = useFourD((s) => s.navMeta);
  const setProbe = useFourD((s) => s.setProbe);

  // Leaving the tool window (or the app navigating away) must not strand
  // the main Stage in fourdnav mode — same cleanup useSpectrumProbe.ts does
  // for specnav.
  useEffect(
    () => () => {
      const viewer = useViewer.getState();
      if (viewer.captureMode === "fourdnav") viewer.setCaptureMode("none");
    },
    [],
  );

  useEffect(() => {
    if (captureMode !== "fourdnav" || !fourdNavPixel || !navMeta) return;
    if (activeId !== navMeta.id) return;
    setProbe(scanPositionFromPixel(fourdNavPixel));
  }, [captureMode, fourdNavPixel, activeId, navMeta, setProbe]);
}
