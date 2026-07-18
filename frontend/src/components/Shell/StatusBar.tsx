// Bottom status bar (handoff §4 "Shell"): dims · dtype · cursor · zoom.
// Cursor/zoom come from the ephemeral stage store so 120 Hz pointermove
// re-renders only this strip, never the shell.

import { useConnection } from "../../lib/lifecycle";
import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

export default function StatusBar() {
  const status = useViewer((s) => s.status);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const nOfM = useViewer((s) => {
    if (!s.activeId) return "";
    const i = s.order.indexOf(s.activeId);
    return i === -1 ? "" : `${i + 1} / ${s.order.length}`;
  });
  const nImages = useViewer((s) => s.order.length);
  const cycleImage = useViewer((s) => s.cycleImage);
  const cursor = useStageInfo((s) => s.cursor);
  const zoom = useStageInfo((s) => s.zoom);
  const captureMode = useViewer((s) => s.captureMode);
  const connected = useConnection((s) => s.connected);

  return (
    <footer className="fvd-statusbar">
      <span>{status}</span>
      <span className="grow" />
      {captureMode !== "none" && (
        <span className="fvd-capture-hint">
          ● {captureMode} — Esc cancels
        </span>
      )}
      <span className="grow" />
      {meta && (
        <>
          {nOfM &&
            (nImages > 1 ? (
              <span className="fvd-imgnav">
                <button
                  className="fvd-imgnav-btn"
                  aria-label="Previous image"
                  data-tip="Previous image (←)"
                  onClick={() => cycleImage(-1)}
                >
                  ‹
                </button>
                <span className="fvd-imgnav-count">{nOfM}</span>
                <button
                  className="fvd-imgnav-btn"
                  aria-label="Next image"
                  data-tip="Next image (→)"
                  onClick={() => cycleImage(1)}
                >
                  ›
                </button>
              </span>
            ) : (
              <span>{nOfM}</span>
            ))}
          <span>{meta.shape.join(" × ")}</span>
          <span>{meta.dtype}</span>
          {meta.pixel_size !== null && (
            <span>
              {Number(meta.pixel_size.toPrecision(3))} {meta.pixel_unit}/px
            </span>
          )}
          {cursor && (
            <span>
              x {Math.floor(cursor.x)} · y {Math.floor(cursor.y)}
            </span>
          )}
          {zoom !== null && <span>{Math.round(zoom * 100)} %</span>}
        </>
      )}
      <span className="fvd-seg-label">LOCAL</span>
      <span className={`fvd-conn${connected ? " on" : ""}`}>
        {connected ? "connected" : "offline"}
      </span>
    </footer>
  );
}
