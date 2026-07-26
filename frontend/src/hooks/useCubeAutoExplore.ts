import { useCallback, useEffect, useRef, useState } from "react";

import type { ImageMeta } from "../lib/api";
import {
  resolveSpectralModality,
  saveSpectralModality,
  type SpectralModality,
} from "../lib/spectralModality";
import { useViewer } from "../store/viewer";

/**
 * When a spectrum-image cube first becomes active, route it to the appropriate
 * EELS or EDS workspace. Ambiguous cubes are returned to the app for an
 * explicit choice instead of silently treating every spectral cube as EDS.
 *
 * Fires once per image (tracked by id) so re-selecting a cube the user has
 * since closed the explorer for doesn't force it back open. The raw channel
 * stepper on the Stage stays available — this only surfaces the explorer.
 */
export interface CubeAutoExplore {
  pending: ImageMeta | null;
  choose: (modality: SpectralModality) => void;
  dismiss: () => void;
}

export function useCubeAutoExplore(): CubeAutoExplore {
  const activeId = useViewer((s) => s.activeId);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const openTool = useViewer((s) => s.openTool);
  const explored = useRef<Set<string>>(new Set());
  const [pending, setPending] = useState<ImageMeta | null>(null);

  useEffect(() => {
    if (!activeId || meta?.kind !== "spectrum_image") {
      setPending(null);
      return;
    }
    if (explored.current.has(activeId)) return;
    explored.current.add(activeId);
    const classification = resolveSpectralModality(meta);
    if (classification.modality) {
      openTool(classification.modality);
      setPending(null);
    } else {
      setPending(meta);
    }
  }, [activeId, meta, openTool]);

  const choose = useCallback(
    (modality: SpectralModality) => {
      if (!pending) return;
      saveSpectralModality(pending, modality);
      openTool(modality);
      setPending(null);
    },
    [openTool, pending],
  );

  const dismiss = useCallback(() => setPending(null), []);
  return { pending, choose, dismiss };
}
