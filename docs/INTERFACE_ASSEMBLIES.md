# Exact interface assemblies

Contrainte's interface-assembly kernel places released components and explicitly
protected reference occurrences by solving equations between exact semantic
interface frames. It is the first public
design-around primitive: a component can remain fixed while Contrainte searches
explicitly permitted mating poses for the surrounding components.

The kernel is evidence-first. It never asks an LLM, a floating-point optimizer, or
a renderer whether two frames coincide. It parses a bounded graph, evaluates
ranked alternatives with rational rigid-transform algebra, and returns a result
that a separate replay path can reconstruct.

This is not the same system as the exact-geometry assembly compiler documented in
[ASSEMBLIES.md](ASSEMBLIES.md). The geometry compiler checks B-rep interference
and clearance for already placed parts. The interface solver determines semantic
placements. A complete design-around workflow must run both, followed by the
applicable tolerance, load, thermal, manufacturing, access, and qualification
gates.

## Document versions

The input schema is:

```text
contrainte.interface-assembly/0.1
```

The result schema is:

```text
contrainte.interface-assembly-result/0.1
```

Version 0.1 accepts only embedded `contrainte.component-manifest/0.3` component
documents. That component version is required because every interface has an
exact frame. An older or future component schema is rejected rather than silently
assigned version 0.1 semantics.

The hybrid design-around schemas are:

```text
contrainte.interface-assembly/0.2
contrainte.interface-assembly-result/0.2
```

Version 0.2 replaces each occurrence's untagged `component` field with one tagged
`participant`. A `released_component` retains the complete version 0.3 component
manifest. A `protected_reference` retains a sealed
`contrainte.reference-component/0.1`, its sealed design-around request, and its
independently reproducible projection. The solver normalizes both variants to the
same bounded interface-only placement view. It does not translate the protected
reference into a component manifest, artifact set, geometry bound, or B-rep.

Every version 0.2 result contains `assembly_digest`, the canonical SHA-256 digest
of the complete version 0.2 input. It also contains one canonical
`participant_evidence` record per occurrence: subject/request/projection digests,
protected-constraint and unresolved-constraint counts, authority counts, the
evidence retained for each exposed interface, and the projection's blockers.
`release_eligible` is always `false`: these fields bind and summarize placement
evidence; they do not promote it to a component or engineering release. The same
summary is emitted by the version 0.2 solve and verify CLI paths. Version 0.1
serialization, result semantics, and CLI output remain unchanged and do not gain
these fields.

## Input contract

An input contains:

- a non-empty, uniquely identified, canonically sorted set of occurrences;
- exactly one occurrence with an anchor transform;
- a canonically sorted set of interface mates;
- one or more ranked alternatives for each mate; and
- an explicit candidate budget.

In version 0.1, each occurrence embeds its complete component manifest. In version
0.2, each occurrence embeds one complete tagged participant. This makes search
semantics independent of a mutable catalogue lookup. Every document is reparsed
into an immutable canonical snapshot before solving.

A protected-reference participant must satisfy all of the following before it can
enter search:

- the reference component, request, and projection content digests reproduce;
- the request binds the exact reference-component digest;
- the sealed reference explicitly allows `attach_at_declared_interface` before
  any requested physical interface can be exposed to a mate;
- the projection independently replays against that component and request;
- the outer occurrence ID equals the request and projection occurrence IDs; and
- only physical interface frames explicitly named by
  `required_interface_ids` are exposed to mates.

The normalized protected interfaces retain their exact frame, kind, direction,
medium, properties, source evidence authority, resolution flag, and projection
blockers. An unrequested physical frame and every datum remain invisible to the
mate resolver. Observational scan or Gaussian-splat authority therefore remains a
blocker even when the exact frame equations solve.

Each mate names a `first` and `second` endpoint. An endpoint is an occurrence ID
plus an interface ID. The two interfaces must have:

- the same interface kind;
- the same medium;
- compatible directions; and
- equal values for every property key explicitly selected by the mate.

Input/output is compatible in either order. A bidirectional interface is
compatible with either direction. Two input-only or two output-only interfaces
are not compatible.

