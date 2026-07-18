import { useEffect, useRef, useState } from "react";

import { supportedExtensions } from "../../lib/api";
import { useViewer } from "../../store/viewer";

/** Welcoming first-run surface that shares the same open behavior as File → Open. */
export default function EmptyStage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [accept, setAccept] = useState("");
  const launchContext = useViewer((s) => s.launchContext);
  const setFolderOpen = useViewer((s) => s.setFolderOpen);
  const openFiles = useViewer((s) => s.openFiles);
  const setStatus = useViewer((s) => s.setStatus);

  useEffect(() => {
    supportedExtensions()
      .then((exts) => setAccept(exts.join(",")))
      .catch(() => undefined);
  }, []);

  const open = () => {
    if ((launchContext?.files.length ?? 0) > 0) setFolderOpen(true);
    else fileRef.current?.click();
  };

  return (
    <div
      className="fvd-stage-empty"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className="fvd-empty-welcome">
        <div className="fvd-empty-art" aria-hidden="true">
          <svg viewBox="0 0 64 64">
            <rect x="10" y="14" width="44" height="36" rx="5" />
            <path d="M17 41 27 30l7 7 5-5 8 9" />
            <circle cx="42" cy="24" r="3" />
          </svg>
        </div>
        <div>
          <h1>Open a microscopy dataset</h1>
          <p>Inspect, measure, compare, and analyze images in one workspace.</p>
        </div>
        <button className="fvd-btn primary fvd-empty-open" onClick={open}>
          Open image…
        </button>
        <div className="fvd-empty-drop">or drop files anywhere in this window</div>
        <div className="fvd-empty-formats">
          DM3/DM4 · TIFF · EMD · SER · MRC · standard images
        </div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={accept || undefined}
          className="fvd-empty-file-input"
          aria-label="Choose microscopy images"
          onChange={(e) => {
            const files = e.target.files;
            if (files && files.length > 0) {
              openFiles(files).catch((err: Error) => setStatus(err.message));
            }
            e.target.value = "";
          }}
        />
      </div>
    </div>
  );
}
