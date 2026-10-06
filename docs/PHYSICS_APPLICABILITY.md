# Physics intent and applicability rules

The `contrainte.physics` package is a bounded kernel for specification sections 13.1 and 13.3. It records the engineering question as a `contrainte.physics-intent/0.2` document, before any software is selected. It then checks that intent against a pinned `contrainte.applicability-rules/0.2` rule set. To do this, it computes declared dimensionless groups exactly from unit-checked inputs and classifies each group against bands that the caller declares and cites. A kernel-owned model-form table records which groups each candidate model form must cover and which section 13.3 considerations this kernel cannot evaluate.

**Claim boundary.** If every rule is satisfied, that only means the declared rules accept the declared inputs. It is not physical validation, solver qualification, intended-use acceptance or release approval. Every report sets release, approval, write and control authority to false, `human_review_required` to true and `qualification_level` to `none`. The kernel runs no solver and calls no external engine. All shipped rules and inputs are synthetic illustrations, and their thresholds are not scientific defaults. The model-form table contains no numeric thresholds.

## Versions

| Artefact | Version |
| --- | --- |
| Physics intent | `contrainte.physics-intent/0.2` |
| Rule set | `contrainte.applicability-rules/0.2` |
| Report | `contrainte.physics-applicability-report/0.2` |
| Registry (units, group forms, model-form table) | `contrainte.applicability-registry/0.2` |

The 0.1 versions were unpublished development drafts and are rejected with a "superseded" message. Version 0.2 is a strengthening of 0.1:

- **Registry.** The registry now binds the model-form table into its digest. Rule sets pin it under the `registry` field, which replaces `group_registry`.
- **Rule sets.** A rule whose group is not admissible for its model form is rejected.
- **Intents.** The parser now rejects three things it accepted before:
  - a scale citing a retired assumption;
  - one scale bound to two roles of a group;
  - a candidate model form that `model_form_alternatives` also lists as `rejected`.
- **Reports.** Reports carry two new outcomes: the model-form coverage and consideration outcomes, and an input-support gate.

## Command flow

```powershell
python -m contrainte.physics rules-pin examples/physics-rules-illustrative.json
python -m contrainte.physics evaluate examples/physics-intent-duct-flow.json examples/physics-rules-illustrative.json --output-dir artifacts/physics-duct
python -m contrainte.physics verify artifacts/physics-duct
python -m contrainte.physics verify artifacts/physics-duct/applicability-report.json --intent examples/physics-intent-duct-flow.json --rules examples/physics-rules-illustrative.json
python -m contrainte.physics groups
python -m contrainte.physics schema intent --output schemas/physics-intent-0.2.schema.json
```

`evaluate` writes three files with canonical bytes: `physics-intent.json`, `applicability-rules.json` and `applicability-report.json`. It verifies the retained bundle before it returns.

| Exit | Meaning |
| --- | --- |
| 0 | Success. For `evaluate`, the report was written and verified with state `rules_satisfied`. |
| 2 | Usage error. |
| 3 | Input rejected. This covers schema, units, identifiers, references and numbers. It also covers input files that cannot be read or decoded: invalid UTF-8 (including UTF-16), unpaired surrogates, integers beyond the interpreter digit limit, and nesting too deep to decode. No report is written. With `verify REPORT --intent --rules`, inputs that no longer validate also exit 3. |
| 4 | Stale pin (rule set or registry). No report is written. |
| 5 | Verification or integrity failure. This includes a citation excerpt whose digest does not match, and any retained-bundle file that cannot be read, decoded, kept canonical or re-validated. |
| 6 | Output could not be written, for example when `--output-dir` names an existing file or the schema `--output` path is a directory. A partially written bundle must not be trusted; `verify` will reject it. |
| 10 / 11 / 12 / 13 | The report was written and verified, with state `marginal_review_required` / `indeterminate` / `rules_violated` / `considerations_review_required`. |

The duct example exits 10, because Ma = 31/100 falls in the declared marginal band. The bracket example exits 12, because span/depth = 15/2 falls outside every declared band. Input files must be UTF-8; a leading byte-order mark is ignored. The CLI never prints a Python traceback for malformed input.

## Exact numbers and dimensional quantities

Every engineering number is a JSON string in exact decimal form, for example `"0.31"` or `"1.5e-3"`. The kernel rejects JSON numbers, booleans, NaN and Infinity, exponents beyond two digits, significands longer than 40 digits and negative zero. Values become `fractions.Fraction` and are never rounded. The exported JSON Schemas check structure only. JSON Schema counts `1.0` as an integer, so a float literal such as `"rule_version": 1.0` is rejected by the strict loader and the parsers, not by the schema. Each result is reported as `{"rational": "p/q", "decimal": exact text or null}`. `decimal` is null when the expansion does not terminate, for example 1/24.

