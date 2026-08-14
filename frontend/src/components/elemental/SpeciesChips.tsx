// A compact horizontal strip of species chips — the connective tissue
// between Maps and Explore (SPECTRAL_WORKSPACE_PLAN #11 Wave 1).
//
// Self-contained on purpose: it reads its species list and selection
// straight from the species store, keyed on `imageId`, rather than taking
// them as props. Maps already writes both (via `setSpecies`/`addSpecies`/
// `selectSpecies`), so mounting this in an Explore tab needs no prop
// plumbing — click a chip here and the row `selectSpecies` picked in Maps
// changes too, because they are the same store slice.
//
// Waves 2/3 mount this in the EDS and EELS Explore tabs; it is not wired up
// anywhere by this wave.

import { useElementColors } from "../../lib/elemental/elementColors";
import { speciesOf, useSpecies } from "../../store/species";

export default function SpeciesChips({
  imageId,
  emptyHint,
}: {
  imageId: string;
  /** Shown in place of the strip when this image has no species yet. */
  emptyHint?: string;
}) {
  const byImage = useSpecies((s) => s.byImage);
  const selectedByImage = useSpecies((s) => s.selectedByImage);
  const selectSpecies = useSpecies((s) => s.selectSpecies);
  const colors = useElementColors();
  const species = speciesOf(byImage, imageId);
  const selectedId = selectedByImage[imageId] ?? null;

  if (species.length === 0) {
    return (
      <div className="fvd-species-chips fvd-species-chips-empty">
        {emptyHint ?? "No species yet — add one from Maps."}
      </div>
    );
  }

  return (
    <div className="fvd-species-chips" role="listbox" aria-label="Species">
      {species.map((s) => {
        const selected = s.id === selectedId;
        return (
          <button
            key={s.id}
            type="button"
            role="option"
            aria-selected={selected}
            className={`fvd-species-chip${selected ? " selected" : ""}`}
            title={
              s.modality === "eels"
                ? `${s.symbol}-${s.transition}`
                : `${s.symbol} ${s.transition}α`
            }
            onClick={() => selectSpecies(imageId, s.id)}
          >
            <span
              className="fvd-species-chip-dot"
              style={{ background: colors(s.symbol) }}
            />
            {s.symbol}
          </button>
        );
      })}
    </div>
  );
}
