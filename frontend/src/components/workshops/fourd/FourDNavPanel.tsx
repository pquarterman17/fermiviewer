// Navigation-image minimap: a small canvas rendering of the real-space nav
// image, click/drag on which sets the probed scan position. This is a
// self-contained canvas panel, NOT the main WebGL Stage — see
// FourDWorkshop's header comment for why v1 stays canvas-only here.

import { useEffect, useRef } from "react";

import { useFourD } from "../../../store/fourd";
import { drawRaster16 } from "./fourdRaster";

const VIEW_W = 180;

export default function FourDNavPanel() {
  const navRaster = useFourD((s) => s.navRaster);
  const busyNav = useFourD((s) => s.busyNav);
  const probe = useFourD((s) => s.probe);
  const setProbe = useFourD((s) => s.setProbe);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const draggingRef = useRef(false);

  useEffect(() => {
    if (!navRaster || !canvasRef.current) return;
    drawRaster16(canvasRef.current, navRaster);
  }, [navRaster]);

  if (!navRaster) {
    return (
      <div className="fvd-ws-empty">
        {busyNav ? "Loading nav image…" : "Select a dataset to load its nav image."}
      </div>
    );
  }

  const scale = VIEW_W / navRaster.w;
  const viewH = navRaster.h * scale;

  const probeAt = (e: { clientX: number; clientY: number }, rect: DOMRect) => {
    const x = Math.floor((e.clientX - rect.left) / scale);
    const y = Math.floor((e.clientY - rect.top) / scale);
    if (x < 0 || y < 0 || x >= navRaster.w || y >= navRaster.h) return;
    setProbe({ y, x });
  };

  return (
    <div className="fvd-ws-fourd-nav">
      <div
        className="fvd-ws-pattern"
        style={{ width: VIEW_W, height: viewH, cursor: "crosshair" }}
        onPointerDown={(e) => {
          draggingRef.current = true;
          probeAt(e, e.currentTarget.getBoundingClientRect());
        }}
        onPointerMove={(e) => {
          if (draggingRef.current) probeAt(e, e.currentTarget.getBoundingClientRect());
        }}
        onPointerUp={() => {
          draggingRef.current = false;
        }}
        onPointerLeave={() => {
          draggingRef.current = false;
        }}
        role="img"
        aria-label="Navigation image — click or drag to probe a scan position"
      >
        <canvas
          ref={canvasRef}
          style={{ width: VIEW_W, height: viewH, imageRendering: "pixelated" }}
        />
        {probe && (
          <svg width={VIEW_W} height={viewH} pointerEvents="none">
            <circle
              cx={(probe.x + 0.5) * scale}
              cy={(probe.y + 0.5) * scale}
              r={3}
              fill="none"
              stroke="var(--capture, #35e0c2)"
              strokeWidth={1.5}
            />
          </svg>
        )}
      </div>
      <div className="fvd-ws-note">
        {probe ? `probe (${probe.y}, ${probe.x})` : "showing the mean pattern"}
      </div>
    </div>
  );
}
