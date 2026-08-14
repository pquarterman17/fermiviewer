// Status plumbing for the EDS Spectrum-Image explorer — split out of
// EdsSpectrumImage.tsx (2026-08-14, at 480/500 lines).
//
// Owns the "an EDS error must not outlive the file it referred to"
// contract in both directions:
//   - `reportEds` only surfaces a status for an image that is still open.
//     A slow element-map or spectrum request over a big BCF cube can
//     resolve or reject AFTER the user removed the file; without the
//     guard its .then/.catch would strand a message in the global status
//     bar that closeImage already cleared.
//   - On teardown (cube removed or switched away) it retracts exactly the
//     last message this explorer wrote — never a message some other panel
//     put in the bar.

import { useCallback, useEffect, useRef } from "react";

import { useViewer } from "../../store/viewer";

export function useEdsStatusReporter(activeId: string | null) {
  const setStatus = useViewer((s) => s.setStatus);

  const stillOpen = useCallback(
    (id: string | null): id is string =>
      !!id && !!useViewer.getState().images[id],
    [],
  );

  // Track the last status this explorer wrote so we can retract exactly it
  // on teardown.
  const lastEdsStatus = useRef<string | null>(null);
  const reportEds = useCallback(
    (id: string | null, msg: string) => {
      if (stillOpen(id)) {
        lastEdsStatus.current = msg;
        setStatus(msg);
      }
    },
    [stillOpen, setStatus],
  );

  // When the active cube is removed or switched away, clear the status line
  // if it still shows the message this explorer last wrote (the reported
  // "errors didn't clear" bug).
  useEffect(() => {
    return () => {
      const st = useViewer.getState();
      if (lastEdsStatus.current && st.status === lastEdsStatus.current) {
        st.setStatus("ready");
      }
    };
  }, [activeId]);

  return { stillOpen, reportEds };
}
