import { lazy } from "react";

import { useStageInfo } from "../../store/stage";
import ChunkBoundary from "../ChunkBoundary";

// The profile chart carries uPlot; fetch it with the first profile drawn
// rather than on first paint.
const DockPlot = lazy(() => import("./DockPlot"));

export default function ProfileDock() {
  const hasProfile = useStageInfo((s) => s.profile !== null);
  if (!hasProfile) return null;
  return (
    <ChunkBoundary label="Profile plot" className="fvd-glass floating">
      <DockPlot />
    </ChunkBoundary>
  );
}