Properties not listed in `property_keys` are not checked. This is intentional and
visible. A caller must not interpret an omitted property as matched.

An interface endpoint may occur in only one mate. A component that provides two
physical connection sites must declare two interface IDs. This avoids silently
using one physical connector, shaft, port, or datum more than once.

The mate graph must be connected to the one anchor. A disconnected subassembly
has no determined world pose and is rejected during parsing.

## Exact pose equation

All transforms use the conventions in [EXACT_TRANSFORMS.md](EXACT_TRANSFORMS.md):
column-vector bases, local-to-parent maps, millimetres, and exact reduced rational
coordinates.

For one mate, define:

- `W_first`: first component to world;
- `F_first`: first interface to first component;
- `A`: second interface to first interface, supplied by the selected alternative;
- `W_second`: second component to world; and
- `F_second`: second interface to second component.

The accepted equation is:

```text
W_first * F_first * A = W_second * F_second
```

Search can propagate this equation from either endpoint. Cycle closure evaluates
the same exact relation after all occurrences have poses. There is no binary
floating-point coincidence tolerance.

Only proper rational rotations are representable. An interface basis must be
exactly orthonormal with determinant `+1`. Reflections, approximate rotation
matrices, and irrational rotations without an explicit rational representation
are outside this schema.

## Ranked bounded search

Occurrences and mates are sorted by ID. Alternatives within a mate are sorted by:

```text
(preference_rank, alternative_id)
```

The solver enumerates the Cartesian product in lexicographic order and returns
the first feasible candidate. The result records its one-based examined-candidate
ordinal and the selected alternative for every mate.

Search is deliberately bounded:

- at most 128 occurrences;
- at most 256 mates;
- at most 64 alternatives per mate;
- at most 4,096 alternatives across the graph;
- at most 256 examined candidates; and
- at most 2,048 exact mate evaluations per search or replay pass.

Additional caps bound embedded manifests, interfaces, artifacts, capabilities,
properties, identifiers, JSON depth, JSON node count, and exact scalar size.
These caps are checked for parsed documents and direct Python objects before
large materialization or deep traversal.

The exact-mate limit applies to each search or verification pass. A call that
solves and then independently verifies its answer can perform both bounded
passes. It is not a wall-clock deadline or a whole-process quota.

## Result states

A result has one of three statuses.

`solved` means the recorded transforms satisfy the selected equations and the
selected combination is the first feasible candidate within the declared
ordering and resource bounds.

`unsatisfiable` means every candidate in the complete finite alternative product
was examined and contradicted an exact equation. It does not mean that no
physical design exists outside the submitted alternatives.

`inconclusive` means the solver did not establish either outcome. The reason is
one of:

- `candidate_budget_exhausted`;
- `work_budget_exhausted`; or
- `exact_scalar_limit`.

Resource exhaustion is never reported as unsatisfiable. In particular, if an
earlier candidate exceeds the exact scalar representation cap, the solver does
not skip it and call a later candidate optimal.

The parser rejects impossible state/count combinations such as an unsatisfiable
result with zero examined candidates or a candidate-budget result that did not
consume the declared candidate budget.

## Independent replay

`verify_interface_assembly_result` handles all three terminal states.

For a solved result it:

1. reparses immutable snapshots of the assembly and result;
2. confirms the anchor and complete occurrence/mate ID sets;
3. independently enumerates every preceding candidate;
4. uses a separate raw-Fraction graph oracle to establish the first feasible
   ordinal and submitted world frames;
5. checks selected IDs and preference ranks; and
6. checks every selected mate through the direct homogeneous-frame equation.

The independent graph oracle does not call the solver's propagation routine. It
therefore catches a class of shared search-order and propagation errors rather
than merely rerunning the same code path.

For unsatisfiable or inconclusive results, verification independently replays the
candidate, work, and scalar boundaries and checks the exact terminal count and
reason.

The result document does not embed the input document or its digest in version
0.1. Verification therefore requires both the original input and result files.
An application that stores them separately must bind both in its own
content-addressed envelope. Version 0.2 closes that identity gap with its required
`assembly_digest`; verification rejects a result paired with any other canonical
input while still requiring the input itself for independent replay.

