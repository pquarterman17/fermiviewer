// Bottom status bar (handoff §4 "Shell"): dims · dtype · cursor · zoom.
// Cursor/zoom come from the ephemeral stage store so 120 Hz pointermove
// re-renders only this strip, never the shell.

import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

export default function StatusBar() {
  const status = useViewer((s) => s.status);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const cursor = useStageInfo((s) => s.cursor);
  const zoom = useStageInfo((s) => s.zoom);

  return (
    <footer className="fvd-statusbar">
      <span>{status}</span>
      <span className="grow" />
      {meta && (
        <>
          <span>{meta.shape.join(" × ")}</span>
          <span>{meta.dtype}</span>
          {cursor && (
            <span>
              x {Math.floor(cursor.x)} · y {Math.floor(cursor.y)}
            </span>
          )}
          {zoom !== null && <span>{Math.round(zoom * 100)} %</span>}
        </>
      )}
    </footer>
  );
}
