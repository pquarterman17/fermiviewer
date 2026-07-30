// Publishing the current energy-window map: into the image library, or
// straight into the workshop's composite overlay.
//
// Both actions re-request the same map with `save_derived` — the inline map
// the explorer previews is not registered anywhere, and `map_meta.id` is what
// the library and the composite engine fetch by. Extracted from
// EdsSpectrumImage so that shared request lives in one place and the explorer
// stays under the module-size ceiling.

import { useCallback, useState } from "react";

import { edsElementMap, type ImageMeta } from "../../lib/api";
import { setCustomColormap, type ColormapName } from "../../lib/colormaps";
import { elementColor } from "../../lib/eds/elementColors";
import { useViewer } from "../../store/viewer";
import type { MapPaint } from "./EdsElementMap";
import type { EdsMapBackground } from "./useEdsElementMap";

interface Options {
  imageId: string | null;
  eLo: number;
  eHi: number;
  bg: EdsMapBackground;
  e0Kev: number;
  /** "(custom)" or the selected element symbol. */
  element: string;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
  onAddToComposite?: (mapMeta: ImageMeta, element: string) => void;
}

export function useEdsDerivedMap({
  imageId,
  eLo,
  eHi,
  bg,
  e0Kev,
  element,
  isOpen,
  onStatus,
  onAddToComposite,
}: Options) {
  const [compositeBusy, setCompositeBusy] = useState(false);
  const [libraryBusy, setLibraryBusy] = useState(false);

  const request = useCallback(
    (id: string) =>
      edsElementMap(id, eLo, eHi, {
        bg,
        e0Kev: bg === "bremsstrahlung" ? e0Kev : undefined,
        saveDerived: true,
      }),
    [bg, e0Kev, eHi, eLo],
  );

  const addToComposite = useCallback(() => {
    const id = imageId;
    if (!id || !onAddToComposite || element === "(custom)") return;
    setCompositeBusy(true);
    request(id)
      .then((r) => {
        if (!isOpen(id)) return; // image removed mid-request; drop result
        if (r.map_meta) {
          onAddToComposite(r.map_meta, element);
          onStatus(id, `EDS composite: added ${element}`);
        }
      })
      .catch((e: Error) => onStatus(id, `EDS composite: ${e.message}`))
      .finally(() => setCompositeBusy(false));
  }, [element, imageId, isOpen, onAddToComposite, onStatus, request]);

  const addToLibrary = useCallback(
    (paint: MapPaint) => {
      const id = imageId;
      if (!id) return;
      // The element tint is generated per element rather than being one of the
      // shared named colormaps, so carrying it onto a library image means
      // publishing it through the "custom" colormap slot.
      const named: ColormapName = paint === "element" ? "custom" : paint;
      if (paint === "element") {
        setCustomColormap(`#000000, ${elementColor(element)}, #ffffff`);
      }
      setLibraryBusy(true);
      request(id)
        .then((result) => {
          if (!isOpen(id) || !result.map_meta) return;
          const store = useViewer.getState();
          store.ingestDerived([result.map_meta]);
          store.setDisplay(result.map_meta.id, { cmap: named }, { silent: true });
          store.setActive(id);
          onStatus(
            id,
            paint === "element"
              ? `EDS map added to library in the ${element} colour`
              : `EDS map added to library with ${named} colormap`,
          );
        })
        .catch((e: Error) => onStatus(id, `EDS library: ${e.message}`))
        .finally(() => setLibraryBusy(false));
    },
    [element, imageId, isOpen, onStatus, request],
  );

  return { compositeBusy, libraryBusy, addToComposite, addToLibrary };
}
