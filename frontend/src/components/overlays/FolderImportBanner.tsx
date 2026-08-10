// Persistent folder-import outcome banner (PROJECT_WORKFLOW_PLAN.md item 5:
// "unmissable rather than a transient status line"). Mounted once at the
// App level so it survives FolderOpenDialog closing the instant Import is
// clicked (see FolderOpenDialog.test.tsx's "imports the typed folder
// paths" — that close-on-click behavior is asserted and unchanged), and
// equally covers a dropped-folder import (item 4), which has no dialog to
// live in at all. Both entry points report through the same
// store/folderImportNotice.ts via lib/folderImport.ts's
// `applyFolderImport`, so this is the ONE place either outcome surfaces.
//
// Stays up until the user dismisses it — unlike the status bar line,
// which the very next unrelated status message silently overwrites.

import { summarizeImport } from "../../lib/folderImport";
import { useFolderImportNotice } from "../../store/folderImportNotice";

export default function FolderImportBanner() {
  const result = useFolderImportNotice((s) => s.result);
  const clear = useFolderImportNotice((s) => s.clear);
  if (!result) return null;

  const notable =
    result.skipped > 0 || result.truncated || result.emptyFolders.length > 0;

  return (
    <div
      className={`fvd-glass fvd-import-banner${notable ? " notable" : ""}`}
      role="status"
    >
      <span>{summarizeImport(result)}</span>
      <button className="fvd-icon-btn" title="Dismiss" onClick={clear}>
        ✕
      </button>
    </div>
  );
}
