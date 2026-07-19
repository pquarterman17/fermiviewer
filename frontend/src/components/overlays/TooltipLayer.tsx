// Hover tooltips (GUI-enhancements handoff, WS2). A single delegated listener
// watches for [data-tip] elements anywhere in the document and, after a short
// dwell, shows a glass chip with the action name plus its optional
// [data-tip-key] keyboard shortcut. Mounted once at the app root; icon-only
// controls opt in with `data-tip="Measure distance" data-tip-key="D"`.

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

interface Tip {
  label: string;
  detail: string | null;
  hint: string | null;
  x: number;
  y: number;
  below: boolean;
}

const DWELL_MS = 350;
// The chip is a single shared node, so it needs a stable id: assistive tech
// only announces a tooltip that its trigger points at via aria-describedby.
const TIP_ID = "fvd-tooltip";

export default function TooltipLayer() {
  const [tip, setTip] = useState<Tip | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let described: HTMLElement | null = null;
    const clear = () => {
      if (timer) clearTimeout(timer);
      timer = undefined;
    };
    const undescribe = () => {
      described?.removeAttribute("aria-describedby");
      described = null;
    };
    const show = (el: HTMLElement) => {
      const label = el.getAttribute("data-tip");
      if (!label) return;
      const detail = el.getAttribute("data-tip-detail");
      const hint = el.getAttribute("data-tip-key");
      const rect = el.getBoundingClientRect();
      clear();
      timer = setTimeout(() => {
        // The trigger can be gone by now (e.g. a button that removes itself on
        // click). A removed node emits neither mouseout nor focusout, so a chip
        // shown for one would strand on screen with nothing left to dismiss it.
        if (!el.isConnected) return;
        // flip below the target when it sits near the top edge (title bar)
        const below = rect.top < 90;
        undescribe();
        el.setAttribute("aria-describedby", TIP_ID);
        described = el;
        setTip({
          label,
          detail,
          hint,
          x: rect.left + rect.width / 2,
          y: below ? rect.bottom + 8 : rect.top - 8,
          below,
        });
      }, DWELL_MS);
    };
    const onOver = (e: MouseEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        "[data-tip]",
      );
      if (el) show(el);
    };
    // Which input last drove focus. Clicking a control focuses it, so without
    // this the focusin below would re-arm the dwell timer that mousedown just
    // cleared — every click on a [data-tip] button would pop its own tooltip
    // back up 350 ms later.
    let pointerModality = false;
    // WCAG 1.4.13 wants hover and focus parity. Keyboard users never trigger
    // mouseover, so without this the descriptions are unreachable for them.
    const onFocus = (e: FocusEvent) => {
      if (pointerModality) return; // click-focus, not keyboard navigation
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        "[data-tip]",
      );
      if (el) show(el);
    };
    const onOut = () => {
      clear();
      undescribe();
      setTip(null);
    };
    const onDown = () => {
      pointerModality = true;
      onOut();
    };
    // …and dismissible without moving the pointer or focus.
    const onKey = (e: KeyboardEvent) => {
      pointerModality = false; // Tab (or any key) hands control back to the keyboard
      if (e.key === "Escape") onOut();
    };
    document.addEventListener("mouseover", onOver);
    document.addEventListener("mouseout", onOut);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("focusin", onFocus);
    document.addEventListener("focusout", onOut);
    document.addEventListener("keydown", onKey);
    return () => {
      clear();
      undescribe();
      document.removeEventListener("mouseover", onOver);
      document.removeEventListener("mouseout", onOut);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("focusin", onFocus);
      document.removeEventListener("focusout", onOut);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  if (!tip) return null;
  return createPortal(
    <div
      className="fvd-tip"
      role="tooltip"
      id={TIP_ID}
      style={{
        left: tip.x,
        top: tip.y,
        transform: tip.below ? "translate(-50%, 0)" : "translate(-50%, -100%)",
      }}
    >
      <span className="fvd-tip-copy">
        <span className="fvd-tip-label">{tip.label}</span>
        {tip.detail && <span className="fvd-tip-detail">{tip.detail}</span>}
      </span>
      {tip.hint && <kbd className="fvd-tip-key">{tip.hint}</kbd>}
    </div>,
    document.body,
  );
}
