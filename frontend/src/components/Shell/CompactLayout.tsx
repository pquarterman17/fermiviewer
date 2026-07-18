import { useEffect } from "react";

import { useViewer } from "../../store/viewer";

const COMPACT_QUERY = "(max-width: 1100px)";

/** Reclaim stage width on compact windows without preventing manual reopening. */
export default function CompactLayout() {
  useEffect(() => {
    const media = window.matchMedia(COMPACT_QUERY);
    const collapseLibrary = ({ matches }: Pick<MediaQueryList, "matches">) => {
      const store = useViewer.getState();
      if (matches && !store.leftCol) store.toggleLeft();
    };

    collapseLibrary(media);
    media.addEventListener("change", collapseLibrary);
    return () => media.removeEventListener("change", collapseLibrary);
  }, []);

  return null;
}
