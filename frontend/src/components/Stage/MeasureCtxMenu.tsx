// Right-click menu for one annotation on the measure overlay: colour
// swatches, end symbol, per-annotation label font size, caption edit,
// label-position reset, delete — plus the dismiss backdrop behind it.
//
// Extracted verbatim from MeasureOverlay.tsx. It renders a fragment of the
// same two sibling divs in the same order, so the overlay's DOM is unchanged.

import type { Size } from "../../lib/geometry";
import { linearUnitToNm, type DisplayUnit } from "../../lib/lengthUnits";
import { loadPrefs } from "../../lib/prefs";
import { simplifyRing } from "../../lib/simplifyRing";
import {
  useViewer,
  type EndSymbol,
  type Measure,
  type View,
} from "../../store/viewer";
import { findHoleHost } from "./pointerDecisions";

/** Measure kinds with a length or area label the Units menu can retarget
 *  (owner spec: "lines, polylines, box/ellipse/polygon/lasso" — "box" is
 *  the rectangular ROI kind (glyph ▭, `measureTools.ts` label "ROI"),
 *  "ellipse" the ellipse ROI; both carry a calibrated `area` alongside
 *  their μ/σ readout, see roiStats/RoiStats. Angle is excluded — degrees
 *  are not a length/area unit). */
const UNIT_MENU_KINDS: ReadonlySet<Measure["kind"]> = new Set([
  "distance",
  "profile",
  "polyline",
  "roi",
  "ellipse",
  "polygon",
  "lasso",
]);

/** The Units group's fixed option list — value `undefined` is "Image
 *  default" (clears the override), matching setMeasureDisplayUnit's
 *  `DisplayUnit | undefined` contract. */
const UNIT_OPTIONS: { value: DisplayUnit | undefined; label: string }[] = [
  { value: undefined, label: "Image default" },
  { value: "auto", label: "Auto" },
  { value: "A", label: "Å" },
  { value: "nm", label: "nm" },
  { value: "um", label: "µm" },
  { value: "mm", label: "mm" },
];

/** Which annotation the menu is acting on, and where it was opened. */
export interface MeasureCtxTarget {
  mid: string;
  x: number;
  y: number;
  /** Set only via the handle's own context-menu path (MeasureOverlay's
   *  onVertexContextMenu) — gates "Delete vertex" below, since a right-
   *  click on the body/label doesn't know which vertex, if any. */
  vertexIndex?: number;
}

interface Props {
  imageId: string;
  /** live measures for this image — the menu resolves `at.mid` against it */
  measures: Measure[];
  at: MeasureCtxTarget;
  /** image calibration (ImageMeta.pixel_size/.pixel_unit) — gates the
   *  Units group: null pixelSize (uncalibrated) or an unconvertible
   *  pixelUnit (reciprocal "1/nm", unrecognized) disables it. */
  pixelSize: number | null;
  pixelUnit: string;
  /** overlay-wide end symbol, shown as active when the measure has none */
  defaultEndSymbol: EndSymbol;
  /** overlay-wide label font size, the fallback in the font-size prompt */
  globalFont: number;
  /** current per-image view — "Simplify outline" converts the lasso
   *  simplify preference (screen px) to image px at the CURRENT zoom
   *  (Convention 3), so it needs view.z here. */
  view: View;
  /** image pixel dimensions — `pts` are stored normalized ([0,1] fraction
   *  of img.w/img.h, same convention as the rest of the store); simplify
   *  needs true (isotropic) image-px points so the epsilon comparison
   *  isn't skewed by a non-square image, then converts the result back. */
  img: Size;
  onClose: () => void;
}

