# Reference spatial assemblies

`contrainte.reference-spatial-assembly/0.1` checks released local component
geometry around one protected reference component. It joins three existing
public contracts without promoting any of them:

- `contrainte.interface-assembly/0.2` and its solved
  `contrainte.interface-assembly-result/0.2` provide exact occurrence poses;
- a sealed reference component, design-around request, and independently
  reproducible projection provide evidence-backed occupied, keepout, access,
  and service boxes; and
- `contrainte.component-manifest/0.3` releases provide the surrounding local
  B-reps.

The compiler performs nominal Open CASCADE interference and clearance checks.
Its only output is a JSON evidence bundle. It does not reconstruct or publish a
B-rep for the protected reference, publish geometry artifacts, or qualify the
assembly for release.

## Input schema

The top-level document contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Exactly `contrainte.reference-spatial-assembly/0.1`. |
| `assembly_id` | Stable, bounded ASCII identifier used in the output filename. |
| `revision` | Bounded revision text. |
| `title` | Bounded descriptive text. |
| `interface_assembly` | Digest-bound source reference for an interface assembly. |
| `interface_result` | Digest-bound source reference for its solved result. |
| `protected_reference` | Binding for the one protected occurrence and its three source documents. |
| `released_components` | Sorted, unique bindings for one to 63 released occurrences. |
| `minimum_occupied_clearance_mm` | Non-negative exact rational clearance from every released component to the protected occupied box. |
| `default_released_clearance_mm` | Non-negative exact rational default for each released/released pair. |
| `released_pair_clearances` | Sorted, unique overrides for named released/released pairs. |

Every exact rational is a reduced, canonical, non-negative string such as `0`,
`5`, or `1/4`; JSON floating-point numbers are not accepted.

A source reference contains exactly:

```json
{
  "locator": "relative/path.json",
  "file_digest": "sha256:..."
}
```

Locators are bounded relative POSIX paths under the explicit source root. A
source reference binds the exact file bytes consumed by the compiler, not merely
the semantic object parsed from those bytes.

The protected binding contains exactly:

```json
{
  "occurrence_id": "protected-motor",
  "reference_component": {
    "locator": "artifacts/reference-motor.json",
    "file_digest": "sha256:..."
  },
  "reference_component_digest": "sha256:...",
  "design_around_request": {
    "locator": "artifacts/reference-motor.request.json",
    "file_digest": "sha256:..."
  },
  "design_around_request_digest": "sha256:...",
  "design_around_projection": {
    "locator": "artifacts/reference-motor.projection.json",
    "file_digest": "sha256:..."
  },
  "design_around_projection_digest": "sha256:..."
}
```

Each of the three files is therefore bound twice: by its exact byte digest and
by its canonical content digest. The occurrence ID must identify the only
`protected_reference` participant in the version 0.2 interface assembly. The
sealed component, request, and projection must exactly equal the documents
embedded in that participant, and the projection must independently replay.

Each released binding contains exactly:

```json
{
  "occurrence_id": "left-bracket",
  "manifest_locator": "artifacts/left.component.json",
  "manifest_file_digest": "sha256:...",
  "manifest_digest": "sha256:..."
}
```

The manifest must be a fully verified `contrainte.component-manifest/0.3`
release, and it must exactly equal the released component embedded in the
corresponding interface participant. The sorted released binding set must cover
every released interface occurrence exactly once. A pair-specific clearance has
exactly `first_occurrence_id`, `second_occurrence_id`, and
`minimum_clearance_mm`; its occurrence IDs must be in increasing order and must
name released bindings.

The interface result must be `solved`, must bind the exact version 0.2 interface
assembly, and must pass the independent interface-result verifier. There must be
exactly one protected occurrence and one to 63 released occurrences. Other
participant mixtures and version 0.1 interface documents are rejected rather
than assigned new semantics.

## Bounded stable inputs

The assembly document, interface document, result, protected component, request,
and projection are each limited to four MiB. General JSON depth, node, string,
integer, identifier, collection, and exact-scalar limits are also enforced.

Inputs are read as bounded stable byte snapshots. Direct-file identity, type,
size, modification time, link count, and open-handle/path continuity are checked
around each read. Symbolic links, Windows reparse points, hard-linked files,
absolute paths, parent traversal, and path replacement are rejected. Declared
file digests are calculated from the bytes actually consumed.

