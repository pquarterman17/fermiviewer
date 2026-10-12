// Floating workshop window frame (handoff §4 "Workshop window"):
// draggable by title bar, focus-on-click z-order, close dot.

import { useEffect, useRef, useState } from "react";

import { useViewer, type ToolKind } from "../../store/viewer";
import { toolWindowZIndex } from "../../styles/zLayers";

const MIN_WIDTH = 300;
const MIN_HEIGHT = 240;

interface ToolSize {
  width: number;
  height?: number;
}

function savedSize(
  key: string | undefined,
  fallback: ToolSize,
  availableWidth: number,
  availableHeight: number,
): ToolSize {
  if (!key) return fallback;
  try {
    const value = JSON.parse(localStorage.getItem(`fv_tool_size_${key}`) ?? "null") as
      Partial<ToolSize> | null;
    if (!value || !Number.isFinite(value.width) || value.width! < MIN_WIDTH) {
      return fallback;
    }
    const height = value.height;
    return {
      width: Math.min(value.width!, Math.max(MIN_WIDTH, availableWidth)),
      height: Number.isFinite(height) && height! >= MIN_HEIGHT
        ? Math.min(height!, Math.max(MIN_HEIGHT, availableHeight))
        : fallback.height,
    };
  } catch {
    return fallback;
  }
}

function rememberSize(key: string, size: ToolSize): void {
  try {
    localStorage.setItem(`fv_tool_size_${key}`, JSON.stringify(size));
  } catch {
    // Storage can be unavailable in locked-down or quota-limited browsers;
    // resizing the live window must still succeed in that session.
  }
}

export default function ToolWindow({
  kind,
  title,
  x,
  y,
  z,
  width,
  height,
  layoutKey,
  workspaceControls = false,
  children,
}: {
  kind: ToolKind;
  title: string;
  x: number;
  y: number;
  z: number;
  width: number;
  height?: number;
  /** Share a remembered preferred size across equivalent tool kinds. */
  layoutKey?: string;
  /** Offer collapse and full-workspace modes for content-heavy inspectors. */
  workspaceControls?: boolean;
  children: React.ReactNode;
}) {
  const moveTool = useViewer((s) => s.moveTool);
  const closeTool = useViewer((s) => s.closeTool);
  const focusTool = useViewer((s) => s.focusTool);
  const [size, setSize] = useState<ToolSize>(() => savedSize(
    layoutKey,
    { width, height },
    window.innerWidth - x - 8,
    window.innerHeight - y - 8,
  ));
  const sizeRef = useRef(size);
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!expanded) return;
    const restore = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", restore);
    return () => window.removeEventListener("keydown", restore);
  }, [expanded]);

  const onTitleDown = (e: React.PointerEvent) => {
    if (expanded) return;
    dragRef.current = { dx: e.clientX - x, dy: e.clientY - y };
    (e.target as Element).setPointerCapture(e.pointerId);
  };

  const onTitleMove = (e: React.PointerEvent) => {
    if (!dragRef.current) return;
    moveTool(
      kind,
      Math.max(0, e.clientX - dragRef.current.dx),
      Math.max(0, e.clientY - dragRef.current.dy),
    );
  };

  const onTitleUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
  };

  return (
    <div
      ref={windowRef}
      className={`fvd-glass fvd-tool-window${collapsed ? " collapsed" : ""}${
        expanded ? " expanded" : ""
      }`}
      style={expanded
        ? { top: 42, right: 8, bottom: 32, left: 8, zIndex: toolWindowZIndex(z) }
        : { left: x, top: y, zIndex: toolWindowZIndex(z), ...size }}
      onMouseDown={() => focusTool(kind)}
    >
      <div
        className="fvd-tool-title"
        onPointerDown={onTitleDown}
        onPointerMove={onTitleMove}
        onPointerUp={onTitleUp}
      >
        <button
          className="fvd-tool-close"
          title="Close"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => closeTool(kind)}
        />
        <span>{title}</span>
        {workspaceControls && (
          <div className="fvd-tool-title-actions">
            <button
              type="button"
              className="fvd-icon-btn"
              aria-label={collapsed ? `Expand ${title}` : `Collapse ${title}`}
              aria-pressed={collapsed}
              title={collapsed ? "Show workspace" : "Collapse to see the source image"}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => {
                setCollapsed((value) => !value);
                if (!collapsed) setExpanded(false);
              }}
            >
              {collapsed ? "▾" : "▴"}
            </button>
            <button
              type="button"
              className="fvd-icon-btn"
              aria-label={expanded ? `Restore ${title} window` : `Use full workspace for ${title}`}
              aria-pressed={expanded}
              title={expanded ? "Restore floating window" : "Use full workspace"}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={() => {
                setExpanded((value) => !value);
                setCollapsed(false);
              }}
            >
              {expanded ? "❐" : "□"}
            </button>
          </div>
        )}
      </div>
      <div className="fvd-tool-body" hidden={collapsed}>{children}</div>
      {!collapsed && !expanded && <div
        className="fvd-tool-resize"
        role="separator"
        aria-label={`Resize ${title} window`}
        onPointerDown={(e) => {
          const rect = windowRef.current?.getBoundingClientRect();
          if (!rect) return;
          resizeRef.current = {
            x: e.clientX,
            y: e.clientY,
            width: rect.width,
            height: rect.height,
          };
          e.currentTarget.setPointerCapture(e.pointerId);
          e.stopPropagation();
        }}
        onPointerMove={(e) => {
          if (!resizeRef.current) return;
          const nextSize = {
            width: Math.max(
              MIN_WIDTH,
              Math.min(
              window.innerWidth - x - 8,
              resizeRef.current.width + e.clientX - resizeRef.current.x,
              ),
            ),
            height: Math.max(
              MIN_HEIGHT,
              Math.min(
              window.innerHeight - y - 8,
              resizeRef.current.height + e.clientY - resizeRef.current.y,
              ),
            ),
          };
          sizeRef.current = nextSize;
          setSize(nextSize);
        }}
        onPointerUp={(e) => {
          resizeRef.current = null;
          e.currentTarget.releasePointerCapture(e.pointerId);
          if (layoutKey) {
            rememberSize(layoutKey, sizeRef.current);
          }
        }}
      />}
    </div>
  );
}
