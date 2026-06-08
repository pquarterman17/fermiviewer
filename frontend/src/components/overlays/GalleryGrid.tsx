// Full-window thumbnail gallery (checklist K): grid of every open
// image; click activates and closes. Toggled from View menu / G key.

import { renderUrl } from "../../lib/api";
import { useViewer } from "../../store/viewer";

export default function GalleryGrid() {
  const open = useViewer((s) => s.galleryOpen);
  const setOpen = useViewer((s) => s.setGalleryOpen);
  const order = useViewer((s) => s.order);
  const images = useViewer((s) => s.images);
  const activeId = useViewer((s) => s.activeId);
  const setActive = useViewer((s) => s.setActive);

  if (!open) return null;

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setOpen(false)}>
      <div
        className="fvd-glass fvd-gallery"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2>All images ({order.length})</h2>
        <div className="fvd-gallery-grid">
          {order.map((id) => {
            const m = images[id];
            if (!m) return null;
            return (
              <button
                key={id}
                className={`fvd-gallery-cell${id === activeId ? " active" : ""}`}
                title={m.name}
                onClick={() => {
                  setActive(id);
                  setOpen(false);
                }}
              >
                {m.kind === "spectrum" ? (
                  <span className="fvd-gallery-spec">∿</span>
                ) : (
                  <img src={renderUrl(id)} alt={m.name} loading="lazy" />
                )}
                <span className="name">{m.name}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
