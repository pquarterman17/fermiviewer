# ADR 0011 — Known standards, derived factor sets, and QC findings beside every composition

**Status:** Accepted
**Date:** 2026-09-07
**Modules:** `src/fermiviewer/io/standards_model.py`, `src/fermiviewer/io/standards_db.py`, `src/fermiviewer/io/factors_db.py`, `src/fermiviewer/calc/eds_factors.py`, `src/fermiviewer/calc/eds_qc.py`, `src/fermiviewer/routes/standards.py`, `src/fermiviewer/routes/factors.py`
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 5b — the 5C stack's second, third and fourth boxes
**Builds on:** ADR 0009 (profiles: the `Quantity`/`Validity`/`Provenance` vocabulary and the store rules), ADR 0010 (quantitative routes resolve acquisition parameters and report where each came from)

---

## Context

`K_FACTORS_200KV` is 47 numbers from one instrument at one voltage,
applied on every instrument at every voltage, and the extrapolation is
invisible in the answer. That is the whole problem this ADR addresses:
not that the table is bad, but that a composition computed from it looks
exactly like a composition computed from factors measured on the actual
microscope.

The fix is the one microanalysis has always used — measure something whose
composition you already know — and the work is in making the result
traceable rather than in the arithmetic, which is a two-line inversion of
quantification this repo already ships.

## Decision

### 1. A standard is a material, not a measurement

`Standard` carries a composition, optional bulk properties, and
provenance. Where and when it was measured are `ReferenceRegion` entries
naming an image and a region reference.

The consequence that matters: **a stored image id is not checked at
storage time.** A standard outlives the session that measured it, so
refusing to save one whose session has closed would make the store
useless. A stale reference is an error at DERIVATION time, where the user
can act on it.

### 2. The composition basis is stored, never inferred

wt% and at% are not interchangeable without the atomic weights, and a
certificate quoting 61.5% means different things under each. `basis` is
required — there is no default, because a default here is a guess that
costs exactly the accuracy the standard was brought in to provide.

Conversion happens once, in `eds_factors.weight_fractions`, because both
derivations need weight fractions and doing it at two call sites is how
two spellings drift.

A certificate that lists only the majors is normalised rather than
rejected: the ratios a derivation uses must not depend on whether the
balance was quoted.

### 3. Derivation inverts the shipped quantification, and is tested against it

* `k_i ∝ w_i/I_i` — from `calc.eds.cliff_lorimer`'s own `w_i ∝ k_i·I_i`.
* `ζ_i = C_i·ρt·D_e/I_i` — from `calc.eds_zeta`'s `C_i·ρt = ζ_i·I_i/D_e`.

Both conventions are taken from those functions rather than from a
textbook that might spell them differently, and both are verified by
ROUND TRIP: a factor derived from a known composition is fed back into
the shipped quantifier, which must return the composition it came from.
That checks the derivation against an independent implementation of the
same physics rather than against its own arithmetic restated — the
failure mode a derivation test is most prone to.

k is defined only up to its reference element, so the reference is stored.
It defaults to Si where present (matching the built-in table's `Si: 1.00`,
so the two are directly comparable), else the major element, which carries
the smallest relative counting error and so contaminates the set least.
`k_ref` comes back with σ exactly 0: it is a definition, not a measurement.

ζ needs the standard's certified mass-thickness. A standard without one
cannot yield ζ, and that is a refusal rather than a fallback — there is no
way to guess ρt that does not simply invent the answer.

### 4. Factor sets are immutable

A profile is a description that gets corrected; a factor set is a
measurement. Editing one in place would silently change what an already
published composition was computed with. So the store has create and
delete and no `update` and no history — re-measuring makes a new set.

Each set records the conditions it is a factor FOR, above all the beam
voltage. That is precisely what the built-in table lacks, and what lets
`check_factor_conditions` say "these were derived at 200 kV and you are at
80" instead of the user finding out from a discrepant result months later.

### 5. Comparison replaces neither side

