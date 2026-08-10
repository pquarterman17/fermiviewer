// Unavailable images in the library, with the "Locate folder…" action
// (PROJECT_WORKFLOW_PLAN #35, format ADR 0002 §4).
//
// A light-mode project references its source pixels, so opening one on a
// machine where the data has moved leaves images that cannot be rendered.
// They are NOT dropped: each keeps its name, its reference, its sample
// membership, its parameters and its measurements, and saving writes the
// reference straight back. This block is where the user SEES that, and where
// they point the project at where the data is now.
//
// A block of its own rather than cards in the sections: a placeholder has no
// pixels, so it cannot be a FilmCard (no thumbnail, no render, nothing to
// select onto the stage) — and pretending otherwise would put a broken image
// in the library instead of an honest, actionable one.
//
// Repeatable by design. Each pick re-links every image found under the chosen
// folder and leaves the rest listed, because samples in a study routinely
// move to different folders and one pick cannot know about all of them.

import { useMemo, useState } from "react";

import { useViewer } from "../../store/viewer";
import Icon from "../icons/Icon";

export default function UnavailableSection() {
  const unavailable = useViewer((s) => s.unavailable);
  const locateData = useViewer((s) => s.locateData);
  const setStatus = useViewer((s) => s.setStatus);
  const [busy, setBusy] = useState(false);

  // derived in a memo, never in a selector: a selector returning a fresh
  // array re-renders forever (the zustand stable-snapshot rule)
  const missing = useMemo(() => Object.values(unavailable), [unavailable]);
  if (missing.length === 0) return null;

  const locate = () => {
    const root = window.prompt(
      "Folder the missing images are in now (every image under it is " +
        "re-linked; repeat for samples that moved elsewhere):",
    );
    if (!root) return;
    setBusy(true);
    locateData(root)
      .catch((e: Error) => setStatus(e.message))
      .finally(() => setBusy(false));
  };

  return (
    <section className="fvd-unavailable" aria-label="Unavailable images">
      <div className="fvd-unavailable-head">
        <span className="fvd-unavailable-title">
          {missing.length} unavailable
        </span>
      </div>
      <p className="fvd-unavailable-note">
        Saved with this project, but the image files are not where it left
        them. Nothing is lost — names, samples, parameters and measurements are
        kept, and saving keeps the references.
      </p>
      <button
        className="fvd-unavailable-btn"
        disabled={busy}
        onClick={locate}
        data-tip="Point this project at the folder its data is in now"
        data-tip-detail="Every image found under the folder is re-linked. Repeat for samples that moved somewhere else."
      >
        <Icon name="search" /> {busy ? "Locating…" : "Locate folder…"}
      </button>
      <ul className="fvd-unavailable-list">
        {missing.map((u) => (
          <li key={u.id} title={u.source ?? u.rel ?? u.name}>
            <span className="fvd-unavailable-name">{u.name}</span>
            {u.rel && <span className="fvd-unavailable-rel">{u.rel}</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
