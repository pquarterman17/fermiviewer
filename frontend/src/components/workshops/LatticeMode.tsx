import { useEffect, useState } from "react";

import { analyzeLattice, imageFft } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import StructurePreview from "./StructurePreview";

export default function LatticeMode({ id }: { id: string }) {
  const setStatus = useViewer((s) => s.setStatus);
  const [fftId, setFftId] = useState<string | null>(null);
  const [spots, setSpots] = useState<[number, number][]>([]);
  const [table, setTable] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    setFftId(null);
    setSpots([]);
    setTable(null);
    let stale = false;
    imageFft(id)
      .then((meta) => {
        if (!stale) setFftId(meta.id);
      })
      .catch((error: Error) => setStatus(`lattice: ${error.message}`));
    return () => {
      stale = true;
    };
  }, [id, setStatus]);

  const onClick = (rowCol: [number, number]) => {
    const next = [...spots, rowCol].slice(-2) as [number, number][];
    setSpots(next);
    setTable(null);
    if (next.length !== 2) return;

    analyzeLattice(id, next[0], next[1])
      .then((result) =>
        setTable({
          a: `${result.a.toFixed(3)} ${result.unit}`,
          b: `${result.b.toFixed(3)} ${result.unit}`,
          γ: `${result.gamma_deg.toFixed(2)}°`,
          "d₁": `${result.d_spacing1.toFixed(3)} ${result.unit}`,
          "d₂": `${result.d_spacing2.toFixed(3)} ${result.unit}`,
          A_cell: `${result.unit_cell_area.toFixed(4)} ${result.unit}²`,
        }),
      )
      .catch((error: Error) => setStatus(`lattice: ${error.message}`));
  };

  return (
    <>
      {fftId && (
        <StructurePreview
          id={fftId}
          markers={spots.map(([row, col]) => ({ x: col, y: row }))}
          color="var(--capture)"
          onClick={onClick}
        />
      )}
      <div className="fvd-ws-note">
        {spots.length < 2
          ? `Click ${2 - spots.length} non-collinear spot${
              spots.length === 1 ? "" : "s"
            } on the FFT.`
          : "Click again to restart."}
      </div>
      {table && (
        <table className="fvd-ws-table">
          <tbody>
            {Object.entries(table).map(([key, value]) => (
              <tr key={key}>
                <td>{key}</td>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