A quantity has the form `{"value", "unit", "kind"}`. Each kind has a dimension vector over length, mass, time and temperature. A unit is accepted only if its dimension equals the dimension of the kind. Each unit has an exact rational SI factor. For example, `km/h` is 5/18 m/s, so 379.44 km/h is exactly 105.4 m/s. This registry is separate from the legacy `contrainte.units.Quantity`, which is unchanged.

Some kinds share a dimension but are never interchangeable: `stress`, `absolute_pressure` and `gauge_pressure`; `thermodynamic_temperature` and `temperature_difference`; `dimensionless` and `strain`. `python -m contrainte.physics groups` prints the full kind and unit tables. Offset temperatures (degC), plane angle, uncertainty, distributions and display units are not supported and are rejected.

## Dimensionless-group forms

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

Each form names its roles. Each role has a required kind, an integer exponent and a domain (positive or non-negative). The kernel checks the bound kinds and confirms that the summed dimension is zero before it computes the result. A declaration must bind each scale to at most one role, so a group such as L/L cannot be formed from one scale. Irrational quantities are inputs and are never computed. These are the speed of sound √(γRT), the kinetic-theory mean free path and the radius of gyration √(I/A).

## Model-form table

The registry contains one entry for every model form. Each entry lists:

- **required groups.** Each one needs a rule in the pinned set before the form can be anything other than indeterminate.
- **admissible groups.** These are the only groups a rule for this form may use. A rule on any other group is rejected; for example, `linear_elastic` on `knudsen` is rejected.
- **unevaluated considerations.** These are section 13.3 factors that this kernel cannot evaluate. Each source is cited.

| Model form | Required groups | Admissible groups | Unevaluated considerations |
| --- | --- | --- | --- |
| `euler_bernoulli_beam`, `timoshenko_beam` | beam_slenderness | beam_slenderness | local_stress_needs |
| `thin_shell` | shell_thickness_ratio | shell_thickness_ratio | through_thickness_effects |
| `continuum_solid` | none | none | no_kernel_applicability_criteria |
| `linear_elastic` | none | none | strain_magnitude, material_behavior, contact, geometric_change |
| `incompressible_flow` | mach, density_variation | mach, density_variation | none |
| `compressible_flow` | mach | mach, density_variation | none |
| `laminar_flow`, `turbulent_flow` | reynolds | reynolds | wall_treatment, separation, target_quantity_sensitivity |
| `continuum_flow`, `rarefied_flow` | knudsen | knudsen | none |
| `lumped_capacitance_thermal`, `distributed_conduction_thermal` | biot | biot | none |
| `steady_state`, `transient_response`, `quasi_static` | time_scale_ratio | time_scale_ratio | none |

The table is part of the registry digest. Changing it makes every pinned rule set stale instead of silently reinterpreting it. The kernel exposes no model form for diffusion-model selection, so that section 13.3 consideration has no entry and remains unsupported.

## Applicability rules

A rule set is closed and versioned (`rule_set_id`, `revision`) and has an authoring status of `draft` or `proposed`. `approved` is rejected, because no identity-backed approval exists. The rule set pins the registry version and digest. Every rule has these fields:

- `rule_id` and `rule_version`
- the candidate `model_form` it gates
- the group form it uses, which must be admissible for that model form
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
| Model-form alternatives | `model_form_alternatives` (required when `criticality` is `critical`; a candidate form may not also be listed as `rejected`) |

The intent also carries `assumptions` and a `rule_set_pin`. All references must resolve. The pin must match the supplied rule set's id, revision and digest exactly. A scale may not cite a retired assumption, because a retired assumption cannot support a live input. An unreferenced retired assumption can still be recorded. No text anywhere in an intent or rule set may contain an unpaired surrogate.

## Evaluation and gates

Rules for a model form that is not a candidate are reported as `not_selected`. Every selected rule is evaluated against every declaration of its group form. If there is no such declaration, the rule is `indeterminate` with reason `group_not_declared`.

Each candidate model form gets one outcome. The outcome lists its `required_groups`, its `missing_required_groups` and its `unevaluated_considerations`. Its state is the first of these that applies:

