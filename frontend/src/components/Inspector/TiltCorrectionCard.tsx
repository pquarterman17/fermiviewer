// Tilt-correction card (#34): stage-tilt angle/axis/geometry controls that
// correct distance/profile/polyline lengths. Split out of MeasurePanel.tsx
// (repo-health #33).

import type { TiltSettings } from "../../lib/geometry";
import type { ViewerState } from "../../store/viewer";
import Card from "./Card";

export default function TiltCorrectionCard({
  activeId,
  tilt,
  setTilt,
}: {
  activeId: string;
  tilt: TiltSettings | null;
  setTilt: ViewerState["setTilt"];
}) {
  return (
    <Card title="Tilt correction" defaultOpen={false}>
      <div className="fvd-ws-note">
        Corrects distance/profile/polyline lengths for stage tilt (#34). 0° =
        off; labels gain a θ marker when active.
      </div>
      <div className="fvd-slider-row">
        <span className="k">Angle (°)</span>
        <input
          type="number"
          min={-89.9}
          max={89.9}
          step={0.1}
          style={{ width: 64 }}
          value={tilt?.angle ?? 0}
          onChange={(e) => {
            const v = Math.max(
              -89.9,
              Math.min(89.9, Number(e.target.value) || 0),
            );
            setTilt(activeId, {
              angle: v,
              axis: tilt?.axis ?? "Y",
              geometry: tilt?.geometry ?? "cross-section",
              seedAngle: tilt?.seedAngle,
            });
          }}
        />
        {tilt?.seedAngle != null &&
          (tilt?.angle ?? 0) !== Number(tilt.seedAngle.toFixed(2)) && (
            <button
              className="fvd-btn"
              title="Apply the stage tilt found in the file metadata"
              onClick={() =>
                setTilt(activeId, {
                  angle: Number(tilt.seedAngle!.toFixed(2)),
                  axis: tilt.axis,
                  geometry: tilt.geometry,
                  seedAngle: tilt.seedAngle,
                })
              }
            >
              Stage: {tilt.seedAngle.toFixed(1)}°
            </button>
          )}
      </div>
      <div className="fvd-slider-row">
        <span className="k">Axis</span>
        <div className="fvd-seg">
          {(["X", "Y"] as const).map((ax) => (
            <button
              key={ax}
              className={`fvd-seg-btn${(tilt?.axis ?? "Y") === ax ? " active" : ""}`}
              onClick={() =>
                setTilt(activeId, {
                  angle: tilt?.angle ?? 0,
                  axis: ax,
                  geometry: tilt?.geometry ?? "cross-section",
                  seedAngle: tilt?.seedAngle,
                })
              }
              title={`Tilt-correction axis: ${ax}`}
            >
              {ax}
            </button>
          ))}
        </div>
      </div>
      <div className="fvd-slider-row">
        <span className="k">Geometry</span>
        <div className="fvd-seg">
          {(
            [
              // MATLAB names on the buttons; formula on hover
              [
                "cross-section",
                "Cross-section",
                "1/sin θ — FIB cross-section",
              ],
              ["surface", "Plan-view", "1/cos θ — tilted plan-view surface"],
            ] as const
          ).map(([g, lbl, hint]) => (
            <button
              key={g}
              className={`fvd-seg-btn${(tilt?.geometry ?? "cross-section") === g ? " active" : ""}`}
              title={hint}
              onClick={() =>
                setTilt(activeId, {
                  angle: tilt?.angle ?? 0,
                  axis: tilt?.axis ?? "Y",
                  geometry: g,
                  seedAngle: tilt?.seedAngle,
                })
              }
            >
              {lbl}
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}
