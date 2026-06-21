// Drag-a-rect region picker over a render preview (SI explorer + local
// FFT). Reports a 1-based inclusive (row0, col0, row1, col1) rect.

import { useRef, useState } from "react";

import { renderUrl } from "../../lib/api";

const VIEW_W = 300;

export type Rect1 = [number, number, number, number];

/** View-space coordinate (px in the scaled preview) → 1-based image pixel,
 *  clamped to [1, n]. Mirrors the rounding used for drag rects. */
export function viewToImagePx(v: number, scale: number, n: number): number {
  return Math.min(n, Math.max(1, Math.round(v / scale + 0.5)));
}

/** A click in pixel-navigate mode → a 1×1 inclusive rect at that pixel
 *  (Quick-Wins #2 EELS specnav). A 1×1 rect is the single-pixel spectrum the
 *  /spectrum endpoint already returns. */
export function clickPixelRect(
  x: number,
  y: number,
  scale: number,
  natW: number,
  natH: number,
): Rect1 {
  const col = viewToImagePx(x, scale, natW);
  const row = viewToImagePx(y, scale, natH);
  return [row, col, row, col];
}

export default function RegionPicker({
  id,
  onRegion,
  pixelMode = false,
}: {
  id: string;
  onRegion: (rect: Rect1 | null) => void; // null = cleared (full image)
  /** when true a click selects a single pixel (1×1 rect) instead of clearing */
  pixelMode?: boolean;
}) {
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [drag, setDrag] = useState<{ a: [number, number]; b: [number, number] } | null>(null);
  const [rect, setRect] = useState<Rect1 | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const scale = nat ? VIEW_W / nat.w : 0;
  const viewH = nat ? nat.h * scale : VIEW_W;

  const local = (e: React.PointerEvent): [number, number] => {
    const r = boxRef.current!.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  const toRect = (a: [number, number], b: [number, number]): Rect1 => [
    viewToImagePx(Math.min(a[1], b[1]), scale, nat!.h),
    viewToImagePx(Math.min(a[0], b[0]), scale, nat!.w),
    viewToImagePx(Math.max(a[1], b[1]), scale, nat!.h),
    viewToImagePx(Math.max(a[0], b[0]), scale, nat!.w),
  ];

  return (
    <div
      ref={boxRef}
      className="fvd-ws-pattern"
      style={{ width: VIEW_W, height: viewH, cursor: "crosshair" }}
      onPointerDown={(e) => {
        if (!nat) return;
        const p = local(e);
        setDrag({ a: p, b: p });
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (drag) setDrag({ a: drag.a, b: local(e) });
      }}
      onPointerUp={(e) => {
        e.currentTarget.releasePointerCapture(e.pointerId);
        if (!drag || !nat) return;
        const w = Math.abs(drag.b[0] - drag.a[0]);
        const h = Math.abs(drag.b[1] - drag.a[1]);
        if (w < 3 || h < 3) {
          if (pixelMode) {
            // click selects a single pixel (1×1 rect) for specnav
            const r = clickPixelRect(drag.a[0], drag.a[1], scale, nat.w, nat.h);
            setRect(r);
            onRegion(r);
          } else {
            setRect(null);
            onRegion(null); // click = clear back to full image
          }
        } else {
          const r = toRect(drag.a, drag.b);
          setRect(r);
          onRegion(r);
        }
        setDrag(null);
      }}
    >
      <img
        src={renderUrl(id)}
        alt=""
        width={VIEW_W}
        draggable={false}
        onLoad={(e) =>
          setNat({
            w: e.currentTarget.naturalWidth,
            h: e.currentTarget.naturalHeight,
          })
        }
      />
      {(drag || rect) && nat && (
        <svg width={VIEW_W} height={viewH} pointerEvents="none">
          {drag ? (
            <rect
              x={Math.min(drag.a[0], drag.b[0])}
              y={Math.min(drag.a[1], drag.b[1])}
              width={Math.abs(drag.b[0] - drag.a[0])}
              height={Math.abs(drag.b[1] - drag.a[1])}
              fill="none"
              stroke="var(--capture)"
              strokeWidth={1.5}
            />
          ) : (
            rect && (
              <rect
                x={(rect[1] - 1) * scale}
                y={(rect[0] - 1) * scale}
                width={(rect[3] - rect[1] + 1) * scale}
                height={(rect[2] - rect[0] + 1) * scale}
                fill="none"
                stroke="var(--capture)"
                strokeWidth={1.5}
                strokeDasharray="5 3"
              />
            )
          )}
        </svg>
      )}
    </div>
  );
}
