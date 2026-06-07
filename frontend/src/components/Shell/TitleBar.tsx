// Native-style window chrome: traffic lights, centred doc title,
// panel toggles (handoff §4 "Shell"). Lights are decorative until Tauri.

import { useViewer } from "../../store/viewer";

export default function TitleBar() {
  const activeId = useViewer((s) => s.activeId);
  const name = useViewer((s) =>
    s.activeId ? (s.images[s.activeId]?.name ?? "") : "",
  );
  const toggleLeft = useViewer((s) => s.toggleLeft);
  const toggleRight = useViewer((s) => s.toggleRight);

  return (
    <header className="fvd-titlebar">
      <div className="fvd-traffic">
        <span />
        <span />
        <span />
      </div>
      <div className="fvd-doc-title">
        {activeId ? `FermiViewer — ${name}` : "FermiViewer"}
      </div>
      <div className="fvd-panel-toggles">
        <button
          className="fvd-icon-btn"
          title="Toggle library  ⌘["
          onClick={toggleLeft}
        >
          ◧
        </button>
        <button
          className="fvd-icon-btn"
          title="Toggle inspector  ⌘]"
          onClick={toggleRight}
        >
          ◨
        </button>
      </div>
    </header>
  );
}
