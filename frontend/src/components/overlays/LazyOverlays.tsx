import { lazy, Suspense, type ReactNode } from "react";
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

  // One boundary PER overlay, never a shared one. Overlays stack (BatchDialog
  // awaits askParams -> ParamDialog), and a shared boundary re-suspends on the
  // second chunk: React hides the already-committed dialog and tears down its
  // effects, so the open dialog blanks and its focus state is lost.
  return (
    <>
      <Boundary>{open.batch && <BatchDialog />}</Boundary>
      <Boundary>{open.calibrations && <CalibrationManager />}</Boundary>
      <Boundary>{open.export && <ExportDialog />}</Boundary>
      <Boundary>{open.folder && <FolderOpenDialog />}</Boundary>
      <Boundary>{open.gallery && <GalleryGrid />}</Boundary>
      <Boundary>{open.metadata && <MetadataDialog />}</Boundary>
      <Boundary>{params && <ParamDialog />}</Boundary>
      <Boundary>{open.preferences && <PrefsWindow />}</Boundary>
      <Boundary>{open.shortcuts && <ShortcutsOverlay />}</Boundary>
    </>
  );
}

function Boundary({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>;
}
