import { useEffect, useRef, useState } from "react";

import Icon from "../icons/Icon";

export interface MenuEntry {
  label?: string;
  shortcut?: string;
  disabled?: boolean;
  action?: () => void;
  kind?: "section" | "sep";
  submenu?: MenuEntry[];
}

export default function DesktopMenus({
  menus,
}: {
  menus: Record<string, MenuEntry[]>;
}) {
  const names = Object.keys(menus);
  const [open, setOpen] = useState<string | null>(null);
  const [openSub, setOpenSub] = useState<string | null>(null);
  const [topIndex, setTopIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const topRefs = useRef(new Map<string, HTMLButtonElement>());
  const itemRefs = useRef(new Map<string, HTMLButtonElement[]>());
  const subRefs = useRef(new Map<string, HTMLButtonElement[]>());

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(null);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => setOpenSub(null), [open]);

  const focusTop = (index: number) => {
    const nextIndex = (index + names.length) % names.length;
    const name = names[nextIndex];
    setTopIndex(nextIndex);
    topRefs.current.get(name)?.focus();
  };

  // Ref slots are written by enabled-entry position and never truncated, so a
  // menu that reopens with fewer enabled entries keeps null slots at the tail.
  // Wrapping on the raw length would land on those and silently do nothing.
  const liveItems = (name: string) =>
    (itemRefs.current.get(name) ?? []).filter(
      (node): node is HTMLButtonElement => node != null,
    );

  const focusItem = (name: string, index: number) => {
    const refs = liveItems(name);
    if (refs.length === 0) return;
    refs[(index + refs.length) % refs.length]?.focus();
  };

  const openMenu = (name: string, focusFirst = false) => {
    setOpen(name);
    if (focusFirst) requestAnimationFrame(() => focusItem(name, 0));
  };

  const closeMenu = (returnFocus = true) => {
    const prior = open;
    setOpen(null);
    if (returnFocus && prior) topRefs.current.get(prior)?.focus();
  };

  const switchMenu = (name: string, delta: number) => {
    const nextIndex = (names.indexOf(name) + delta + names.length) % names.length;
    const next = names[nextIndex];
    setTopIndex(nextIndex);
    if (open) openMenu(next, true);
    else focusTop(nextIndex);
  };

  const topKeyDown = (e: React.KeyboardEvent, name: string) => {
    if (e.key === "ArrowRight") switchMenu(name, 1);
    else if (e.key === "ArrowLeft") switchMenu(name, -1);
    else if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
      openMenu(name, true);
    } else if (e.key === "Escape") closeMenu();
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const mainKeyDown = (
    e: React.KeyboardEvent,
    name: string,
    index: number,
    entry: MenuEntry,
  ) => {
    const refs = liveItems(name);
    if (e.key === "ArrowDown") focusItem(name, index + 1);
    else if (e.key === "ArrowUp") focusItem(name, index - 1);
    else if (e.key === "Home") focusItem(name, 0);
    else if (e.key === "End") focusItem(name, refs.length - 1);
    else if (e.key === "Escape") closeMenu();
    else if (e.key === "ArrowLeft") switchMenu(name, -1);
    else if (e.key === "ArrowRight" && entry.submenu) {
      const subKey = `${name}:${entry.label}`;
      setOpenSub(subKey);
      requestAnimationFrame(() => subRefs.current.get(subKey)?.[0]?.focus());
    } else if (e.key === "ArrowRight") switchMenu(name, 1);
    else if ((e.key === "Enter" || e.key === " ") && entry.submenu) {
      const subKey = `${name}:${entry.label}`;
      setOpenSub(subKey);
      requestAnimationFrame(() => subRefs.current.get(subKey)?.[0]?.focus());
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const subKeyDown = (
    e: React.KeyboardEvent,
    name: string,
    subKey: string,
    parentIndex: number,
    index: number,
  ) => {
    const refs = (subRefs.current.get(subKey) ?? []).filter(
      (node): node is HTMLButtonElement => node != null,
    );
    if (refs.length === 0) return;
    if (e.key === "ArrowDown") refs[(index + 1) % refs.length]?.focus();
    else if (e.key === "ArrowUp")
      refs[(index - 1 + refs.length) % refs.length]?.focus();
    else if (e.key === "Home") refs[0]?.focus();
    else if (e.key === "End") refs[refs.length - 1]?.focus();
    else if (e.key === "Escape" || e.key === "ArrowLeft") {
      setOpenSub(null);
      liveItems(name)[parentIndex]?.focus();
    } else if (e.key === "ArrowRight") switchMenu(name, 1);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const run = (entry: MenuEntry) => {
    if (entry.disabled || !entry.action) return;
    setOpen(null);
    entry.action();
  };

  return (
    <div className="fvd-desktop-menus" role="menubar" ref={rootRef}>
      {Object.entries(menus).map(([name, entries]) => {
        let itemIndex = 0;
        return (
          <div key={name} className="fvd-menu-root">
            <button
              ref={(node) => {
                if (node) topRefs.current.set(name, node);
                else topRefs.current.delete(name);
              }}
              type="button"
              role="menuitem"
              tabIndex={names.indexOf(name) === topIndex ? 0 : -1}
              className={`fvd-menu-item${open === name ? " open" : ""}`}
              aria-haspopup="menu"
              aria-expanded={open === name}
              onClick={() => (open === name ? closeMenu(false) : openMenu(name))}
              onFocus={() => setTopIndex(names.indexOf(name))}
              onMouseEnter={() => open && openMenu(name)}
              onKeyDown={(e) => topKeyDown(e, name)}
            >
              {name}
            </button>
            {open === name && (
              <div className="fvd-menu-dropdown" role="menu" aria-label={name}>
                {entries.map((entry, entryIndex) => {
                  if (entry.kind === "sep")
                    return (
                      <div key={entryIndex} className="fvd-menu-sep" role="separator" />
                    );
                  if (entry.kind === "section")
                    return (
                      <div key={entryIndex} className="fvd-menu-section" role="presentation">
                        {entry.label}
                      </div>
                    );
                  const focusIndex = entry.disabled ? -1 : itemIndex++;
                  const subKey = `${name}:${entry.label}`;
                  return (
                    <div
                      key={entryIndex}
                      className="fvd-menu-entry-wrap"
                      // Keeps role="menu" -> role="menuitem" ownership intact
                      // across this layout wrapper.
                      role="presentation"
                      onMouseEnter={() => setOpenSub(entry.submenu ? subKey : null)}
                    >
                      <button
                        ref={(node) => {
                          if (focusIndex < 0) return;
                          const refs = itemRefs.current.get(name) ?? [];
                          refs[focusIndex] = node as HTMLButtonElement;
                          itemRefs.current.set(name, refs);
                        }}
                        type="button"
                        role="menuitem"
                        className={`fvd-menu-entry${entry.submenu ? " has-sub" : ""}`}
                        disabled={entry.disabled}
                        aria-haspopup={entry.submenu ? "menu" : undefined}
                        aria-expanded={entry.submenu ? openSub === subKey : undefined}
                        onClick={() => entry.submenu ? setOpenSub(subKey) : run(entry)}
                        onKeyDown={(e) => mainKeyDown(e, name, focusIndex, entry)}
                      >
                        <span>{entry.label}</span>
                        {entry.submenu ? (
                          <Icon name="chevron-right" size={14} className="fvd-submenu-arrow" />
                        ) : (
                          entry.shortcut && (
                            <span className="fvd-shortcut">{entry.shortcut}</span>
                          )
                        )}
                      </button>
                      {entry.submenu && openSub === subKey && (
                        <Submenu
                          entries={entry.submenu}
                          name={name}
                          subKey={subKey}
                          parentIndex={focusIndex}
                          refs={subRefs}
                          onRun={run}
                          onKeyDown={subKeyDown}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function Submenu({
  entries,
  name,
  subKey,
  parentIndex,
  refs,
  onRun,
  onKeyDown,
}: {
  entries: MenuEntry[];
  name: string;
  subKey: string;
  parentIndex: number;
  refs: React.RefObject<Map<string, HTMLButtonElement[]>>;
  onRun: (entry: MenuEntry) => void;
  onKeyDown: (
    e: React.KeyboardEvent,
    name: string,
    subKey: string,
    parentIndex: number,
    index: number,
  ) => void;
}) {
  let focusIndex = 0;
  return (
    <div className="fvd-menu-dropdown fvd-submenu" role="menu">
      {entries.map((entry, entryIndex) => {
        if (entry.kind === "sep")
          return <span key={entryIndex} className="fvd-menu-sep" role="separator" />;
        const index = entry.disabled ? -1 : focusIndex++;
        return (
          <button
            key={entryIndex}
            ref={(node) => {
              if (index < 0) return;
              const current = refs.current.get(subKey) ?? [];
              current[index] = node as HTMLButtonElement;
              refs.current.set(subKey, current);
            }}
            type="button"
            role="menuitem"
            className="fvd-menu-entry"
            disabled={entry.disabled}
            onClick={(e) => {
              e.stopPropagation();
              onRun(entry);
            }}
            onKeyDown={(e) => onKeyDown(e, name, subKey, parentIndex, index)}
          >
            <span>{entry.label}</span>
            {entry.shortcut && <span className="fvd-shortcut">{entry.shortcut}</span>}
          </button>
        );
      })}
    </div>
  );
}