1. `violated`: any rule for the form is violated.
2. `no_rule`: the set has no rule for the form.
3. `indeterminate`: a rule is indeterminate, or a required group has no rule.
4. `marginal`: any rule is marginal.
5. `considerations_unevaluated`: every rule passes, but the table lists considerations this kernel cannot evaluate.
6. `applicable`: none of the above.

The overall `applicability_state` is the worst state found. From worst to best: `rules_violated`, `indeterminate` (which includes `no_rule`), `marginal_review_required`, `considerations_review_required`, `rules_satisfied`.

Only a candidate form that covers every required group, has no unevaluated considerations and passes every rule can contribute to `rules_satisfied`. Even then, the result means only rule applicability.

Every marginal outcome creates a warning and an open review task, numbered deterministically as `RVW-<n>`.

**Input support.** Every scale bound in a group declaration feeds a computed group, so its cited support is inspected. The scale qualifies if it cites at least one non-synthetic evidence record, or at least one `accepted` assumption. Otherwise it raises `INPUT_SUPPORT_NOT_QUALIFYING`, with a warning that names its actual support:

- synthetic illustration evidence only;
- open assumptions only;
- or a mixture of the two.

The scale's declared `basis`, for example `measured`, does not change this check. Any bound scale that cites synthetic evidence also produces a `SYNTHETIC_INPUT_EVIDENCE` warning. Scales that are not bound to a group, such as environment conditions, are recorded but not gated.

`qualified_execution.permitted` is always false. Its blockers are:

- violated or indeterminate rules
- pending marginal reviews
- candidate forms without a rule (`MODEL_FORM_WITHOUT_RULE`)
- required groups without a rule (`REQUIRED_GROUP_NOT_COVERED`)
- unevaluated considerations (`CONSIDERATION_NOT_EVALUATED`)
- synthetic rule citations
- bound inputs without qualifying support
- open critical assumptions
- `ai_proposed` inputs
- exploratory acceptance
- a requested mode other than `qualified`
- always: `RULE_SET_NOT_APPROVED`, `NO_IDENTITY_BACKED_APPROVAL` and `NO_QUALIFIED_SOLVER_CAPSULE`

`controlled_review_readiness` is `ready_for_independent_review` only if none of the following is present:

- a violated or indeterminate rule
- a candidate form without a rule
- a missing required group
- an unevaluated consideration
- a synthetic rule citation
- a bound input without qualifying support
- an AI-proposed input
- an open critical assumption
- exploratory acceptance

It is never an approval. Marginal outcomes create review tasks but do not block controlled readiness, because the independent review handles them.

Exploration mode labels the output `exploratory` and keeps every violation visible. `authority_promotion_permitted` is always false.

## Digests and verification

- The intent digest and the rule-set digest are SHA-256 hashes of the canonical documents.
- The report binds both digests and the registry digest, and also carries `report_digest` over its own canonical body.
- Verification has three steps:
  1. Check the self-digest.
  2. Check the input binding.
  3. Recompute the whole evaluation from the inputs and compare canonical bytes.
- The following are rejected:
  - an edited report, which breaks its digest;
  - an edited and re-hashed report, which fails recomputation;
  - an edited retained input, which breaks the binding to the report;
  - a retained file that is not in canonical form.

**Trust limitation: bundles are unsigned.** Verification proves that a bundle is internally consistent and reproducible from its own retained inputs. It does not prove who produced the bundle or that the bundle is the one that was originally produced. Suppose someone rewrites a retained input and then regenerates the whole bundle consistently, with a new report and a new `report_digest`. That bundle verifies.

To detect such a replacement, record `report_digest`, or the intent and rule-set digests, somewhere outside the bundle when it is first produced. `evaluate` and `verify` both print `report_digest`. Then compare the recorded value with what `verify` prints.

Signatures, trusted time and identity-backed approval are outside this kernel (A01-U03).

## Not implemented

The following are not implemented:

- solver plans, adapters, capsules, meshing, execution, V&V/UQ and result models (§13.4–13.13);
- automatic selection of rules or model forms;
- evaluation of the considerations listed in the model-form table, which are only flagged for independent review: turbulence wall treatment, separation and target-quantity sensitivity; beam local-stress needs; shell through-thickness effects; strain, material behaviour, contact and geometric change for linear elasticity;
- any model form for diffusion regimes;
- checks that a load magnitude's kind matches the load kind;
- material lookup;
- embedding `physics_intents` in a CIR document;
- identity, signatures, approvals and audit events;
- uncertainty propagation.

Domains are recorded for the reviewer but are never reported as available for execution.
