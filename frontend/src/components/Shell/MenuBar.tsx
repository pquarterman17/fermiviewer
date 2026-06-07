// Inline dropdown menu bar (handoff §4 "Menu bar"). Items run inline;
// WINDOW-badged workshop items arrive with Phase 4 tool windows.

import { useEffect, useRef, useState } from "react";

import { supportedExtensions } from "../../lib/api";
import { useViewer } from "../../store/viewer";

interface Entry {
  label: string;
  shortcut?: string;
  disabled?: boolean;
  action?: () => void;
}

export default function MenuBar({
  onFit,
  onActualSize,
}: {
  onFit: () => void;
  onActualSize: () => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [accept, setAccept] = useState<string>("");
  const barRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const store = useViewer();

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!barRef.current?.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  // accept filter from the backend's parser registry
  useEffect(() => {
    supportedExtensions()
      .then((exts) => setAccept(exts.join(",")))
      .catch(() => undefined);
  }, []);

  // native OS picker → multipart upload
  const openFiles = () => fileRef.current?.click();

  // ⌘O / Ctrl+O opens the picker (a keydown counts as a user gesture)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        fileRef.current?.click();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onFilesPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      store.openFiles(files).catch((err: Error) => store.setStatus(err.message));
    }
    e.target.value = ""; // allow re-picking the same file
  };

  // secondary: server-side path entry (large files, no upload copy)
  const openByPath = () => {
    const raw = window.prompt("Open server-side path(s) — separate with ;");
    if (!raw) return;
    const paths = raw
      .split(";")
      .map((p) => p.trim())
      .filter(Boolean);
    if (paths.length) {
      store.openPaths(paths).catch((e: Error) => store.setStatus(e.message));
    }
  };

  const menus: Record<string, Entry[]> = {
    File: [
      { label: "Open…", shortcut: "⌘O", action: openFiles },
      { label: "Open by Path…", action: openByPath },
      {
        label: "Save Session…",
        disabled: store.order.length === 0,
        action: () => {
          const p = window.prompt("Save session to path (.json):");
          if (p) {
            store
              .saveWorkspace(p)
              .catch((e: Error) => store.setStatus(e.message));
          }
        },
      },
      {
        label: "Load Session…",
        action: () => {
          const p = window.prompt("Load session from path (.json):");
          if (p) {
            store
              .loadWorkspace(p)
              .catch((e: Error) => store.setStatus(e.message));
          }
        },
      },
      {
        label: "Export…",
        shortcut: "⌘E",
        disabled: !store.activeId,
        action: () => store.setExportOpen(true),
      },
      {
        label: "Close Image",
        shortcut: "⌘W",
        disabled: !store.activeId,
        action: () => {
          if (store.activeId) void store.closeImage(store.activeId);
        },
      },
    ],
    View: [
      { label: "Fit", shortcut: "F", disabled: !store.activeId, action: onFit },
      {
        label: "Actual Size",
        shortcut: "1",
        disabled: !store.activeId,
        action: onActualSize,
      },
      {
        label: store.theme === "dark" ? "Light Theme" : "Dark Theme",
        shortcut: "⌘⇧L",
        action: store.toggleTheme,
      },
      {
        label: store.leftCol ? "Show Library" : "Hide Library",
        shortcut: "⌘[",
        action: store.toggleLeft,
      },
      {
        label: store.rightCol ? "Show Inspector" : "Hide Inspector",
        shortcut: "⌘]",
        action: store.toggleRight,
      },
    ],
    Analyze: [
      {
        label: "EELS Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("eels"),
      },
      {
        label: "EDS Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("eds"),
      },
      {
        label: "Diffraction Workshop",
        shortcut: "WINDOW",
        action: () => store.openTool("diffraction"),
      },
    ],
  };

  return (
    <nav className="fvd-menubar" ref={barRef}>
      <input
        ref={fileRef}
        type="file"
        multiple
        accept={accept || undefined}
        style={{ display: "none" }}
        onChange={onFilesPicked}
      />
      {Object.entries(menus).map(([name, entries]) => (
        <div key={name} style={{ position: "relative" }}>
          <div
            className={`fvd-menu-item${open === name ? " open" : ""}`}
            onMouseDown={() => setOpen(open === name ? null : name)}
            onMouseEnter={() => open && setOpen(name)}
          >
            {name}
          </div>
          {open === name && (
            <div className="fvd-menu-dropdown">
              {entries.map((e) => (
                <div
                  key={e.label}
                  className={`fvd-menu-entry${e.disabled ? " disabled" : ""}`}
                  onMouseDown={(ev) => {
                    ev.stopPropagation();
                    setOpen(null);
                    e.action?.();
                  }}
                >
                  <span>{e.label}</span>
                  {e.shortcut && (
                    <span className="fvd-shortcut">{e.shortcut}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </nav>
  );
}
