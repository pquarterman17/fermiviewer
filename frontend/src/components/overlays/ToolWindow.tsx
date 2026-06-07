// Floating workshop window frame (handoff §4 "Workshop window"):
// draggable by title bar, focus-on-click z-order, close dot.

import { useRef } from "react";

import { useViewer, type ToolKind } from "../../store/viewer";

export default function ToolWindow({
  kind,
  title,
  x,
  y,
  z,
  width,
  children,
}: {
  kind: ToolKind;
  title: string;
  x: number;
  y: number;
  z: number;
  width: number;
  children: React.ReactNode;
}) {
  const moveTool = useViewer((s) => s.moveTool);
  const closeTool = useViewer((s) => s.closeTool);
  const focusTool = useViewer((s) => s.focusTool);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);

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
      className="fvd-glass fvd-tool-window"
      style={{ left: x, top: y, zIndex: 200 + z, width }}
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
    </div>
  );
}
