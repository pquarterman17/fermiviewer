import { lazy, Suspense } from "react";
import { useShallow } from "zustand/react/shallow";

import { useParamDialog } from "../../store/params";
import { useViewer } from "../../store/viewer";

const BatchDialog = lazy(() => import("./BatchDialog"));
const CalibrationManager = lazy(() => import("./CalibrationManager"));
const ExportDialog = lazy(() => import("./ExportDialog"));
const FolderOpenDialog = lazy(() => import("./FolderOpenDialog"));
const GalleryGrid = lazy(() => import("./GalleryGrid"));
const MetadataDialog = lazy(() => import("./MetadataDialog"));
const ParamDialog = lazy(() => import("./ParamDialog"));
const PrefsWindow = lazy(() => import("./PrefsWindow"));
const ShortcutsOverlay = lazy(() => import("./ShortcutsOverlay"));

/** Mount modal code only after its corresponding open state is requested. */
export default function LazyOverlays() {
  const open = useViewer(
    useShallow((state) => ({
      batch: state.batchOpen,
      calibrations: state.calibOpen,
      export: state.exportOpen,
      folder: state.folderOpen,
      gallery: state.galleryOpen,
      metadata: state.metaOpen,
      preferences: state.prefsOpen,
      shortcuts: state.shorts,
    })),
  );
  const params = useParamDialog((state) => state.title !== null);

  return (
    <Suspense fallback={null}>
      {open.batch && <BatchDialog />}
      {open.calibrations && <CalibrationManager />}
      {open.export && <ExportDialog />}
      {open.folder && <FolderOpenDialog />}
      {open.gallery && <GalleryGrid />}
      {open.metadata && <MetadataDialog />}
      {params && <ParamDialog />}
      {open.preferences && <PrefsWindow />}
      {open.shortcuts && <ShortcutsOverlay />}
    </Suspense>
  );
}
