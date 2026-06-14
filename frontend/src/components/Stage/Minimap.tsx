// Minimap (checklist N): overview thumbnail with the visible-region
// rectangle; click or drag to recentre the view. Hidden when the whole
// image already fits the viewport.

import { renderUrl } from "../../lib/api";
import { fitZoom, screenToImage, type Size } from "../../lib/geometry";
import { useViewer, type View } from "../../store/viewer";

const MAP_W = 120;

export default function Minimap({
  imageId,
  view,
  img,
  vp,
  onNavigate,
}: {
  imageId: string;
  view: View;
  img: Size;
  vp: Size;
  onNavigate: (view: View) => void;
}) {
  const show = useViewer((s) => s.minimap);
  // hidden unless meaningfully zoomed past fit
  if (!show || view.z <= fitZoom(img, vp) * 1.05) return null;

  const mapH = (img.h / img.w) * MAP_W;
  const sx = MAP_W / img.w; // map px per image px

  // visible image-space rect (clamped)
  const tl = screenToImage(0, 0, view, img, vp);
  const br = screenToImage(vp.w, vp.h, view, img, vp);
  const rx = Math.max(0, tl.x) * sx;
  const ry = Math.max(0, tl.y) * sx;
  const rw = (Math.min(img.w, br.x) - Math.max(0, tl.x)) * sx;
  const rh = (Math.min(img.h, br.y) - Math.max(0, tl.y)) * sx;

  const navigate = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onNavigate({
      ...view,
      px: (e.clientX - r.left) / MAP_W,
      py: (e.clientY - r.top) / mapH,
    });
  };

  return (
    <div
      className="fvd-glass fvd-minimap"
      style={{ width: MAP_W, height: mapH }}
      onPointerDown={(e) => {
        e.stopPropagation(); // don't let the Stage start a marquee/pan
        navigate(e);
      }}
      onPointerMove={(e) => {
        e.stopPropagation();
        if (e.buttons === 1) navigate(e);
      }}
    >
      <img
        src={renderUrl(imageId)}
        alt=""
        width={MAP_W}
        height={mapH}
        draggable={false}
      />
      <div
        className="fvd-minimap-rect"
        style={{
          left: rx,
          top: ry,
          width: Math.max(4, rw),
          height: Math.max(4, rh),
        }}
      />
    </div>
  );
}
