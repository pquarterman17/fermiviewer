import { useEffect, useRef } from "react";

import { useViewer } from "../store/viewer";

/**
 * When an EDS spectrum-image cube first becomes the active image, open the EDS
 * Spectrum-Image Explorer automatically so the user lands on the spectrum +
 * element maps instead of scrolling thousands of raw energy channels.
 *
 * Fires once per image (tracked by id) so re-selecting a cube the user has
 * since closed the explorer for doesn't force it back open. The raw channel
 * stepper on the Stage stays available — this only surfaces the explorer.
 */
export function useCubeAutoExplore(): void {
  const activeId = useViewer((s) => s.activeId);
  const kind = useViewer((s) =>
    s.activeId ? (s.images[s.activeId]?.kind ?? null) : null,
  );
  const openTool = useViewer((s) => s.openTool);
  const explored = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!activeId || kind !== "spectrum_image") return;
    if (explored.current.has(activeId)) return;
    explored.current.add(activeId);
    openTool("eds");
  }, [activeId, kind, openTool]);
}
