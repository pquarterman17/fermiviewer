// Calibration manager (checklist M closer): list / apply / delete the
// stored per-instrument pixel calibrations (io/calibration_db.py).

import { useEffect, useState } from "react";

import {
  applyCalibrationKey,
  deleteCalibration,
  listCalibrations,
  type CalibrationEntry,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import ModalDialog from "./ModalDialog";

export default function CalibrationManager() {
  const open = useViewer((s) => s.calibOpen);
  const setOpen = useViewer((s) => s.setCalibOpen);
  const activeId = useViewer((s) => s.activeId);
  const setStatus = useViewer((s) => s.setStatus);

  const [entries, setEntries] = useState<Record<string, CalibrationEntry>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    listCalibrations()
      .then(setEntries)
      .catch((e: Error) => setStatus(`calibrations: ${e.message}`));
  }, [open, setStatus]);

  if (!open) return null;

  const keys = Object.keys(entries).sort();

  const apply = (key: string) => {
    if (!activeId) return;
    setBusy(true);
    applyCalibrationKey(activeId, key)
      .then((r) => {
        useViewer.setState((s) => ({
          images: { ...s.images, [r.image.id]: r.image },
        }));
        setStatus(`calibrated: ${r.image.pixel_size} ${r.image.pixel_unit}/px`);
      })
      .catch((e: Error) => setStatus(`apply: ${e.message}`))
      .finally(() => setBusy(false));
  };

  const remove = (key: string) => {
    setBusy(true);
    deleteCalibration(key)
      .then(() =>
        setEntries((es) => {
          const next = { ...es };
          delete next[key];
          return next;
        }),
      )
      .catch((e: Error) => setStatus(`delete: ${e.message}`))
      .finally(() => setBusy(false));
  };

  return (
    <ModalDialog
      ariaLabel="Calibrations"
      className="fvd-export"
      onClose={() => setOpen(false)}
    >
        <h2>Calibrations</h2>
        {keys.length === 0 ? (
          <div className="fvd-ws-empty">
            No stored calibrations. Use Image → Calibrate Pixel Size… with a
            save key to add one.
          </div>
        ) : (
          <table className="fvd-ws-table">
            <thead>
              <tr>
                <th>Instrument | mag</th>
                <th>px size</th>
                <th>saved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k} title={entries[k].note}>
                  <td>{k}</td>
                  <td>
                    {entries[k].pixel_size} {entries[k].unit}
                  </td>
                  <td>{entries[k].saved}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button
                      className="fvd-btn"
                      disabled={busy || !activeId}
                      title="Apply to the active image"
                      onClick={() => apply(k)}
                    >
                      Apply
                    </button>{" "}
                    <button
                      className="fvd-icon-btn"
                      disabled={busy}
                      title="Delete"
                      onClick={() => remove(k)}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={() => setOpen(false)}
            title="Close the calibration manager (Esc)"
          >
            Close
          </button>
        </div>
    </ModalDialog>
  );
}
