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
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRefs = useRef<Array<HTMLButtonElement | null>>([]);

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
    triggerRef.current?.focus();
    if (w.slug === current?.slug) return; // already active
    loadNamed(w.slug).catch((e: Error) => setStatus(`open: ${e.message}`));
  };

  const onSave = () => {
    setOpen(false);
    triggerRef.current?.focus();
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

  const onDelete = (w: WorkspaceInfo) => {
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

  const liveMenuItems = () =>
    menuRefs.current.filter((node): node is HTMLButtonElement => node != null);

  const focusMenuItem = (index: number) => {
    const refs = liveMenuItems();
    if (refs.length === 0) return;
    refs[(index + refs.length) % refs.length]?.focus();
  };

  const openFromKeyboard = (last = false) => {
    setOpen(true);
    requestAnimationFrame(() =>
      focusMenuItem(last ? liveMenuItems().length - 1 : 0),
    );
  };

  const onMenuKeyDown = (e: React.KeyboardEvent, index: number) => {
    const refs = liveMenuItems();
    if (e.key === "ArrowDown") focusMenuItem(index + 1);
    else if (e.key === "ArrowUp") focusMenuItem(index - 1);
    else if (e.key === "Home") focusMenuItem(0);
    else if (e.key === "End") focusMenuItem(refs.length - 1);
    else if (e.key === "Escape") {
      setOpen(false);
      triggerRef.current?.focus();
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <div className="fvd-workspace" ref={ref}>
      <button
        ref={triggerRef}
        className={`fvd-workspace-chip${open ? " open" : ""}`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") openFromKeyboard();
          else if (e.key === "ArrowUp") openFromKeyboard(true);
          else if (e.key === "Escape" && open) setOpen(false);
          else return;
          e.preventDefault();
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        data-tip="Switch or save workspace"
      >
        <Icon name="workspace" />
        <span className="name">{current?.name ?? "Default"}</span>
        <Icon name="chevron-down" size={12} />
      </button>
      {open && (
        <div
          className="fvd-menu-dropdown fvd-workspace-menu"
          role="menu"
          aria-label="Workspaces"
        >
          <div className="fvd-menu-section" role="presentation">Workspaces</div>
          {items.length === 0 && (
            <div className="fvd-menu-entry disabled" role="presentation">
              <span>No saved workspaces</span>
            </div>
          )}
          {items.map((w, itemIndex) => (
            <div key={w.slug} className="fvd-workspace-row" role="presentation">
              <button
                ref={(node) => {
                  menuRefs.current[itemIndex * 2] = node;
                }}
                className="fvd-menu-entry fvd-workspace-open"
                role="menuitem"
                aria-current={w.slug === current?.slug ? "true" : undefined}
                onClick={() => onSwitch(w)}
                onKeyDown={(e) => onMenuKeyDown(e, itemIndex * 2)}
              >
                <span>
                  {w.slug === current?.slug && <Icon name="check" size={14} />}
                  {w.name}
                </span>
              </button>
              <button
                ref={(node) => {
                  menuRefs.current[itemIndex * 2 + 1] = node;
                }}
                className="fvd-workspace-del"
                role="menuitem"
                aria-label={`Delete workspace ${w.name}`}
                onClick={() => onDelete(w)}
                onKeyDown={(e) => onMenuKeyDown(e, itemIndex * 2 + 1)}
              >
                <Icon name="close" size={14} />
              </button>
            </div>
          ))}
          <div className="fvd-menu-sep" role="separator" />
          <button
            ref={(node) => {
              menuRefs.current[items.length * 2] = node;
              menuRefs.current.length = items.length * 2 + 1;
            }}
            className="fvd-menu-entry"
            role="menuitem"
            onClick={onSave}
            onKeyDown={(e) => onMenuKeyDown(e, items.length * 2)}
          >
            <span><Icon name="plus" size={14} /> Save current layout…</span>
          </button>
        </div>
      )}
    </div>
  );
}
