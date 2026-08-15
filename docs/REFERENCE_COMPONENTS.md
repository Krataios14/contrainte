# Protected reference components and design-around projections

A reference component is an existing motor, gearbox, pump, robot, instrument,
enclosure, PCB, legacy part, or other object that a design must preserve. Contrainte
treats it as a digest-bound engineering input rather than editable generated
geometry.

The public kernel turns a bounded component record into protected constraints and
explicitly flexible design domains. This makes “design around this motor” concrete:
the motor identity, source model, occupied bounds, physical interfaces, service
envelopes, mass properties, known evidence, unknowns, allowed operations, and
project gate dispositions remain fixed while mounts, transmission, cooling,
electronics, harnesses, controls, guarding, or service tooling can be synthesized
around them.

AI may propose the surrounding design. It cannot alter the protected component or
promote weak evidence while doing so.

## Schemas

Version 0.1 defines three documents:

```text
contrainte.reference-component/0.1
contrainte.design-around-request/0.1
contrainte.design-around-projection/0.1
```

Reference components and requests are created as unsealed payloads. The sealing
functions parse every field, enforce cross-field invariants, and add a canonical
content digest. Projections bind both sealed digests.

Changing a component revision, evidence authority, bound, frame, operation, known
field, unknown field, or gate changes its digest. A stale in-memory object whose
fields no longer match its digest is rejected again at projection and verification
boundaries.

## Evidence model

Each evidence record includes:

- an evidence ID;
- a typed kind;
- an artifact SHA-256;
- an authority ceiling;
- a locator; and
- canonical RFC 6901 field paths that it supports.

Supported evidence kinds include manufacturer drawings and data sheets, supplier
models, calibrated metrology, test reports, declarations, scans, Gaussian splats,
and explicitly labelled other records.

Authority is separate from kind:

- `documented_source`;
- `verified_measurement`;
- `nominal_source`;
- `observation`; and
- `informative`.

Manufacturer drawings can support documented dimensions. Calibrated metrology can
support verified measurements. Supplier nominal models, scans, and Gaussian splats
cannot be relabelled as those authorities merely because they are convenient.

Evidence support is directional and segment-aware. Evidence for
`/occupied_bounds` may support a child coordinate. Evidence for only
`/occupied_bounds/minimum/x` cannot authorize the complete bounds object.

Field paths use canonical RFC 6901 escapes. Empty segments, trailing slashes,
filesystem-style dot navigation, invalid tilde escapes, and ancestor/descendant
known-versus-unknown contradictions are rejected.

## Geometry and frames

The component carries exact rational millimetre occupied bounds. Every minimum must
be strictly below its corresponding maximum.

Frames use Contrainte's exact proper rigid-transform schema. A frame is either:

- a physical `interface`, with typed kind, direction, medium, and properties; or
- a virtual `datum`, without interface semantics.

A physical interface origin must lie inside or on the occupied bounds. The kernel
does not claim that it lies on a B-rep face, hole axis, connector body, or persistent
topological entity. A virtual datum may lie outside the solid when the governing
drawing intentionally defines an external construction datum.

Reference operations require real referents:

- `attach_at_declared_interface` requires at least one physical interface frame;
- `route_within_declared_access` requires at least one access envelope; and
- `remove_for_service` requires at least one service envelope.

An enum value therefore cannot create a resolved permission with no corresponding
physical declaration.

## Spatial envelopes

An envelope has an exact box and one purpose:

- `keepout` protects occupied or hazard space;
- `access` preserves routing or operating access; and
- `service` preserves removal and maintenance space.

A design-around request may add exact non-negative clearance to a named envelope.
The projected clearance retains the envelope evidence ceiling. An observational
envelope cannot become an authoritative clearance constraint merely because a
request refers to it.

These are axis-aligned component-local boxes. Version 0.1 does not represent swept
volumes, oriented boxes, arbitrary boundary geometry, deformation, or tolerance
zones.

## Mass properties

Optional mass properties contain:

- positive exact mass in kilograms;
- an exact component-local centre of mass;
- a symmetric exact inertia tensor in `kg*mm2`;
- the fixed reference `center_of_mass`; and
- one supporting evidence record.

The centre of mass must lie in the occupied bounds. The inertia tensor must be
positive semidefinite. Contrainte also proves the exact positive-semidefinite
condition on `trace(I)/2 * identity - I`, which is equivalent to the principal
moment triangle inequalities, and enforces conservative upper bounds derived from
the mass, centre of mass, and occupied box.

These checks reject impossible records; they do not measure the part or establish
that the source evidence is authentic.

## Known and unknown fields

A known field names a canonical path and its evidence. Projection resolves the
actual protected value at that path and stores its digest, evidence IDs, and
authority ceiling.

Observation-, nominal-, or informative-grade known fields remain evidence blockers.
Calling an appearance value “known” cannot make it authoritative.

