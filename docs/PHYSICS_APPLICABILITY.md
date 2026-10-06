# Physics intent and applicability rules

The `contrainte.physics` package is a bounded kernel for specification sections 13.1 and 13.3. It records the engineering question as a `contrainte.physics-intent/0.1` document, before any software is selected. It then checks that intent against a pinned `contrainte.applicability-rules/0.1` rule set. To do this, it computes declared dimensionless groups exactly from unit-checked inputs and classifies each group against bands that the caller declares and cites.

**Claim boundary.** If every rule is satisfied, that only means the declared rules accept the declared inputs. It is not physical validation, solver qualification, intended-use acceptance or release approval. Every report sets release, approval, write and control authority to false, `human_review_required` to true and `qualification_level` to `none`. The kernel runs no solver and calls no external engine. All shipped rules and inputs are synthetic illustrations, and their thresholds are not scientific defaults.

## Command flow

```powershell
python -m contrainte.physics rules-pin examples/physics-rules-illustrative.json
python -m contrainte.physics evaluate examples/physics-intent-duct-flow.json examples/physics-rules-illustrative.json --output-dir artifacts/physics-duct
python -m contrainte.physics verify artifacts/physics-duct
python -m contrainte.physics verify artifacts/physics-duct/applicability-report.json --intent examples/physics-intent-duct-flow.json --rules examples/physics-rules-illustrative.json
python -m contrainte.physics groups
python -m contrainte.physics schema intent --output schemas/physics-intent-0.1.schema.json
```

`evaluate` writes three files with canonical bytes: `physics-intent.json`, `applicability-rules.json` and `applicability-report.json`. It verifies the retained bundle before it returns.

| Exit | Meaning |
| --- | --- |
| 0 | Success. For `evaluate`, the report was written and verified with state `rules_satisfied`. |
| 2 | Usage error. |
| 3 | Input rejected (schema, units, identifiers, references or numbers). No report is written. |
| 4 | Stale pin (rule set or group registry). No report is written. |
| 5 | Verification or integrity failure. This includes a citation excerpt whose digest does not match. |
| 10 / 11 / 12 | The report was written and verified, with state `marginal_review_required` / `indeterminate` / `rules_violated`. |

The duct example exits 10, because Ma = 31/100 falls in the declared marginal band. The bracket example exits 12, because span/depth = 15/2 falls outside every declared band.

## Exact numbers and dimensional quantities

Every engineering number is a JSON string in exact decimal form, for example `"0.31"` or `"1.5e-3"`. The kernel rejects JSON numbers, booleans, NaN and Infinity, exponents beyond two digits, significands longer than 40 digits and negative zero. Values become `fractions.Fraction` and are never rounded. The exported JSON Schemas check structure only. JSON Schema counts `1.0` as an integer, so a float literal such as `"rule_version": 1.0` is rejected by the strict loader and the parsers, not by the schema. Each result is reported as `{"rational": "p/q", "decimal": exact text or null}`. `decimal` is null when the expansion does not terminate, for example 1/24.

A quantity has the form `{"value", "unit", "kind"}`. Each kind has a dimension vector over length, mass, time and temperature. A unit is accepted only if its dimension equals the dimension of the kind. Each unit has an exact rational SI factor. For example, `km/h` is 5/18 m/s, so 379.44 km/h is exactly 105.4 m/s. This registry is separate from the legacy `contrainte.units.Quantity`, which is unchanged.

Some kinds share a dimension but are never interchangeable: `stress`, `absolute_pressure` and `gauge_pressure`; `thermodynamic_temperature` and `temperature_difference`; `dimensionless` and `strain`. `python -m contrainte.physics groups` prints the full kind and unit tables. Offset temperatures (degC), plane angle, uncertainty, distributions and display units are not supported and are rejected.

## Dimensionless-group registry `contrainte.dimensionless-groups/0.1`

| Form | Value |
| --- | --- |
| `mach.speed_ratio` | V / a |
| `reynolds.dynamic_viscosity` | ρ V L / μ |
| `reynolds.kinematic_viscosity` | V L / ν |
| `knudsen.mean_free_path` | λ / L |
| `beam_slenderness.span_to_depth` | L / h |
| `beam_slenderness.effective_squared` | (K L)² A / I (slenderness squared) |
| `biot.lumped` | h Lc / k |
| `time_scale_ratio.response_to_process` | τ_response / τ_process |
| `shell_thickness_ratio.thickness_to_radius` | t / R |
| `density_variation.relative` | Δρ / ρ_ref |

Each form names its roles. Each role has a required kind, an integer exponent and a domain (positive or non-negative). The kernel checks the bound kinds and confirms that the summed dimension is zero before it computes the result. Irrational quantities are inputs and are never computed. These are the speed of sound √(γRT), the kinetic-theory mean free path and the radius of gyration √(I/A). Rule sets pin the registry digest, which also covers the unit tables. A changed registry therefore makes old rule sets stale instead of silently reinterpreting them.