## CLI

Solve an assembly:

```powershell
python -m contrainte interface-assembly solve interface-assembly.json --output interface-result.json
```

The checked-in hybrid example locks a protected existing motor and places one
released-component participant at its explicitly requested mount:

```powershell
python -m contrainte interface-assembly solve examples/mixed-reference-motor-interface.json --output artifacts/mixed-reference-motor.result.json
python -m contrainte interface-assembly verify examples/mixed-reference-motor-interface.json artifacts/mixed-reference-motor.result.json
```

This example verifies semantic placement and evidence binding only. It does not
run reference-envelope or B-rep spatial checks.

Replay the result against the original input:

```powershell
python -m contrainte interface-assembly verify interface-assembly.json interface-result.json
```

The solve command prints the status and examined-candidate count. The verify
command prints `{"status": "verified"}` only after complete reconstruction.
Malformed documents and unreproducible results exit with code 2.

## Python API

The stable public entry points are:

```python
from contrainte import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    solve_interface_assembly,
    verify_interface_assembly_result,
)

assembly = InterfaceAssembly.from_dict(input_document)
result = solve_interface_assembly(assembly)
assert verify_interface_assembly_result(assembly, result)

stored_result = InterfaceAssemblyResult.from_dict(result_document)
assert verify_interface_assembly_result(assembly, stored_result)
```

Directly constructed objects do not bypass schema invariants. Public solve and
verify boundaries validate concrete types, canonical ordering, immutable nested
maps, collection caps, exact frame values, and schema versions before use.

## What this proves

Within the submitted finite alternative set and resource bounds, a verified
solved result proves:

- exact semantic interface compatibility for selected fields;
- exact satisfaction of every mate pose equation;
- exact graph-cycle closure;
- preservation of the declared anchor pose;
- deterministic first-feasible selection; and
- reconstruction of the recorded terminal evidence.

## What this does not prove

The interface solver does not currently:

- verify the local artifact bytes referenced by embedded component manifests;
- establish component-manifest authorship or authenticity;
- establish legal permission, freedom to operate, or non-infringement;
- prove that an interface frame lies on persistent B-rep topology;
- build or inspect STEP geometry;
- detect collision, insufficient clearance, or motion-sweep interference;
- solve tolerances, fits, backlash, preload, fasteners, seals, cable bend radius,
  connector keying, or assembly sequence;
- simulate structural, thermal, fluid, electromagnetic, control, contamination,
  cleaning, manufacturing, reliability, or service conditions;
- infer an unspecified mating transform;
- search continuous geometry or topology; or
- qualify a component or assembly for an intended use.

Embedded component manifests may contain released-looking lifecycle text, but
the interface solver only validates their schema and semantic frame data. A
production caller must first verify each manifest and its local source artifacts
through the appropriate release boundary, then retain that evidence binding.

A design-around workflow should treat an existing component as a protected,
content-addressed occurrence, enumerate only permitted interface alternatives,
solve this semantic graph, compile the surrounding exact geometry, and run every
applicable downstream evidence gate. AI may propose alternatives; it cannot
promote a candidate to verified status.

Version 0.2 makes the protected occurrence native to the semantic graph, but it
does not yet perform conservative occupied, keepout, access, or service-envelope
checks. That remains the next separate spatial-evidence gate. It also does not
interpret electrical property strings as voltage, current, pin, protection, or
circuit-simulation evidence.

`component-assembly/0.1` accepts only version 0.1 interface assemblies and exact
local component releases. A version 0.2 occurrence deliberately refuses that
legacy geometry handoff, including when its participant happens to be a released
component, so a mixed graph cannot silently bypass the future spatial-evidence
contract.

For locally derived `component-manifest/0.3` occurrences, the separate
[`component-assembly/0.1` contract](COMPONENT_ASSEMBLIES.md) performs that next
nominal-geometry gate. It replays the exact result, verifies and reconstructs each
local component release, projects the rational poses directly into Open CASCADE,
and rejects B-rep interference or insufficient clearance. It does not retroactively
add geometry authority to this semantic solver or to placeholder example digests.