The CLI retains the actual assembly-input file and every directory in its path
through compilation. The input is opened without link following; Windows handles
deny delete sharing, while POSIX uses retained directory/file descriptors and
`O_NOFOLLOW`. Its visible name and identity are rechecked before staging, before
promotion, and before commit. The output cannot be the same path, lexical alias,
or pre-existing hardlink as that retained input, and publication cannot overwrite
any consumed source locator.

Released manifests use the same handle-bound source tree and the complete local
release snapshot machinery. The compiler verifies manifest and source-bundle
digests, local release lifecycle restrictions, every release artifact, and the
reproduced bounds before accepting a B-rep. It does not verify one file and later
use an unbound reread of that path.

The protected spatial model is also strictly bounded. It contains the occupied
box plus every declared envelope, with at most 32 regions in total. With 63
released components, at most 1,953 released/released pairs and 2,016
released/protected-region combinations are evaluated.

Protected box coordinates and all governing clearances are limited to
`1000000000 mm`; every protected box edge must be at least `0.000001 mm` so the
nominal Open CASCADE proxy is within the declared kernel scale. The synthetic
region ID `occupied-bounds` is reserved and cannot also be an envelope ID.

## Geometry and authority

The two geometry paths have intentionally different authority.

For a released component, the compiler reproduces the verified local B-rep from
its release engineering bundle and applies the exact occurrence pose from the
solved interface result. Bundle evidence labels this authority
`verified_local_release_brep`.

For the protected reference, the compiler uses only the exact component-local
`occupied_bounds` and declared `keepout`, `access`, and `service` envelopes. Each
`ExactBox` becomes a temporary Open CASCADE box proxy, then receives the protected
occurrence pose. The result may be oriented in world space even though the source
box is axis-aligned in component-local space.

These proxy solids exist solely to perform conservative nominal intersection and
distance measurements. Their bundle records retain:

- the region ID, purpose, and source path;
- exact component-local bounds and exact world transform;
- the governing clearance;
- evidence ID, kind, authority, and artifact digest;
- `geometry_authority: conservative_box_proxy_only`; and
- `protected_brep_claimed: false`.

The compiler does not infer a protected surface, volume, topology, material, or
shape from a drawing, scan, supplier model, measurement, or Gaussian splat.
Evidence authority remains the ceiling declared by the sealed reference
component; passing a geometric check does not upgrade it.

The occupied box uses `minimum_occupied_clearance_mm`. Each named envelope uses
the clearance declared for it by the sealed design-around request, or zero when
the request declares no additional clearance. Released/released pairs use their
specific override when present and otherwise use
`default_released_clearance_mm`.

## Exact placement and nominal OCCT checks

The solved transforms retain exact rational, proper, right-handed basis and
translation values as semantic authority. Compiler and verifier project the
basis directly into an Open CASCADE `gp_Trsf`; they do not recover Euler angles.
The twelve matrix coefficients are read back as exact fractions of their binary
floating-point values. A maximum coefficient error above
`0.000000000001` is rejected.

Every unordered released/released pair and every released/protected-region pair
records:

- minimum Open CASCADE distance in millimetres;
- the required exact rational clearance;
- boolean-common volume in cubic millimetres; and
- `passed`, `interference`, or `clearance_violation`.

Common volume above `0.000001 mm3` is interference. Otherwise, measured distance
plus `0.000001 mm` must be at least the required clearance. Kernel measurements
are converted directly from binary floats to exact fractions for the decision;
the decimal report strings are display values only. These thresholds absorb
nominal kernel noise. They are not manufacturing tolerances, fit allowances, or
physical uncertainty bounds.

Any failed comparison stops compilation before bundle publication.

Bundle publication does not preflight a path and then reopen it for an in-place
write. It retains the complete output-directory chain, creates a unique
same-directory file with no-follow/exclusive-create semantics, verifies link
count before writing, flushes and rereads the exact canonical bytes through the
same handle, and promotes that retained identity by same-directory rename. A
pre-existing direct bundle is first retained and moved to a private backup name;
staging, promotion, verification, dependency, or cleanup failure restores its
exact bytes at the original visible name. Pre-existing hardlinks are rejected
before any staged bytes are written.

