import { useState } from "react";

import { renderUrl } from "../../lib/api";

const VIEW_W = 300;

export default function StructurePreview({
  id,
  markers,
  color,
  onClick,
}: {
  id: string;
  markers: { x: number; y: number }[];
  color: string;
  onClick?: (rowCol: [number, number]) => void;
}) {
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const scale = nat ? VIEW_W / nat.w : 0;
  const viewH = nat ? nat.h * scale : VIEW_W;

  return (
    <div
      className="fvd-ws-pattern"
      style={{
        width: VIEW_W,
        height: viewH,
        cursor: onClick ? "crosshair" : undefined,
      }}
      onClick={(event) => {
        if (!onClick || !nat) return;
        const rect = event.currentTarget.getBoundingClientRect();
        onClick([
          (event.clientY - rect.top) / scale + 0.5,
          (event.clientX - rect.left) / scale + 0.5,
        ]);
      }}
    >
      <img
        src={renderUrl(id)}
        alt=""
        width={VIEW_W}
        draggable={false}
        onLoad={(event) =>
          setNat({
            w: event.currentTarget.naturalWidth,
            h: event.currentTarget.naturalHeight,
          })
        }
      />
      {nat && (
        <svg width={VIEW_W} height={viewH} pointerEvents="none">
          {markers.map((marker, index) => (
            <circle
              key={index}
              cx={(marker.x - 0.5) * scale}
              cy={(marker.y - 0.5) * scale}
              r={3}
              fill="none"
              stroke={color}
              strokeWidth={1.2}
            />
          ))}
        </svg>
      )}
    </div>
  );
}
