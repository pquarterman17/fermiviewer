// Active-image load for the stage: fetch the raw uint16 raster for the
// current image (or the current cube frame), push it to the GPU, and seed
// the display window from the file's own metadata / Preferences.
//
// Extracted verbatim from Stage.tsx — this is the one self-contained effect
// cluster there that needs no stage-local closure beyond the two renderer
// refs and the three pieces of state it fills in. Everything else it reads
// (active image, frame index, display/status setters) it subscribes itself,
// so the call site stays five stable references wide.

import { useEffect, type Dispatch, type SetStateAction } from "react";

import { loadImagePixels } from "../../gl/loadPixels";
import type { GLRenderer } from "../../gl/render";
import { type Raster16 } from "../../lib/api";
import { autoWindow } from "../../lib/display";
import { type Size } from "../../lib/geometry";
import { loadPrefs } from "../../lib/prefs";
import { useStageInfo } from "../../store/stage";
import { useViewer, type Measure } from "../../store/viewer";
import { type Pt } from "./stageUtils";

export interface StageImageLoadCtx {
  glRef: { current: GLRenderer | null };
  rasterRef: { current: Raster16 | null };
  setImgSize: Dispatch<SetStateAction<Size | null>>;
  setPending: Dispatch<
    SetStateAction<{ kind: Measure["kind"]; pts: Pt[] } | null>
  >;
  setNFrames: Dispatch<SetStateAction<number | null>>;
}

/** Loads the active image (raw uint16 → GPU). Re-fetches when the stack
 *  frame index changes. Returns nothing: the raster lands in `rasterRef`
 *  plus the stage-info store, the size/frame-count in the passed setters. */
export function useStageImageLoad({
  glRef,
  rasterRef,
  setImgSize,
  setPending,
  setNFrames,
}: StageImageLoadCtx): void {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  // -1 = the energy SUM view (the sensible cube overview). Defaulting to a
  // channel index showed channel 0 (~0 keV, empty for EDS) as a black stage
  // while the filmstrip's summed /render looked fine.
  const stackFrame = useViewer((s) =>
    s.activeId ? (s.stackFrames[s.activeId] ?? -1) : -1,
  );
  const setDisplay = useViewer((s) => s.setDisplay);
  const setStatus = useViewer((s) => s.setStatus);
  const setRaster = useStageInfo((s) => s.setRaster);
  const setProfile = useStageInfo((s) => s.setProfile);

  const rasterless = meta?.kind === "spectrum";

  useEffect(() => {
    setImgSize(null);
    setPending(null);
    setProfile(null);
    rasterRef.current = null;
    setRaster(null);
    if (!activeId || rasterless) {
      glRef.current?.clear();
      // no raster → no stack: drop the stale StackStepper overlay + ,/. wiring
      setNFrames(null);
      return;
    }
    const isStack = meta?.kind === "spectrum_image";
    // frame < 0 → omit the param so the backend returns the energy sum
    const frameArg = isStack && stackFrame >= 0 ? stackFrame : undefined;
    let alive = true;
    // the getter returns null once this effect is stale, so a late response
    // can never upload an outdated image over the current one
    loadImagePixels(() => (alive ? glRef.current : null), activeId, meta?.kind, frameArg)
      .then((loaded) => {
        if (!alive || !loaded) return;
        const { w, h, raster: r } = loaded;
        rasterRef.current = r;
        setRaster(r);
        setNFrames(r?.nFrames ?? null);
        setImgSize({ w, h });
        // colour composites have no window to seed — their pixels ARE the
        // display values (ADR 0003), so the whole seeding block is scalar-only
        if (!r) return;
        // honor DM-saved display window on first load (checklist I)
        const st = useViewer.getState();
        if (!st.display[activeId] && st.images[activeId]) {
          const m = st.images[activeId].meta;
          const dl = m["display_low"];
          const dh = m["display_high"];
          const dg = m["display_gamma"];
          const di = m["display_inverted"];
          // these are one-time seeds on first display, not user actions —
          // mark them silent so they fold into the "Opened" history step
          // (WS4d) instead of logging a spurious "Contrast"/"Invert"
          if (typeof dl === "number" && typeof dh === "number" && dh > dl) {
            const span = r.vmax - r.vmin || 1;
            setDisplay(
              activeId,
              {
                lo: Math.max(0, (dl - r.vmin) / span),
                hi: Math.min(1, (dh - r.vmin) / span),
                gamma: typeof dg === "number" && dg > 0 ? dg : 1,
                invert: di === true,
              },
              { silent: true },
            );
          } else if (di === true) {
            setDisplay(activeId, { invert: true }, { silent: true });
          } else {
            // no embedded display window — auto-contrast on open if enabled
            // in Preferences (otherwise leave the full 0–1 range)
            const prefs = loadPrefs();
            if (prefs.autoContrastOnOpen) {
              setDisplay(
                activeId,
                autoWindow(r, prefs.autoLoPct, prefs.autoHiPct),
                { silent: true },
              );
            }
          }
        }
      })
      .catch((e: Error) => {
        if (alive) setStatus(`load failed: ${e.message}`);
      });
    return () => {
      alive = false;
    };
  }, [
    activeId,
    rasterless,
    stackFrame,
    meta?.kind,
    setDisplay,
    setProfile,
    setRaster,
    setStatus,
    glRef,
    rasterRef,
    setImgSize,
    setPending,
    setNFrames,
  ]);
}