An unknown field records:

- its canonical path;
- the consequence of not knowing it; and
- the evidence required to resolve it.

Every unknown becomes an explicit projection blocker. Known and unknown paths may
not overlap as equals, ancestors, or descendants.

In the motor example, the missing torque-speed and derating map blocks transmission
and inverter release. Contrainte does not fabricate that map from a bounding box,
nameplate photograph, or Gaussian splat.

## Project evidence gates

Every reference component contains exactly one workflow gate for:

- authenticity;
- rights to use;
- rights to modify;
- freedom to operate; and
- export control.

Each disposition is `unreviewed`, `accepted_for_project`, `blocked`, or
`not_applicable`, with evidence and rationale. Unreviewed or blocked gates appear in
the projection blockers.

These are project workflow records only. They are not legal determinations, legal
advice, non-infringement opinions, export licences, or proof that a supplier record
is authentic. The fixed schema disclaimer is part of every sealed component and
projection and cannot be removed or altered.

## Design-around request

A request binds exactly one component digest and names:

- a request ID and occurrence ID;
- flexible design domains;
- required physical interface IDs; and
- envelope-clearance requirements.

Flexible domains include mounting, structure, transmission, power, electronics,
cooling, lubrication, harness, controls, shielding, guarding, and service tooling.
The list is permission to design surrounding work in those domains, not evidence
that any candidate is feasible.

Unknown interfaces or envelopes are rejected. Flexible domains and IDs are sorted,
unique, and bounded.

## Projection

The projector emits:

- protected constraints with source paths, value digests, evidence IDs, authority
  ceilings, and resolution flags;
- flexible-domain bindings to required interfaces;
- evidence, unknown, and project-gate blockers;
- the bound request and component digests; and
- a projection content digest.

Protected constraints cover identity, source model, occupied bounds, frames,
envelopes, mass properties, allowed operations, known fields, unknowns, evidence
gates, and requested clearances.

The verifier reparses the component, request, and projection. It reconstructs the
projection through a separate semantic oracle with its own evidence-ceiling,
RFC 6901 pointer, and identity-support implementations. The verifier deliberately
does not call the projector's corresponding helpers; regression tests inject faults
into those helpers and require verification to reject the resulting projection.

## CLI example

Seal the synthetic motor and its digest-bound design-around request:

```powershell
python -m contrainte reference-component seal examples/reference-motor-payload.json --output artifacts/reference-motor.json
python -m contrainte reference-component seal-request examples/reference-motor-design-around-payload.json --output artifacts/reference-motor.request.json
```

Project and independently replay the protected constraints:

```powershell
python -m contrainte reference-component project artifacts/reference-motor.json artifacts/reference-motor.request.json --output artifacts/reference-motor.projection.json
python -m contrainte reference-component verify artifacts/reference-motor.json artifacts/reference-motor.request.json artifacts/reference-motor.projection.json
```

The example intentionally produces evidence blockers. It uses placeholder digests,
synthetic review records, and an informative mass test. It is a deterministic schema
fixture, not supplier evidence or a released motor record.

## Python API

```python
from contrainte import (
    DesignAroundRequest,
    ReferenceComponentManifest,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
    verify_design_around_projection,
)

component_document = seal_reference_component(component_payload)
component = ReferenceComponentManifest.from_dict(component_document)

request_document = seal_design_around_request(request_payload)
request = DesignAroundRequest.from_dict(request_document)

projection = project_design_around(component, request)
assert verify_design_around_projection(component, request, projection)
```

Public boundaries reject subclass spoofing, mutable nested collections, stale
digests, non-canonical rationals, hostile keys, excessive depth/nodes/collections,
oversized integers, and invalid state combinations.

## What this proves

A verified projection proves that:

- the exact sealed component and request digests are bound;
- protected values reproduce from the sealed component;
- evidence authority ceilings and resolution flags follow schema rules;
- unknowns and unresolved project gates remain visible;
- requested interfaces and envelope clearances refer to declared entities;
- flexible domains are explicit; and
- the projection reproduces through the independent oracle.

## What this does not prove

Version 0.1 does not:

- read or authenticate evidence artifact bytes;
- prove authorship, supplier identity, legal rights, or freedom to operate;
- reconstruct a B-rep from drawings, scans, or splats;
- verify the source model against a physical component;
- locate frames on persistent topology;
- perform collision, clearance, tolerance, motion, access, or service simulation;
- evaluate a motor map, material, stiffness, thermal behavior, loss, fatigue,
  reliability, EMC, control, safety, contamination, or cleaning behavior;
- choose or optimize a surrounding design; or
- qualify a component or system for an intended use.

The next workflow stage may translate proven physical interfaces into exact
interface-assembly constraints. It must preserve the component and evidence digests,
then run exact geometry and every applicable physics, manufacturing, inspection,
safety, and qualification gate.
