// Color overlay (checklist K): pseudo-colour additive blend of 2–4
// same-size images — drift inspection, before/after comparison. Reuses
// the EDS composite engine (channel list + canvas blend).

import { useEffect, useState } from "react";

import { useViewer } from "../../store/viewer";
import EdsComposite, { type Channel } from "./EdsComposite";

const OVERLAY_PALETTE = ["#f43f5e", "#06b6d4", "#22c55e", "#eab308"];

export default function ColorOverlayWorkshop() {
  const selected = useViewer((s) => s.selected);
  const [channels, setChannels] = useState<Channel[]>([]);

  const key = selected.join(",");
  useEffect(() => {
    const s = useViewer.getState();
    const ids = s.selected.slice(0, 4);
    const shapes = new Set(
      ids.map((id) => (s.images[id]?.shape ?? []).join("x")),
    );
    if (ids.length < 2 || shapes.size !== 1) {
      setChannels([]);
      return;
    }
    setChannels(
      ids.map((id, i) => ({
        id,
        el: (s.images[id]?.name ?? id).slice(0, 8),
        color: OVERLAY_PALETTE[i % OVERLAY_PALETTE.length],
        intensity: 1,
        visible: true,
      })),
    );
    // key encodes the selection; images are read fresh via getState
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (channels.length < 2) {
    return (
      <div className="fvd-ws-empty">
        ⌘-click 2–4 same-size images in the filmstrip.
      </div>
    );
  }
  return (
    <div className="fvd-ws">
      <EdsComposite channels={channels} onChange={setChannels} />
    </div>
  );
}
