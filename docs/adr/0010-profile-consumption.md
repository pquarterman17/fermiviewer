# ADR 0010 — Quantitative routes read applied calibration profiles; a typed value always wins

**Status:** Accepted
**Date:** 2026-09-07
**Modules:** `src/fermiviewer/io/profile_units.py`, `src/fermiviewer/io/profiles_applied.py`, `src/fermiviewer/routes/_eds_params.py`, `src/fermiviewer/routes/eds_quant.py`, `src/fermiviewer/routes/eds_zeta.py`, `src/fermiviewer/routes/eds_advanced.py`
**Plan:** `plans/MICROSCOPY_FEATURE_ROADMAP.md` item 5a, third box (the CONSUMERS) — the first piece of the 5C stack
**Builds on:** ADR 0009 (a profile is a named, versioned record and an image carries a snapshot of the one applied), ADR 0004 §5 (results snapshot their calibration)

---

## Context

ADR 0009 shipped the profile record, the store, the apply/unapply flow and
the result snapshot, and said plainly that nothing consumed a profile yet.
`profile_quantity` was the resolver it left for consumers to call.

So a user could describe their detector's takeoff angle, their probe
current and their beam energy, apply that profile to an image, watch it
ride into the `.fvp` and into every result's calibration snapshot — and
then get a composition computed from `take_off_angle_deg=20`, the literal
default, because no quantitative route ever read it. The profile was
provenance theatre: recorded, displayed, and unused.

Two things make wiring it more delicate than passing a number through.

**A profile field carries a unit, and the consumer's signature carries a
different one.** The store keeps probe current in picoamps because that is
what a detector reports; `dose_electrons` takes nanoamps. Reading `.value`
and ignoring `.unit` puts a factor of 1000 into the dose, and so into the
mass-thickness and every composition derived from it — silently, with the
profile's own provenance attached to lend it authority.

**A profile value does not pass through pydantic.** `take_off_angle_deg`
declares `Field(gt=0, lt=90)` because `zaf_correction` refuses outside
that range. A typed 120 is rejected at the door. A profile's 120 would
walk straight past the guard, which would then be protecting only the
input path nobody gets wrong.

## Decision

1. **A request field a profile can supply becomes `X | None = None`.**
   `None` means "the caller did not state this", which is a different
   thing from any particular number. The route's former literal survives
   as its documented default.

2. **Precedence is request → profile → default, and the request always
   wins.** A profile is a default, never an override. A user who typed a
   number sees that number used, whatever is applied to the image. The
   ordered candidate list lets one field try several sources: `beam_kv`
   asks the acquisition profile before the microscope profile, because
   the acquisition profile describes THIS session while the microscope
   runs at several voltages.

3. **Conversion is dimensional and refuses rather than guesses.**
   `io/profile_units.py` assigns every unit to one dimension; converting
   within a dimension scales, converting across raises. There is no
   "unrecognised unit passes through unchanged" fallback — that is right
   for a display axis (`calc/energy_units.kev_factor`, where the worst
   case is a mislabelled tick) and wrong for a quantity feeding a
   published number. An unreadable stored unit is a 422, **not** a silent
   fall through to the built-in default: answering with 20 deg because
   the applied profile said something this build could not parse hides
   the one thing the user needs to know.

4. **The resolved value is bounds-checked by the same rule as the typed
   one**, and the recorded `params` carry the resolved value rather than
   `null` — a result record is a reproduction key, and a `null` there
   would let a re-run after a profile edit silently produce different
   numbers.

5. **Every response reports where each parameter came from.** The
   `calibration` block gives value, unit, `origin`
   (`request` | `profile` | `default`), and for a profile the
   `profile:<id>@<version>` and the field read. Reported for the defaults
   too: a composition computed on a placeholder 20 deg should not look
   identical to one computed on a measured 35 deg.

6. **kV and keV are not one dimension.** An accelerating voltage and a
   beam energy agree numerically for a singly-charged electron and differ
   in kind. The equivalence is named at the single call site that relies
   on it (`resolve_beam_kv`) rather than licensed table-wide, where it
   would quietly permit every other volt/electronvolt conversion in the
   codebase.

7. **One mapping table, not a copy per route.** `routes/_eds_params.py`
   holds which profile field supplies which request parameter for every
   EDS route. The 4C review named this seam — "a sibling op that never
   got the same fix" — and a per-route copy of a UNIT mapping is its worst
   form: the copies stay plausible while disagreeing, and the symptom is a
   composition off by a factor invisible in the response.

## What is NOT wired, and why

The roadmap box lists nine quantities. Four have no consumer in the
codebase at all, and are deliberately absent from the mapping table
rather than listed against a route that would ignore them:

| Field | State |
| --- | --- |
| `detector.solid_angle` | `calc/eds_zeta.detector_solid_angle_sr` exists and is exported but is **called from nowhere**. Needs a consumer before it needs a wire. |
| `detector.efficiency` | Appears only in a docstring. No calculation takes it. |
| `detector.window_thickness` / `window_material` | No absorption path models the window. |
| `acquisition.dwell_time` | No consumer. |

These are the inputs an ABSOLUTE intensity calculation needs, which is
what ζ-factor derivation from a standard requires — so they arrive with
5C-3, together with the physics that reads them. Wiring them now would
mean adding parameters no calculation consumes, which is the same false
promise as a stale doc claim.

`acquisition.dead_time` has no direct consumer either, but it does have an
indirect one and is wired: a detector reports real time and a dead-time
percentage, and `live = real × (1 − dead/100)` is the live time the dose
integral needs. A profile stating that pair is not missing the parameter.

`routes/eds_maps.py` is deliberately untouched. Its `beam_kv=None` already
means "no line-energy filter — take the K line unconditionally", a
documented meaning distinct from "unstated". Repurposing it would change
which lines an existing caller gets AND remove their ability to ask for
unconditional selection. That is a behaviour decision, not a wiring one.

`thickness_nm` and `density_g_cm3` are properties of the SPECIMEN. No
instrument profile describes them, so they take no candidates.

## Alternatives considered

**Let the profile override a typed value when the profile is newer.**
Rejected: it makes the number a user typed unpredictable, and there is no
reading of "I entered 12 degrees" that means "use 35".

**Convert with a best-effort passthrough on an unknown unit.** Rejected —
see §3. It is the failure mode this ADR exists to close, wearing the
costume of robustness.

**Put kV and keV in one dimension.** Rejected — see §6.

**Keep the literal defaults and merely REPORT what a profile would have
said.** Considered seriously, because it cannot change any existing
number. Rejected: it leaves the actual complaint in place (the applied
profile still does not affect the result) while adding a block that says
so, which is worse than not wiring at all.

## Verification

- `tests/test_profile_consumption.py` — the unit table (every conversion
  pinned as arithmetic, including `2 um → 2000.0 nm` exactly), the
  refusals, and the three-way precedence.
- `tests/test_api_profile_consumption.py` — each wired route through the
  API, the pA→nA conversion checked at the DOSE and not only in the
  report, the bounds a profile would otherwise bypass, the unreadable
  unit, and the recorded reproduction key.
- Both were run against the unwired code: 15 of 16 API tests fail, the
  sixteenth being the pydantic baseline that must be unaffected. Against
  a wired-but-unconverted implementation the probe-current test fails
  `500.0 == 0.5`, so it distinguishes "wired" from "wired correctly".
