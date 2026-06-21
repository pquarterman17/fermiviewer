// Draggable scale bar overlay (handoff §4, audit #10). Extracted from
// Stage.tsx so the side-by-side compare panes can reuse the exact same
// bar (smart default position, per-image colour/length/thickness/font/
// unit overrides, EM sub-unit step-down). Parameterized purely by
// imageId + view/img/vp, so it works in any pane.

import { useRef, type RefObject } from "react";

import { imageToScreen, niceScaleLength, type Size } from "../../lib/geometry";
import { loadPrefs } from "../../lib/prefs";
import { useViewer, type View } from "../../store/viewer";

export default function ScaleBarOverlay({
  imageId,
  pixelSize,
  unit,
  view,
  img,
  vp,
  barRef,
}: {
  imageId: string;
  pixelSize: number;
  unit: string;
  view: View;
  img: Size;
  vp: Size;
  barRef: RefObject<HTMLDivElement>;
}) {
  // Scale bar colour: per-image override (audit #10) or white default.
  // Decoupled from measurement overlay colour per user request.
  const sbColor = useViewer((s) => s.scaleBars[imageId]?.color ?? "#ffffff");
  const color = sbColor;
  const visible = useViewer((s) => s.scaleBarVisible);
  const sbState = useViewer((s) => s.scaleBars[imageId]);
  const setScaleBar = useViewer((s) => s.setScaleBar);
  const dragRef = useRef<{ startX: number; startY: number; x0: number; y0: number } | null>(null);

  if (!visible) return null;

  const z = view.z;

  // Default position: bottom-left of the VISIBLE image rectangle, so the
  // bar always lands on real pixels — never in the black letterbox region
  // beside a DM3/DM4 image that doesn't fill the viewport. A user-dragged
  // position (sbState.x/.y, viewport-normalized) overrides this. When the
  // image fills the viewport the visible rect == viewport, so this reduces
  // to the original 2% / 92% corner.
  const tl = imageToScreen(0, 0, view, img, vp);
  const br = imageToScreen(img.w, img.h, view, img, vp);
  const visL = Math.max(0, Math.min(tl.x, br.x));
  const visR = Math.min(vp.w, Math.max(tl.x, br.x));
  const visT = Math.max(0, Math.min(tl.y, br.y));
  const visB = Math.min(vp.h, Math.max(tl.y, br.y));
  // when the image is panned fully off-screen the visible rect collapses
  // (visR ≤ visL); fall back to the viewport corner instead of (0,0)
  const visW = Math.max(0, visR - visL);
  const visH = Math.max(0, visB - visT);
  const leftPx =
    sbState?.x != null
      ? sbState.x * vp.w
      : visW > 0
        ? visL + 0.02 * visW
        : 0.02 * vp.w;
  const topPx =
    sbState?.y != null
      ? sbState.y * vp.h
      : visH > 0
        ? visT + 0.92 * visH
        : 0.92 * vp.h;

  // size
  const autoPhys = niceScaleLength((120 * pixelSize) / z);
  const phys = sbState?.lengthPhys ?? autoPhys;
  const widthPx = (phys / pixelSize) * z;
  const thickness = sbState?.thickness ?? Math.max(2, Math.round(vp.h / 80));
  // per-image override wins; else the Preferences default (20 by default,
  // user request 2026-06-09 — readable at presentation size)
  const fontSize = sbState?.fontSize ?? loadPrefs().scaleBarFontSize;
  // unit override: convert phys (in pixel_unit) to the forced unit
  const unitOverride = sbState?.unitOverride ?? null;
  const label = (() => {
    if (unitOverride) {
      // convert via nm as common base — mirrors _bar_label_with_unit in Python
      const nmPer: Record<string, number> = {
        pm: 1e-3, Å: 0.1, nm: 1, µm: 1e3, um: 1e3, mm: 1e6, m: 1e9,
      };
      const fSrc = nmPer[unit];
      const fTgt = nmPer[unitOverride];
      if (fSrc != null && fTgt != null) {
        const converted = (phys * fSrc) / fTgt;
        return `${Number(converted.toPrecision(3))} ${unitOverride}`;
      }
    }
    return phys >= 1
      ? `${Number(phys.toPrecision(3))} ${unit}`
      : fmtSub(phys, unit);
  })();

  const onPointerDown = (e: React.PointerEvent) => {
    e.stopPropagation();
    // start the drag from wherever the bar currently sits (the smart
    // default until the user has dragged it), as viewport-normalized
    dragRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      x0: leftPx / vp.w,
      y0: topPx / vp.h,
    };
    (e.target as Element).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!dragRef.current || vp.w === 0 || vp.h === 0) return;
    const dx = (e.clientX - dragRef.current.startX) / vp.w;
    const dy = (e.clientY - dragRef.current.startY) / vp.h;
    const nx = Math.min(0.98, Math.max(0, dragRef.current.x0 + dx));
    const ny = Math.min(0.98, Math.max(0, dragRef.current.y0 + dy));
    setScaleBar(imageId, { x: nx, y: ny });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    dragRef.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
  };

  return (
    <div
      ref={barRef}
      className="fvd-scalebar fvd-scalebar-drag"
      style={{ color, left: leftPx, top: topPx, fontSize }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className="bar" style={{ width: widthPx, height: thickness }} />
      <div className="label">{label}</div>
    </div>
  );
}

function fmtSub(phys: number, unit: string): string {
  // step down through the first sub-unit that lands ≥ 1; Å preferred
  // over pm for sub-nm lengths (EM convention)
  const chains: Record<string, [string, number][]> = {
    µm: [
      ["nm", 1e3],
      ["Å", 1e4],
    ],
    um: [
      ["nm", 1e3],
      ["Å", 1e4],
    ],
    nm: [
      ["Å", 10],
      ["pm", 1e3],
    ],
  };
  for (const [u, f] of chains[unit] ?? []) {
    if (phys * f >= 1) {
      return `${Number((phys * f).toPrecision(3))} ${u}`;
    }
  }
  return `${Number(phys.toPrecision(3))} ${unit}`;
}