## Applicability rules

A rule set is closed and versioned (`rule_set_id`, `revision`) and has an authoring status of `draft` or `proposed`. `approved` is rejected, because no identity-backed approval exists. Every rule has these fields:

- `rule_id` and `rule_version`
- the candidate `model_form` it gates
- the group form it uses
- `bands` with at least one `valid` interval and optional `marginal` intervals
- a `rationale`
- at least one resolved citation
- an `on_marginal` review role and instruction
- optional `escalation_model_forms` (the §13.3 hierarchy)

Each citation embeds an excerpt and its SHA-256, and the kernel recomputes that digest.

An interval is `{"lower": bound|null, "upper": bound|null}`, where a bound is `{"value", "inclusive"}`. The kernel rejects:

- reversed or empty intervals;
- any overlap between intervals in a rule, including a shared endpoint that both sides include.

A value outside every interval is `violated`. Boundary equality follows the declared inclusivity exactly.

## Physics intent

The intent covers each §13.1 element as a closed, typed field:

| §13.1 element | Field |
| --- | --- |
| Decision supported | `decision` |
| Target outputs | `target_outputs` (a kind and unit for each quantity of interest) |
| Acceptance criteria or exploratory rationale | `acceptance` (criteria limits are unit-checked against the output kind) |
| Modeled and excluded bodies, simplifications | `geometry` |
| Domains | `domains` (the 24 §13.2 identifiers) |
| Time character and fidelity | `time` |
| Expected nonlinearities | `nonlinearities` |
| Relevant scales | `scales` (each with a basis and evidence or assumption citations) and `group_declarations` |
| Loads, environment state, boundary conditions | `loads`, `environment`, `boundary_conditions` |
| Initial conditions | `initial_conditions` (`not_relevant` or `specified`) |
| Interfaces and coupling | `interfaces` |
| Material model requirements | `materials` |
| Failure modes | `failure_modes` |
| Uncertainty sources | `uncertainty_sources` |
| Validation evidence | `validation_evidence` (available or planned) |
| Model-form alternatives | `model_form_alternatives` (required when `criticality` is `critical`) |

The intent also carries `assumptions` and a `rule_set_pin`. All references must resolve. The pin must match the supplied rule set's id, revision and digest exactly.

## Evaluation and gates

Rules for a model form that is not a candidate are reported as `not_selected`. Every selected rule is evaluated against every declaration of its group form. If there is no such declaration, the rule is `indeterminate` with reason `group_not_declared`. A candidate form with no rule gets the state `no_rule`.

The overall `applicability_state` is the worst state found. From worst to best: `rules_violated`, `indeterminate`, `marginal_review_required`, `rules_satisfied`.

Every marginal outcome creates a warning and an open review task, numbered deterministically as `RVW-<n>`.

`qualified_execution.permitted` is always false. Its blockers are:

- violated or indeterminate rules
- pending marginal reviews
- uncovered model forms
- synthetic citations
- open critical assumptions
- `ai_proposed` inputs
- exploratory acceptance
- a requested mode other than `qualified`
- always: `RULE_SET_NOT_APPROVED`, `NO_IDENTITY_BACKED_APPROVAL` and `NO_QUALIFIED_SOLVER_CAPSULE`

`controlled_review_readiness` is `ready_for_independent_review` only if none of the following is present: a violated or indeterminate rule, an uncovered form, a synthetic citation, an AI-proposed input, an open critical assumption, or exploratory acceptance. It is never an approval.

Exploration mode labels the output `exploratory` and keeps every violation visible. `authority_promotion_permitted` is always false.

## Digests and verification

- The intent digest and the rule-set digest are SHA-256 hashes of the canonical documents.
- The report binds both digests and the registry digest, and also carries `report_digest` over its own canonical body.
- Verification has three steps:
  1. Check the self-digest.
  2. Check the input binding.
  3. Recompute the whole evaluation from the inputs and compare canonical bytes.
- Editing a report breaks its digest. Editing and then re-hashing it fails recomputation. Editing a retained input breaks the binding. A retained file that is not in canonical form is rejected.

## Not implemented

The following are not implemented:

- solver plans, adapters, capsules, meshing, execution, V&V/UQ and result models (§13.4–13.13);
- automatic selection of rules or model forms;
- checks beyond the declared group bands: turbulence wall treatment and separation; shell through-thickness effects; strain, contact and geometric-change checks for linear elasticity; diffusion regimes;
- material lookup;
- embedding `physics_intents` in a CIR document;
- identity, signatures, approvals and audit events;
- uncertainty propagation.

Domains are recorded for the reviewer but are never reported as available for execution.
