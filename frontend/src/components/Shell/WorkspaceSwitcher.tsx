// Menu-bar workspace switcher (design WS4b). Shows the current named
// workspace and a dropdown to switch / save / delete. A workspace is the
// existing session serializer's payload, addressed by name and kept under
// the OS config dir — this only adds the chrome; the store actions
// (saveWorkspaceNamed / loadWorkspaceNamed) own the I/O.

import { useEffect, useRef, useState } from "react";

import {
  deleteWorkspace,
  listWorkspaces,
  type WorkspaceInfo,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import Icon from "../icons/Icon";

export default function WorkspaceSwitcher() {
  const current = useViewer((s) => s.currentWorkspace);
  const hasImages = useViewer((s) => s.order.length > 0);
  const setStatus = useViewer((s) => s.setStatus);
  const saveNamed = useViewer((s) => s.saveWorkspaceNamed);
  const loadNamed = useViewer((s) => s.loadWorkspaceNamed);

  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<WorkspaceInfo[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  const refresh = () =>
    listWorkspaces()
      .then(setItems)
      .catch((e: Error) => setStatus(`workspaces: ${e.message}`));

  // refresh the list each time the menu opens, and close on outside click
  useEffect(() => {
    if (!open) return;
    void refresh();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const onSwitch = (w: WorkspaceInfo) => {
    setOpen(false);
    if (w.slug === current?.slug) return; // already active
    loadNamed(w.slug).catch((e: Error) => setStatus(`open: ${e.message}`));
  };

  const onSave = () => {
    setOpen(false);
    if (!hasImages) {
      setStatus("nothing to save — open an image first");
      return;
    }
    const name = window.prompt(
      "Save current layout as workspace:",
      current?.name ?? "",
    );
    if (name && name.trim())
      saveNamed(name.trim()).catch((e: Error) => setStatus(`save: ${e.message}`));
  };

  const onDelete = (e: React.MouseEvent, w: WorkspaceInfo) => {
    e.stopPropagation(); // don't also switch to the row being deleted
    if (!window.confirm(`Delete workspace “${w.name}”?`)) return;
    deleteWorkspace(w.slug)
      .then(() => {
        if (w.slug === current?.slug)
          useViewer.setState({ currentWorkspace: null });
        void refresh();
        setStatus(`deleted workspace “${w.name}”`);
      })
      .catch((err: Error) => setStatus(`delete: ${err.message}`));
  };

  return (
    <div className="fvd-workspace" ref={ref}>
      <button
        className={`fvd-workspace-chip${open ? " open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        data-tip="Switch or save workspace"
      >
        <Icon name="workspace" />
        <span className="name">{current?.name ?? "Default"}</span>
        <Icon name="chevron-down" size={12} />
      </button>
      {open && (
        <div className="fvd-menu-dropdown fvd-workspace-menu">
          <div className="fvd-menu-section">Workspaces</div>
          {items.length === 0 && (
            <div className="fvd-menu-entry disabled">
              <span>No saved workspaces</span>
            </div>
          )}
          {items.map((w) => (
            <div
              key={w.slug}
              className="fvd-menu-entry"
              // The check glyph became an aria-hidden SVG, so the active
              // workspace needs a non-visual marker of its own.
              aria-current={w.slug === current?.slug ? "true" : undefined}
              onMouseDown={(ev) => {
                ev.stopPropagation();
                onSwitch(w);
              }}
            >
              <span>
                {w.slug === current?.slug && <Icon name="check" size={14} />}
                {w.name}
              </span>
              <span
                className="fvd-workspace-del"
                title="Delete workspace"
                onMouseDown={(ev) => onDelete(ev, w)}
              >
                <Icon name="close" size={14} />
              </span>
            </div>
          ))}
          <div className="fvd-menu-sep" />
          <div
            className="fvd-menu-entry"
            onMouseDown={(ev) => {
              ev.stopPropagation();
              onSave();
            }}
          >
            <span><Icon name="plus" size={14} /> Save current layout…</span>
          </div>
        </div>
      )}
    </div>
  );
}
