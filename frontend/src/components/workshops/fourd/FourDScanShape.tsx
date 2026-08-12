// Scan-shape control for a headerless acquisition (PLAN_4DSTEM #14).
//
// Merlin writes frames back to back and records nothing about the raster, so
// every .mib opens as a 1×N line-scan and the nav minimap is a 10-px strip.
// The parser has always accepted a scan_shape; nothing exposed it. This is
// the exposure: type the raster, or click one of the factorisations the
// server ranked, and the file is re-opened under it.
//
// Deliberately absent for a format that records its own navigation axes
// (`scan_shape_from_file`): re-rastering those would be offering to
// contradict the acquisition, and the server refuses it anyway.

import { useEffect, useState } from "react";

import type { FourDMeta } from "../../../lib/api";

export default function FourDScanShape({
  meta,
  busy,
  onApply,
}: {
  meta: FourDMeta | null;
  busy: boolean;
  onApply: (rows: number, cols: number) => void;
}) {
  const [rows, setRows] = useState("");
  const [cols, setCols] = useState("");

  // Seed from whatever the dataset currently claims, and re-seed when the
  // selection or the applied shape changes — a stale 1×12 sitting in the
  // fields after a successful 3×4 reads as "the reshape did not take".
  useEffect(() => {
    setRows(meta ? String(meta.scan_shape[0]) : "");
    setCols(meta ? String(meta.scan_shape[1]) : "");
  }, [meta?.id, meta?.scan_shape[0], meta?.scan_shape[1]]);

  // `scan_shape_from_file` defaults TRUE when absent: a meta that does not
  // say a raster is a guess must not be offered a re-raster.
  if (!meta || (meta.scan_shape_from_file ?? true)) return null;
  const options = meta.scan_shape_options ?? [];
  const nFrames = meta.n_frames || meta.scan_shape[0] * meta.scan_shape[1];

  const r = Number(rows);
  const c = Number(cols);
  const product = r * c;
  const valid =
    Number.isInteger(r) && Number.isInteger(c) && r > 0 && c > 0 &&
    product === nFrames;
  const unchanged = r === meta.scan_shape[0] && c === meta.scan_shape[1];

  return (
    <div className="fvd-ws-row" aria-label="Scan shape">
      <span className="k" title="This file records no raster — every shape whose product is the frame count is consistent with it">
        Scan
      </span>
      <input
        type="number"
        min={1}
        value={rows}
        style={{ width: 68 }}
        aria-label="Scan rows"
        onChange={(e) => setRows(e.target.value)}
      />
      <span>×</span>
      <input
        type="number"
        min={1}
        value={cols}
        style={{ width: 68 }}
        aria-label="Scan columns"
        onChange={(e) => setCols(e.target.value)}
      />
      <span className={valid ? "k" : "fvd-ws-note"}>
        {valid
          ? `${nFrames} frames`
          : `must multiply to ${nFrames} frames (got ${
              Number.isFinite(product) ? product : "—"
            })`}
      </span>
      <button
        className="fvd-btn primary"
        disabled={!valid || unchanged || busy}
        title={
          unchanged
            ? "This is already the scan shape"
            : "Re-open the file with this raster"
        }
        onClick={() => onApply(r, c)}
      >
        Apply
      </button>
      {options.length > 0 && (
        <>
          <span className="k">or</span>
          <div className="fvd-seg">
            {options.slice(0, 6).map(([or_, oc]) => (
              <button
                key={`${or_}x${oc}`}
                type="button"
                className={`fvd-seg-btn${
                  or_ === meta.scan_shape[0] && oc === meta.scan_shape[1]
                    ? " active"
                    : ""
                }`}
                disabled={busy}
                title={`Re-raster to ${or_} × ${oc}`}
                onClick={() => {
                  setRows(String(or_));
                  setCols(String(oc));
                  onApply(or_, oc);
                }}
              >
                {or_}×{oc}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
