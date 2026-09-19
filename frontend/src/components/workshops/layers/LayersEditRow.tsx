// The stage-editing toggle and what it has to say about the operator's
// edits so far.
//
// Split out of `LayersWorkshop.tsx` for the size guard. It is one idea —
// "you can move these lines, and here is how far you have moved them" —
// so it travels together.

export function LayersEditRow({
  editing,
  disabled,
  onEditing,
  movedCount,
}: {
  editing: boolean;
  disabled: boolean;
  onEditing: (on: boolean) => void;
  /** interfaces now sitting somewhere other than where the detector put them */
  movedCount: number;
}) {
  return (
    <>
      <div className="fvd-ws-row">
        <label
          className="k"
          style={{ display: "flex", alignItems: "center", gap: 4 }}
        >
          <input
            type="checkbox"
            checked={editing}
            disabled={disabled}
            onChange={(e) => onEditing(e.target.checked)}
          />
          edit on stage
        </label>
        <span className="k" style={{ fontSize: 10, opacity: 0.7 }}>
          drag a line to nudge · click to add · right-click to remove
        </span>
      </div>
      {movedCount > 0 && (
        <div className="fvd-ws-note">
          {movedCount === 1 ? "1 interface" : `${movedCount} interfaces`} moved
          from where the detector put {movedCount === 1 ? "it" : "them"}; the
          faint dashed line on the stage marks the original. That gap is worth
          keeping — it says where the automatic method needed help on this
          specimen, and both sets are saved with the result.
        </div>
      )}
    </>
  );
}