`GET /factors/{id}/compare` reports the measured and built-in values with
their ratio, and resolves nothing. A large disagreement is information
about the instrument; adopting one number silently would destroy it.

The built-in table is rebased onto the derived set's reference element
before comparing. Without that, every ratio carries a constant offset that
looks like disagreement but is only a difference of convention.

A ζ set has no built-in counterpart — this build ships no absolute ζ
table — and says so rather than comparing against something else.

### 6. QC findings, not exceptions

Every check returns findings and the number is still computed. A check
that should refuse belongs in the calculation, not in QC. Each finding
carries a stable code, a severity, a sentence a scientist can act on, and
the numbers behind it so nobody takes the sentence on faith.

`"error"` never means the value is absent — only that it should not be
published as it stands.

Counting statistics are graded on the INTENSITY, not on the final
percentage, because Cliff-Lorimer normalises: an element measured on nine
counts still comes back as a confident-looking 4.1 at% once every
element's share is forced to sum to 100.

### 7. The one calculation that reads solid angle and efficiency

ADR 0010 left `detector.solid_angle` and `detector.efficiency` unwired
because nothing consumed them. `transfer_zeta` is the consumer: ζ counts
collected photons, so `ζ ∝ 1/(Ω·ε)` and moving a set between detector
geometries is a ratio of collected signal.

It is approximate in a way that is stated rather than hidden: a single
efficiency ratio is only right when the two detectors' efficiency CURVES
have the same shape over the lines used. Two different windows do not, so
the transferred σ is widened rather than carried across unchanged.

`detector.window_thickness` and `acquisition.dwell_time` remain unwired.
Modelling the window means an energy-dependent efficiency curve, which is
a bigger piece than a factor transfer and does not belong bolted onto it.

### 8. Derivation is a registered op; the stores are not

The coverage table enforces "an analysis endpoint owes a registered op",
and `/factors/derive` is analysis — it fits peaks and produces numbers.
So `eds_derive_factors` is registered, and it takes the composition
INLINE rather than a `standard_id`.

That is not a convenience. A recipe is a portable record, and a step
naming a per-user store id replays only on the machine holding that
standard. The route accepts either form; the op accepts only the portable
one, and the route's inline path is validated by exactly the same
`standard_from_json` the store uses so the two cannot diverge on what
counts as a valid composition.

The standards and factor STORES have no ops for the same reason the
profile store has none: they are per-user state, not calculations.
`/factors/{id}/transfer` also has none, but for a different reason worth
recording — it reads no dataset at all (its inputs are a stored set and
two solid angles), so it does not fit the op contract, which is a
function OF a dataset. It is classified as store arithmetic rather than
assigned to a shipped wave it had no part in.

## Known limits

* **`check_peak_interference` sees principal lines only.** `line_energy`
  returns one line per element, so a Kβ/Kα clash — Ti Kβ 4.93 under V Kα
  4.95, the standing example — is not caught. Silence from this check
  means "no interference between the lines being integrated", which is
  the question a caller can act on, and is weaker than "no interference".
  Pinned as a test so the limit is not mistaken for coverage.
* **Derivation fits the whole summed spectrum.** A `region`/`roi` on the
  request is recorded in the factor set's provenance but does not yet
  restrict which pixels are summed; that needs the region contract wired
  through the spectral path, which is its own change.
* **No absolute ζ table ships**, so a derived ζ set can only be compared
  against another derived set.

## Verification

- `tests/test_standards_factors.py` — the composition record and its
  refusals, at%→wt% conversion, both round trips through the shipped
  quantifiers, the uncertainty algebra, and every QC rule including the
  documented interference limit.
- `tests/test_api_standards_factors.py` — the stores through the API,
  versioned edits keeping history, reference regions surviving a closed
  session and failing at derivation, a hand-worked k value
  (`k_Cr = (0.30/6000)/(0.70/21000) = 1.5`), comparison leaving the
  stored set untouched, and QC findings on `/eds/quantify`.
