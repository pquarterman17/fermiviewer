// Left filmstrip / library (handoff §4 "Library"). Phase 1: thumbnails +
// click-to-activate. Phase 3 adds names mode, multi-select, reorder, ctx menu.

import { renderUrl } from "../../lib/api";
import { useViewer } from "../../store/viewer";

export default function Filmstrip() {
  const order = useViewer((s) => s.order);
  const images = useViewer((s) => s.images);
  const activeId = useViewer((s) => s.activeId);
  const setActive = useViewer((s) => s.setActive);

  return (
    <aside className="fvd-filmstrip">
      {order.length === 0 && (
        <div className="fvd-film-empty">
          No images open.
          <br />
          File → Open…
        </div>
      )}
      {order.map((id) => {
        const meta = images[id];
        if (!meta) return null;
        return (
          <div
            key={id}
            className={`fvd-film-card${id === activeId ? " active" : ""}`}
            onClick={() => setActive(id)}
            title={meta.name}
          >
            {meta.kind === "spectrum" ? (
              // 1-D spectra have no raster (backend 400s on /render)
              <div className="fvd-film-thumb fvd-film-spectrum">⌇</div>
            ) : (
              <img
                className="fvd-film-thumb"
                src={renderUrl(id)}
                alt={meta.name}
                draggable={false}
              />
            )}
            <div className="fvd-film-name">{meta.name}</div>
          </div>
        );
      })}
    </aside>
  );
}
