// Launch-folder Open dialog. The OS-native file picker can't be pointed
// at a directory by the page, so when the app is launched from a folder
// (`fermiviewer <dir>` / the launch cwd) we offer its supported images
// here, pre-selected and one click from open. A "Browse…" escape hatch
// falls back to the native picker for anywhere else on disk.

import { useEffect, useRef, useState } from "react";

import { useViewer } from "../../store/viewer";

export default function FolderOpenDialog() {
  const open = useViewer((s) => s.folderOpen);
  const setOpen = useViewer((s) => s.setFolderOpen);
  const ctx = useViewer((s) => s.launchContext);
  const openPaths = useViewer((s) => s.openPaths);
  const openFiles = useViewer((s) => s.openFiles);
  const setStatus = useViewer((s) => s.setStatus);

  const files = ctx?.files ?? [];
  const [sel, setSel] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  // default every file selected each time the dialog opens
  useEffect(() => {
    if (open) setSel(new Set(files.map((f) => f.path)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Esc closes
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

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

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
      <div
        className="fvd-glass fvd-folder"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Open from folder"
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

        <input
          ref={fileRef}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={onBrowse}
        />
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={() => fileRef.current?.click()}>
            Browse…
          </button>
          <button className="fvd-btn" onClick={() => setOpen(false)}>
            Cancel
          </button>
          <button
            className="fvd-btn primary"
            disabled={sel.size === 0}
            onClick={openSelected}
          >
            Open {sel.size > 0 ? `(${sel.size})` : ""}
          </button>
        </div>
      </div>
    </div>
  );
}
