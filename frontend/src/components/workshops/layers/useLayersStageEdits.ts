// The Layers workshop's half of the stage-overlay conversation.
//
// Split out of `LayersWorkshop.tsx` when the tilt handle pushed that module
// past the 500-line guard, along a seam that was already there: everything
// here answers "the stage published something — what does the workshop run
// now", and nothing here draws or owns analysis parameters.
//
// The two requests are deliberately separate channels. Moving an interface
// keeps the profile and re-measures within it (`editLayers`); changing the
// tilt RE-COLLAPSES the profile, so the old interface depths describe a
// curve that no longer exists and the run has to start from detection
// again. Applying both at once would read dragged depths against a frame
// they were never measured in.

import { useEffect } from "react";

import { useViewer } from "../../../store/viewer";

export function useLayersStageEdits({
  ready,
  onPositions,
  onTilt,
}: {
  /** false until a result exists — a stage edit before the first run has
      no profile to be a depth in */
  ready: boolean;
  onPositions: (positions: number[]) => void;
  onTilt: (tiltDeg: number) => void;
}): void {
  const layersEditReq = useViewer((s) => s.layersEditReq);
  const setLayersEditReq = useViewer((s) => s.setLayersEditReq);
  const layersTiltReq = useViewer((s) => s.layersTiltReq);
  const setLayersTiltReq = useViewer((s) => s.setLayersTiltReq);

  useEffect(() => {
    if (layersEditReq && ready) {
      onPositions(layersEditReq);
      setLayersEditReq(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersEditReq]);

  useEffect(() => {
    if (layersTiltReq === null) return;
    onTilt(layersTiltReq);
    setLayersTiltReq(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layersTiltReq]);
}
