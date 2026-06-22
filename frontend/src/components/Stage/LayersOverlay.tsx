// Stage overlay for the Cross-section Layers workshop: draws the detected
// interface mean-lines (and the wavy σ_w trace when present) on the image.
// Read-only — analysis lives in the workshop; this just visualises the
// `layersOverlay` store slice for the active image.

import { imageToScreen, type Size } from "../../lib/geometry";
import { useViewer, type View } from "../../store/viewer";

export default function LayersOverlay({
  imageId,
  view,
  img,
  vp,
}: {
  imageId: string;
  view: View;
  img: Size;
  vp: Size;
}) {
  const overlay = useViewer((s) => s.layersOverlay);
  if (!overlay || overlay.imageId !== imageId) return null;
  const horizontal = overlay.axis === "y";

  return (
    <svg className="fvd-measure-layer" width={vp.w} height={vp.h}>
      {overlay.interfaces.map((pos, k) => {
        // mean interface line: spans the lateral extent at depth `pos`
        const a = horizontal
          ? imageToScreen(0, pos, view, img, vp)
          : imageToScreen(pos, 0, view, img, vp);
        const b = horizontal
          ? imageToScreen(img.w, pos, view, img, vp)
          : imageToScreen(pos, img.h, view, img, vp);
        const trace = overlay.traces[k];
        // wavy trace: edge depth per lateral column → polyline
        const poly = trace
          ? trace
              .map((d, j) => {
                const p = horizontal
                  ? imageToScreen(j, d, view, img, vp)
                  : imageToScreen(d, j, view, img, vp);
                return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
              })
              .join(" ")
          : null;
        return (
          <g key={k}>
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="#f59e0b"
              strokeWidth={1}
              strokeDasharray="5 3"
              opacity={0.85}
            />
            {poly && (
              <polyline points={poly} fill="none" stroke="#22d3ee" strokeWidth={1} opacity={0.8} />
            )}
          </g>
        );
      })}
    </svg>
  );
}