export default function MeasureCtxMenu({
  imageId,
  measures,
  at,
  pixelSize,
  pixelUnit,
  defaultEndSymbol,
  globalFont,
  view,
  img,
  onClose,
}: Props) {
  const setMeasureStyle = useViewer((s) => s.setMeasureStyle);
  const setMeasureFontSize = useViewer((s) => s.setMeasureFontSize);
  const setMeasureDisplayUnit = useViewer((s) => s.setMeasureDisplayUnit);
  const setAllMeasureDisplayUnits = useViewer((s) => s.setAllMeasureDisplayUnits);
  const removeMeasure = useViewer((s) => s.removeMeasure);
  const addHole = useViewer((s) => s.addHole);
  const removeHole = useViewer((s) => s.removeHole);
  const updateMeasure = useViewer((s) => s.updateMeasure);
  const pushUndo = useViewer((s) => s.pushUndo);

  // Plan item 4 — DRAW a hole: a polygon/lasso ring fully contained by
  // another region offers "Mark as hole" (findHoleHost — pointerDecisions
  // .ts — picks the smallest containing region deterministically); a
  // region that already HAS holes offers the reverse, one entry per hole.
  const target = measures.find((x) => x.id === at.mid);
  const holeHostId =
    target && (target.kind === "polygon" || target.kind === "lasso")
      ? findHoleHost(measures, target.id, target.pts)
      : null;
  const holes = target?.holes ?? [];

  // Measure display-units feature — "Units" group, offered only for the
  // kinds that carry a length/area label (UNIT_MENU_KINDS above). Disabled
  // (with an explanatory title, same idiom as the other absent/disabled
  // items in this menu) when the image is uncalibrated or its calibration
  // unit cannot be linearly converted (reciprocal "1/nm", unrecognized) —
  // never silently "converts" those.
  const showUnitsGroup = !!target && UNIT_MENU_KINDS.has(target.kind);
  const unitsDisabledReason =
    pixelSize == null
      ? "image is uncalibrated (px) — units cannot be converted"
      : linearUnitToNm(pixelUnit) == null
        ? `calibration unit "${pixelUnit}" cannot be converted (reciprocal or unrecognized)`
        : null;

  // Lasso-editing plan, item D step 2 — "Delete vertex" joins this menu
  // (Convention 6): only for the closed-ring kinds with an editable vertex
  // list (a line/angle/etc's endpoint isn't deletable), only when the
  // handle's own context-menu path recorded WHICH vertex, and disabled
  // (here: absent, same idiom as "Mark as hole") at <= 3 vertices — a
  // polygon must stay a polygon.
  const canDeleteVertex =
    !!target &&
    (target.kind === "polygon" || target.kind === "lasso") &&
    at.vertexIndex != null &&
    target.pts.length > 3;

  // Lasso-editing plan, item C — retroactive "Simplify outline": unlike
  // "Delete vertex" it acts on the whole ring, not one right-clicked
  // vertex, so it doesn't gate on at.vertexIndex — a right-click on the
  // body or label offers it too (same idiom as "Mark as hole"). Retroactive
  // simplify is user-invoked, so BOTH ring kinds qualify (Convention 5
  // restricts only capture-time auto-simplify to lasso). Hidden (same
  // "absent" idiom as "Delete vertex") when it can't do anything useful —
  // a triangle can't be simplified further.
  const canSimplify =
    !!target &&
    (target.kind === "polygon" || target.kind === "lasso") &&
    target.pts.length > 3;

  return (
    <>
      <div
        className="fvd-ctx-menu fvd-glass"
        style={{ left: at.x, top: at.y }}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <div className="fvd-ctx-swatches">
          {[
            "#ffffff",
            "#22d3ee",
            "#fbbf24",
            "#f472b6",
            "#a3e635",
            "#f43f5e",
          ].map((c) => (
            <button
              key={c}
              className="fvd-swatch"
              style={{ background: c }}
              title="Set annotation color"
              onClick={() => {
                setMeasureStyle(imageId, at.mid, { color: c });
                onClose();
              }}
            />
          ))}
        </div>
        <div className="fvd-ctx-label">End symbol</div>
        <div className="fvd-ctx-sym-row">
          {(["bar", "none", "circle", "square", "cross"] as EndSymbol[]).map(
            (sym) => {
              const active =
                (measures.find((x) => x.id === at.mid)?.endSymbol ??
                  defaultEndSymbol) === sym;
              return (
                <button
                  key={sym}
                  className={`fvd-ctx-sym${active ? " active" : ""}`}
                  title={sym}
                  onClick={() => {
                    setMeasureStyle(imageId, at.mid, { endSymbol: sym });
                    onClose();
                  }}
                >
                  {sym === "bar"
                    ? "|"
                    : sym === "none"
                      ? "—"
                      : sym === "circle"
                        ? "○"
                        : sym === "square"
                          ? "□"
                          : "×"}
                </button>
              );
            },
          )}
        </div>
        <div className="fvd-ctx-sep" />
        <button
          className="fvd-ctx-item"
          title="Set this annotation's label font size"
          onClick={() => {
            const m = measures.find((x) => x.id === at.mid);
            const cur = m?.fontSize ?? globalFont;
            const t = window.prompt(
              `Font size (px, current: ${cur}):`,
              String(cur),
            );
            if (t !== null) {
              const n = Number(t);
              if (Number.isFinite(n) && n > 0) {
                setMeasureFontSize(imageId, at.mid, n);
              } else if (t.trim() === "" || t === "0") {
                setMeasureFontSize(imageId, at.mid, null);
              }
            }
            onClose();
          }}
        >
          Font size…
        </button>
        <div className="fvd-ctx-sep" />
        <button
          className="fvd-ctx-item"
          title="Edit the annotation's caption text"
          onClick={() => {
            const m = measures.find((x) => x.id === at.mid);
            const t = window.prompt("Caption:", m?.text ?? "");
            if (t !== null) {
              useViewer.getState().setMeasureText(imageId, at.mid, t);
            }
            onClose();
          }}
        >
          Edit caption…
        </button>
        <button
          className="fvd-ctx-item"
          title="Snap the caption back to its default position"
          onClick={() => {
            setMeasureStyle(imageId, at.mid, {
              labelDx: 0,
              labelDy: 0,
            });
            onClose();
          }}
        >
          Reset label position
        </button>
        {showUnitsGroup && (
          <>
            <div className="fvd-ctx-sep" />
            <div className="fvd-ctx-label" title={unitsDisabledReason ?? undefined}>
              Units
            </div>
            {UNIT_OPTIONS.map((opt) => {
              const active = (target?.displayUnit ?? undefined) === opt.value;
              return (
                <button
                  key={opt.label}
                  className="fvd-ctx-item"
                  disabled={!!unitsDisabledReason}
                  title={
                    unitsDisabledReason ??
                    (opt.value === undefined
                      ? "Render this measure in the image's calibration unit"
                      : `Display this measure's label in ${opt.label}`)
                  }
                  onClick={() => {
                    setMeasureDisplayUnit(imageId, at.mid, opt.value);
                    onClose();
                  }}
                >
                  {opt.label}
                  {active ? " ✓" : ""}
                </button>
              );
            })}
            <button
              className="fvd-ctx-item"
              disabled={!!unitsDisabledReason}
              title={
                unitsDisabledReason ??
                "Apply this measure's unit choice to every measure on this image"
              }
              onClick={() => {
                setAllMeasureDisplayUnits(imageId, target?.displayUnit);
                onClose();
              }}
            >
              Apply to all measures on this image
            </button>
          </>
        )}
        {holeHostId && (
          <button
            className="fvd-ctx-item"
            title="Subtract this ring from the smallest region that fully contains it"
            onClick={() => {
              addHole(imageId, holeHostId, at.mid);
              onClose();
            }}
          >
            Mark as hole
          </button>
        )}
        {holes.length > 0 && (
          <>
            <div className="fvd-ctx-sep" />
            <div className="fvd-ctx-label">Holes</div>
            {holes.map((_, i) => (
              <button
                key={i}
                className="fvd-ctx-item"
                title="Restore this hole as its own region"
                onClick={() => {
                  removeHole(imageId, at.mid, i);
                  onClose();
                }}
              >
                Remove hole {i + 1}
              </button>
            ))}
          </>
        )}
        {canSimplify && (
          <button
            className="fvd-ctx-item"
            title="Reduce this outline's vertex count — uses the lasso simplify preference at the current zoom; zoom in first for a gentler pass"
            onClick={() => {
              const before = target!.pts;
              // pts are stored normalized (fraction of img.w/img.h); convert
              // to true image px so epsilon (also image px, Convention 3)
              // compares isotropically even when img.w !== img.h, then
              // convert the simplified ring back to the stored convention.
              const beforePx = before.map((p) => ({
                x: p.x * img.w,
                y: p.y * img.h,
              }));
              const epsilon = loadPrefs().lassoCloseSimplifyPx / view.z;
              const afterPx = simplifyRing(beforePx, epsilon);
              if (afterPx.length < before.length) {
                const after = afterPx.map((p) => ({
                  x: p.x / img.w,
                  y: p.y / img.h,
                }));
                updateMeasure(imageId, at.mid, after);
                pushUndo({
                  t: "measure-move",
                  imageId,
                  measureId: at.mid,
                  before,
                  after,
                });
              } else {
                useViewer
                  .getState()
                  .setStatus("outline already simplified — no vertices removed");
              }
              onClose();
            }}
          >
            Simplify outline
          </button>
        )}
        {canDeleteVertex && (
          <button
            className="fvd-ctx-item"
            title="Remove this vertex from the outline"
            onClick={() => {
              const before = target!.pts;
              const after = before.filter((_, i) => i !== at.vertexIndex);
              updateMeasure(imageId, at.mid, after);
              pushUndo({
                t: "measure-move",
                imageId,
                measureId: at.mid,
                before,
                after,
              });
              onClose();
            }}
          >
            Delete vertex
          </button>
        )}
        <button
          className="fvd-ctx-item danger"
          title="Delete this annotation"
          onClick={() => {
            removeMeasure(imageId, at.mid);
            onClose();
          }}
        >
          Delete
        </button>
      </div>
      <div
        className="fvd-ctx-backdrop"
        onPointerDown={() => onClose()}
        onContextMenu={(e) => {
          e.preventDefault();
          onClose();
        }}
      />
    </>
  );
}
