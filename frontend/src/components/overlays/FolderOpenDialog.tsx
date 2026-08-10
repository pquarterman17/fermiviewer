// Launch-folder Open dialog. The OS-native file picker can't be pointed
// at a directory by the page, so when the app is launched from a folder
// (`fermiviewer <dir>` / the launch cwd) we offer its supported images
// here, pre-selected and one click from open. A "Browse…" escape hatch
// falls back to the native picker for anywhere else on disk.

import { useEffect, useRef, useState } from "react";

import { supportedExtensions } from "../../lib/api";
import { importFolders } from "../../lib/folderImport";
import { useViewer } from "../../store/viewer";
import ModalDialog from "./ModalDialog";

export default function FolderOpenDialog() {
  const open = useViewer((s) => s.folderOpen);
  const setOpen = useViewer((s) => s.setFolderOpen);
  const ctx = useViewer((s) => s.launchContext);
  const openPaths = useViewer((s) => s.openPaths);
  const openFiles = useViewer((s) => s.openFiles);
  const setStatus = useViewer((s) => s.setStatus);

  const files = ctx?.files ?? [];
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [accept, setAccept] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  // one absolute folder path per line; imported as one group per folder
  // (or a single merged group, per PROJECT_WORKFLOW_PLAN.md items 2-3)
  const [folderPaths, setFolderPaths] = useState("");
  const [mergeFolders, setMergeFolders] = useState(false);
  const folderPathList = folderPaths
    .split("\n")
    .map((p) => p.trim())
    .filter(Boolean);

  // default every file selected whenever the dialog opens or the launch
  // folder changes (ctx is a stable store ref, so this won't loop)
  useEffect(() => {
    if (open) setSel(new Set((ctx?.files ?? []).map((f) => f.path)));
  }, [open, ctx]);

  // reset the folder-import fields each time the dialog opens
  useEffect(() => {
    if (open) {
      setFolderPaths("");
      setMergeFolders(false);
    }
  }, [open]);

  // accept filter for the Browse fallback (same source as the menu picker)
  useEffect(() => {
    supportedExtensions()
      .then((exts) => setAccept(exts.join(",")))
      .catch(() => undefined);
  }, []);

  if (!open) return null;

  const toggle = (path: string) =>
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const openSelected = () => {
    const paths = files.filter((f) => sel.has(f.path)).map((f) => f.path);
    if (paths.length === 0) return;
    setOpen(false);
    openPaths(paths).catch((e: Error) => setStatus(e.message));
  };

  const onBrowse = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files;
    if (picked && picked.length > 0) {
      setOpen(false);
      openFiles(picked).catch((err: Error) => setStatus(err.message));
    }
    e.target.value = "";
  };

  const importSelectedFolders = () => {
    if (folderPathList.length === 0) return;
    setOpen(false);
    importFolders(folderPathList, { merge: mergeFolders }).catch((e: Error) =>
      setStatus(e.message),
    );
  };

  return (
    <ModalDialog
      ariaLabel="Open from folder"
      className="fvd-folder"
      onClose={() => setOpen(false)}
    >
        <h2>Open from folder</h2>
        {ctx?.dir && <div className="fvd-folder-path">{ctx.dir}</div>}

        {files.length === 0 ? (
          <div className="fvd-folder-empty">
            No supported images in this folder.
          </div>
        ) : (
          <ul className="fvd-folder-list">
            {files.map((f) => (
              <li key={f.path}>
                <label>
                  <input
                    type="checkbox"
                    checked={sel.has(f.path)}
                    onChange={() => toggle(f.path)}
                  />
                  <span className="name">{f.name}</span>
                </label>
              </li>
            ))}
          </ul>
        )}

        <div className="fvd-folder-import">
          <label htmlFor="fvd-folder-paths">Import folder(s)</label>
          <textarea
            id="fvd-folder-paths"
            className="fvd-folder-paths"
            rows={3}
            placeholder={"One folder per line, e.g.\n/data/study/400C\n/data/study/500C"}
            value={folderPaths}
            onChange={(e) => setFolderPaths(e.target.value)}
          />
          <label className="fvd-check">
            <input
              type="checkbox"
              checked={mergeFolders}
              onChange={(e) => setMergeFolders(e.target.checked)}
            />
            Merge into one group
          </label>
          <p className="fvd-folder-hint">
            Each folder recurses fully: its own images become one group,
            each first-level subfolder becomes another (nested under a new
            project when there's more than one). Unsupported files are
            skipped and counted; imports cap at 500 files.
          </p>
          <div className="fvd-btn-row">
            <button
              className="fvd-btn primary"
              disabled={folderPathList.length === 0}
              onClick={importSelectedFolders}
              title="Import the listed folder(s) as image group(s)"
            >
              Import folder{folderPathList.length > 1 ? "s" : ""}
              {folderPathList.length > 0 ? ` (${folderPathList.length})` : ""}
            </button>
          </div>
        </div>

        <input
          ref={fileRef}
          type="file"
          multiple
          accept={accept || undefined}
          style={{ display: "none" }}
          onChange={onBrowse}
        />
        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={() => fileRef.current?.click()}
            title="Open the system file picker"
          >
            Browse elsewhere…
          </button>
          <button
            className="fvd-btn"
            onClick={() => setOpen(false)}
            title="Cancel and close (Esc)"
          >
            Cancel
          </button>
          <button
            className="fvd-btn primary"
            disabled={sel.size === 0}
            onClick={openSelected}
            autoFocus
            title="Open the selected file(s) (Enter)"
          >
            Open {sel.size > 0 ? `(${sel.size})` : ""}
          </button>
        </div>
    </ModalDialog>
  );
}
