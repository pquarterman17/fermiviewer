// Floating workshop window frame (handoff §4 "Workshop window"):
// draggable by title bar, focus-on-click z-order, close dot.

import { useRef, useState } from "react";

import { useViewer, type ToolKind } from "../../store/viewer";
import { toolWindowZIndex } from "../../styles/zLayers";

export default function ToolWindow({
  kind,
  title,
  x,
  y,
  z,
  width,
  height,
  children,
}: {
  kind: ToolKind;
  title: string;
  x: number;
  y: number;
  z: number;
  width: number;
  height?: number;
  children: React.ReactNode;
}) {
  const moveTool = useViewer((s) => s.moveTool);
  const closeTool = useViewer((s) => s.closeTool);
  const focusTool = useViewer((s) => s.focusTool);
  const [size, setSize] = useState<{ width: number; height?: number }>({
    width,
    height,
  });
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  const resizeRef = useRef<{
    x: number;
    y: number;
    width: number;
    height: number;
  } | null>(null);
  const windowRef = useRef<HTMLDivElement>(null);

  const onTitleDown = (e: React.PointerEvent) => {
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
      className="fvd-glass fvd-tool-window"
      style={{ left: x, top: y, zIndex: toolWindowZIndex(z), ...size }}
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
      </div>
      <div className="fvd-tool-body">{children}</div>
      <div
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
          setSize({
            width: Math.max(
              300,
              Math.min(
              window.innerWidth - x - 8,
              resizeRef.current.width + e.clientX - resizeRef.current.x,
              ),
            ),
            height: Math.max(
              240,
              Math.min(
              window.innerHeight - y - 8,
              resizeRef.current.height + e.clientY - resizeRef.current.y,
              ),
            ),
          });
        }}
        onPointerUp={(e) => {
          resizeRef.current = null;
          e.currentTarget.releasePointerCapture(e.pointerId);
        }}
      />
    </div>
  );
}
