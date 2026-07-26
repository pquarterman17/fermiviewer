// Hover tooltips (GUI-enhancements handoff, WS2). A single delegated listener
// watches for [data-tip] elements anywhere in the document and, after a short
// dwell, shows a glass chip with the action name plus its optional
// [data-tip-key] keyboard shortcut. Mounted once at the app root; icon-only
// controls opt in with `data-tip="Measure distance" data-tip-key="D"`.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
// The chip is a single shared node, so it needs stable ids: assistive tech
// only announces a tooltip that its trigger points at via aria-describedby.
const TIP_ID = "fvd-tooltip";
// The trigger's aria-label already IS the tip label, so the description must
// point only at the detail/shortcut nodes — describing the whole chip made
// screen readers announce the name twice.
const DESC_ID = "fvd-tooltip-desc";
const KEY_ID = "fvd-tooltip-key";
// Minimum gap kept between the chip and the viewport edges.
const EDGE_PX = 8;

export default function TooltipLayer() {
  const [tip, setTip] = useState<Tip | null>(null);
  const chipRef = useRef<HTMLDivElement>(null);

  // The chip centers on its trigger, so a trigger near a viewport edge (the
  // 168px filmstrip column) could push half the chip off screen. Clamp after
  // measuring the rendered width; runs before paint, so there is no jump.
  useLayoutEffect(() => {
    const node = chipRef.current;
    if (!node || !tip) return;
    const half = node.offsetWidth / 2;
    const left = Math.min(
      Math.max(tip.x, EDGE_PX + half),
      window.innerWidth - EDGE_PX - half,
    );
    if (left !== tip.x) node.style.left = `${left}px`;
  }, [tip]);

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
        // A label-only tip gets no aria-describedby at all: the label is the
        // control's accessible name already.
        const descIds = [detail && DESC_ID, hint && KEY_ID].filter(Boolean);
        if (descIds.length) {
          el.setAttribute("aria-describedby", descIds.join(" "));
          described = el;
        }
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
      ref={chipRef}
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
        {tip.detail && (
          <span className="fvd-tip-detail" id={DESC_ID}>
            {tip.detail}
          </span>
        )}
      </span>
      {tip.hint && (
        <kbd className="fvd-tip-key" id={KEY_ID}>
          {tip.hint}
        </kbd>
      )}
    </div>,
    document.body,
  );
}
