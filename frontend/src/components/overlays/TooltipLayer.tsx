// Hover tooltips (GUI-enhancements handoff, WS2). A single delegated listener
// watches for [data-tip] elements anywhere in the document and, after a short
// dwell, shows a glass chip with the action name plus its optional
// [data-tip-key] keyboard shortcut. Mounted once at the app root; icon-only
// controls opt in with `data-tip="Measure distance" data-tip-key="D"`.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface Tip {
  label: string;
  hint: string | null;
  x: number;
  y: number;
  below: boolean;
}

const DWELL_MS = 350;

export default function TooltipLayer() {
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const clear = () => {
      if (timer) clearTimeout(timer);
      timer = undefined;
    };
    const onOver = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        "[data-tip]",
      );
      if (!el) return;
      const label = el.getAttribute("data-tip");
      if (!label) return;
      const hint = el.getAttribute("data-tip-key");
      const rect = el.getBoundingClientRect();
      clear();
      timer = setTimeout(() => {
        // flip below the target when it sits near the top edge (title bar)
        const below = rect.top < 90;
        setTip({
          label,
          hint,
          x: rect.left + rect.width / 2,
          y: below ? rect.bottom + 8 : rect.top - 8,
          below,
        });
      }, DWELL_MS);
    };
    const onOut = () => {
      clear();
      setTip(null);
    };
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    document.addEventListener("mousedown", onOut);
    return () => {
      clear();
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mouseout", onOut);
      document.removeEventListener("mousedown", onOut);
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div
      className="fvd-tip"
      style={{
        left: tip.x,
        top: tip.y,
        transform: tip.below ? "translate(-50%, 0)" : "translate(-50%, -100%)",
      }}
    >
      <span>{tip.label}</span>
      {tip.hint && <kbd className="fvd-tip-key">{tip.hint}</kbd>}
    </div>,
    document.body,
  );
}