This containment boundary does not claim protection against an actor with the
same filesystem identity deliberately creating a new hardlink during the small
interval after the last link-count check while a write is in progress. Such an
actor already holds equivalent local write authority. The compiler detects link
count changes at subsequent verification where the platform exposes them, but it
does not label this as a stronger cross-principal sandbox guarantee.

## JSON evidence bundle

Successful compilation writes one file:

```text
<assembly-id>.reference-spatial-assembly-bundle.json
```

Its content schema is
`contrainte.reference-spatial-assembly-bundle/0.1`. The envelope carries a
canonical digest of the complete content. That content records the embedded input
assembly, all semantic digests and source records, exact placement evidence,
protected-region evidence, every nominal pair result, kernel identity, checks,
authority summary, and evidence blockers.

The following values are fixed and independently enforced:

```json
{
  "qualification": "unqualified_demonstration",
  "release_eligible": false,
  "artifacts": []
}
```

The authority summary states that protected geometry consists only of
conservative explicit boxes, that no protected B-rep is claimed, that released
geometry comes from verified local release B-reps, that spatial results are
conditional constraint evidence, and that release authority is `none`.

Blockers always include:

- `protected-reference:no-brep-authority`;
- `release:human-engineering-review-required`; and
- `spatial-model:conservative-primitives-only`.

Every blocker retained by the independently verified design-around projection is
also carried forward. Passing all nominal spatial checks never removes these
blockers and never creates STEP, STL, a component release, an engineering
release, or manufacturing authority.

## Independent replay

Bundle verification stable-reads the JSON bundle, checks its canonical digest and
exact field set, rejects qualification or release promotion, and requires
`artifacts` to remain empty. It then reopens every digest-bound source beneath the
explicit source root.

The verifier independently replays the version 0.2 interface result and the
design-around projection, re-verifies every released local release, rebuilds its
B-rep, reconstructs every protected box proxy, and repeats all spatial checks.
Its transform projection, placement construction, kernel measurement, status
classification, region loop, and released-pair loop are separate from the
compiler implementations. Rehashed changes to source records, authority,
transforms, regions, clearances, measurements, checks, blockers, or kernel
identity therefore do not verify.

## CLI

Build the deterministic existing-motor source tree, replay its interface result,
and compile the fully digest-bound spatial assembly:

```powershell
python examples/build-reference-spatial-motor.py --output-dir artifacts/reference-spatial-motor
python -m contrainte interface-assembly solve artifacts/reference-spatial-motor/existing-motor.interface.json --output artifacts/reference-spatial-motor/existing-motor.interface-result.json
python -m contrainte interface-assembly verify artifacts/reference-spatial-motor/existing-motor.interface.json artifacts/reference-spatial-motor/existing-motor.interface-result.json
python -m contrainte reference-spatial-assembly compile artifacts/reference-spatial-motor/existing-motor-spatial-assembly.json --source-root artifacts/reference-spatial-motor --output-dir artifacts/reference-spatial-motor/compiled
```

Independently replay the JSON evidence bundle against the same source tree:

```powershell
python -m contrainte reference-spatial-assembly verify artifacts/reference-spatial-motor/compiled/existing-motor-bracket.reference-spatial-assembly-bundle.json --source-root artifacts/reference-spatial-motor
```

The compile command prints the bundle digest. The verify command returns
`status: verified`, the bundle and assembly digests, and
`release_eligible: false` when independent replay succeeds.

## Deliberate nonclaims

Version 0.1 establishes only a nominal static spatial condition for exact
released component definitions against evidence-backed conservative boxes at one
solved pose. It does not establish:

- a B-rep, mesh, surface, persistent topology, or exact physical boundary for the
  protected reference;
- that a drawing, supplier model, scan, Gaussian splat, measurement, or declared
  box is authentic, complete, accurate, current, or legally usable;
- manufacturing tolerance stacks, fit, backlash, preload, deformation, motion
  sweeps, vibration, fatigue, impact, wear, or failure modes;
- actual tool, hand, cable, connector, hose, fluid, installation, removal,
  operating, or service access beyond the declared conservative boxes;
- structural, thermal, fluid, electromagnetic, electronics, controls, safety,
  contamination, cleaning, reliability, or regulatory performance; or
- fitness for manufacture, intended use, human safety, qualification, or release.

Those claims require their own evidence, models, simulations, inspections,
reviews, and qualification gates. This bundle preserves the spatial evidence
boundary so later stages can add those gates without mistaking a conservative
proxy check for a released design.
