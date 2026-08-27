# Topology-backed component interfaces

The `contrainte.component-release-request/0.3` contract binds an exact interface
frame to one authored feature in a verified prismatic CAD bundle. A successful
derivation emits `contrainte.component-manifest/0.4` with reproduced kernel-face
evidence. This closes the narrower authority gap left by manifest 0.3, whose
frames are proven only to lie within the component's reproduced axis-aligned
bounds.

This first version is deliberately not a general persistent-topology system. It
supports only the six stock faces and cylindrical walls of named through-holes
from `contrainte.prismatic-part/0.1`.

## Version boundary

The schema meanings are separate:

- release request 0.1 derives manifest 0.2 with geometry bounds and unframed
  interfaces;
- release request 0.2 derives manifest 0.3 with exact frames and bounds-only
  frame containment; and
- release request 0.3 derives manifest 0.4 with exact frames, authored semantic
  selectors, and compiler-produced attachment evidence.

Older requests and manifests reject the `attachment` field. A 0.3 request must
provide a frame and selector for every interface and must not provide its own
derived evidence. A 0.4 manifest requires the complete evidence object for every
interface.

## Selectors

An interface attachment contains a strict selector:

```json
{
  "attachment": {
    "selector": {
      "kind": "prismatic_stock_face",
      "feature_id": "stock",
      "role": "positive_z"
    }
  }
}
```

`prismatic_stock_face` requires `feature_id` to be `stock`. Its role is one of
`negative_x`, `positive_x`, `negative_y`, `positive_y`, `negative_z`, or
`positive_z`. The frame origin must lie strictly inside that exact authored face,
not on a stock edge and not in or on a through-hole opening. The frame `z_axis`
must equal the outward face normal.

A named through-hole uses:

```json
{
  "attachment": {
    "selector": {
      "kind": "prismatic_through_hole",
      "feature_id": "mount-nw",
      "role": "cylindrical_wall"
    }
  }
}
```

The identifier must resolve to exactly one authored `hole_id`. The frame origin
must satisfy the exact cylinder equation at a Z coordinate strictly between the
two openings. Its `z_axis` must be the canonical positive-Z through-hole axis.
The point is therefore on the cylindrical wall while the frame direction follows
the authored hole axis; the direction is not a claim about the radial surface
normal.

All coordinates, radii, and semantic incidence decisions are made from the exact
decimal feature definition. Open CASCADE is an additional reproduced-geometry
check, not the source of the feature identity.

## Derived evidence

The compiler adds an `evidence` object beside the selector:

```json
{
  "source_feature_digest": "sha256:...",
  "matched_face_count": 1,
  "surface_type": "cylinder",
  "origin_on_surface": true,
  "orientation_matches": true,
  "characteristic_point_mm": {"x": "-35", "y": "20", "z": "5"},
  "direction": {"x": "0", "y": "0", "z": "1"},
  "radius_mm": "5"
}
```

Plane evidence omits `radius_mm`. The parser fixes `matched_face_count` to one and
both decision booleans to true. It requires the characteristic point to equal the
interface-frame origin and the evidence direction to equal its `z_axis`.

The source-feature digest covers the normalized authored stock or hole feature.
The compiler independently rebuilds the verified source B-rep, matches surface
type and geometric invariants without relying on face-list order, and requires
the exact frame point to lie on the one matching face. A zero-match or ambiguous
match fails closed.

## Verification replay

Local component verification re-verifies the source bundle and every artifact,
rebuilds the prismatic B-rep, and replays the selector through a verifier path
separate from the derivation matchers. It recomputes feature identity, exact
incidence, frame orientation, kernel face cardinality, surface type, point,
direction, and radius. Changed selectors, frames, source features, or plausible
rehashed evidence do not verify.

The manifest also retains the release-request content digest and the source
bundle's byte and canonical content digests. As in older local component
manifests, these are integrity bindings rather than signatures or authorship
proofs.

## CLI example

Compile the prismatic source, derive the topology-backed component beside it, and
replay the complete local chain:

```powershell
python -m contrainte cad compile examples/mounting-plate.json --output-dir artifacts/mounting-plate-topology
python -m contrainte component derive artifacts/mounting-plate-topology/plate.demo.cad-bundle.json examples/mounting-plate-topology-component.json --output artifacts/mounting-plate-topology/component.mounting-plate.topology-demo.json
python -m contrainte component verify artifacts/mounting-plate-topology/component.mounting-plate.topology-demo.json
```

The synthetic example proves one positive-Z stock-face attachment and one named
through-hole cylindrical-wall attachment.

## Deliberate limits and nonclaims

Version 0.1 does not provide:

- persistent naming for arbitrary imported, boolean, sketch, solid-program, or
  assembly topology;
- edge, vertex, circular-opening, datum-axis, pattern-instance, or user-authored
  surface-region selectors;
- topology recovery after a feature is deleted, split, merged, reordered, or
  changed to a different geometric class;
- tolerance-conditioned incidence, fit, contact, fastener, joint, preload,
  deformation, motion, wear, or assembly-sequence evidence;
- STEP AP242 semantic PMI, GD&T, controlled drawings, or manufacturing release;
  or
- authorship, supplier authenticity, legal rights, qualification, or fitness for
  an intended use.

Manifest 0.4 is not yet admitted by the existing interface-assembly,
component-assembly, or protected-reference spatial contracts. Those consumers
remain pinned to manifest 0.3 until their own versioned schemas explicitly carry
and preserve topology-attachment authority.
