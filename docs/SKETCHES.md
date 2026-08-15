# Constrained sketch extrusions

The `contrainte.sketch-extrusion/0.1` contract turns a fully constrained, straight-line planar profile into a single Open CASCADE B-rep. It adds editable dimensional intent without making a language model, a mesh, or an opaque kernel result the authority for the sketch dimensions.

The contract deliberately separates two kinds of computation. Point coordinates, polygon areas, and expected extrusion volume are solved with exact rational arithmetic. build123d and Open CASCADE construct and measure the B-rep; their floating-point volume must agree with the independently calculated volume within a relative error of `0.00000001`.

## Input document

A sketch extrusion contains exactly these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | Must be `contrainte.sketch-extrusion/0.1`. |
| `part_id` | Stable, filesystem-safe part identity. |
| `revision` | Source revision label. |
| `title` | Human-readable description. |
| `material` | Complete evidence-backed `contrainte.material-record/0.1`. |
| `manufacturing` | Process intent and a positive `minimum_feature_size`. |
| `limits` | Positive maximum mass and maximum XYZ bounding box. |
| `points` | Canonically ordered point declarations. |
| `constraints` | Canonically ordered linear constraint equations. |
| `profile` | One outer polygon and zero or more inner polygon loops. |
| `extrusion_distance` | Positive extrusion length. |

Unknown fields are rejected. Point and constraint identifiers must be unique and ordered lexically. Each profile loop starts with its lexically lowest point identifier; inner loops are ordered by their first identifier. These canonical ordering rules make semantically identical documents converge on one content digest instead of allowing incidental list order to affect authority.

## Constraint language

Version 0.1 supports five constraint kinds:

| Kind | Required data | Equation |
| --- | --- | --- |
| `fixed` | `point_id`, `x`, `y` | Fixes both coordinates of one point. |
| `horizontal` | `first_point_id`, `second_point_id` | Makes the two Y coordinates equal. |
| `vertical` | `first_point_id`, `second_point_id` | Makes the two X coordinates equal. |
| `offset_x` | two point IDs and signed `distance` | Sets `second.x - first.x`. |
| `offset_y` | two point IDs and signed `distance` | Sets `second.y - first.y`. |

All coordinates and offsets are lengths. Signed offsets make direction explicit; profile winding remains a separate semantic rule.

The solver converts values to rational millimetres and performs Gaussian elimination. A valid sketch has one unique solution for every X and Y coordinate. The compiler rejects:

- inconsistent equation systems;
- sketches with any free coordinate;
- redundant or overconstraining equations;
- constraints that reference unknown or identical points; and
- solved coordinates that cannot be represented as finite decimals in evidence JSON.

The evidence report records the variable count, equation count, matrix rank, rational-arithmetic identity, and every solved coordinate.

## Profile semantics

Every declared point must occur exactly once across the profile loops. The outer loop must be counter-clockwise; holes must be clockwise. Loops must contain at least three distinct vertices and must not repeat the closing vertex.

The topology validator rejects self-intersection, intersections between loops, holes outside or touching the outer boundary, and nested or intersecting holes. Every polygon edge and the extrusion distance must meet the manufacturing minimum feature size. Exact segment-distance checks also enforce that minimum between non-adjacent edges in one loop, between the outer boundary and each hole, and between separate holes.

The current profile language contains straight segments only. A hole is represented by an inner polygon, not by a special pocket operation. All loops are extruded through the complete distance; version 0.1 does not represent blind pockets.

## Engineering checks

Compilation proceeds only when the following checks pass:

1. Strict schema parsing and canonical identities.
2. Exact linear constraint solution with full rank.
3. Simple, correctly wound profile topology.
4. Minimum edge, wall/loop separation, and extrusion feature sizes.
5. One valid, positive-volume Open CASCADE solid.
6. Kernel volume agreement with exact profile area multiplied by extrusion distance.
7. Mass below the declared maximum, using the embedded material density.
8. Exact-body bounding dimensions below the declared XYZ limits.

The volume cross-check and mass gate originate from the raw kernel volume. Serialized kernel measurements and bounding dimensions are normalized to nine decimal places so harmless platform-level floating-point tails do not change bundle identities.

## Evidence and verification

A successful compile writes four files beside one another:

- `<part_id>.step`, the normalized exact-geometry exchange artifact;
- `<part_id>.stl`, a deterministic visualization mesh;
- `<part_id>.svg`, a dimensionally derived profile drawing; and
- `<part_id>.sketch-bundle.json`, the evidence bundle.

The `contrainte.sketch-bundle/0.1` document pins the normalized sketch and material digests, complete analysis, kernel package versions, named passed checks, artifact roles, sizes, and SHA-256 hashes. Its own digest covers the entire bundle content.

Verification is reproduction, not a checksum-only operation. It reparses the embedded sketch, solves every constraint, rebuilds and remeasures the B-rep, compares the full analysis and kernel identity, checks the exact expected check list, and verifies all three referenced artifacts.

A verified sketch bundle can be passed to `contrainte component derive`. The resulting unqualified component manifest pins the source bundle, exact STEP geometry, mesh, drawing, and B-rep-derived bounds under the same release boundary as the other public CAD forms.

## CLI

Install the optional CAD backend, then compile and verify the demonstration fixture:

```powershell
python -m pip install -e ".[cad]"
python -m contrainte sketch compile examples/constrained-pocket-plate.json --output-dir artifacts/constrained-pocket-plate
python -m contrainte sketch verify artifacts/constrained-pocket-plate/plate.sketch.demo.sketch-bundle.json
```

The compile command prints the bundle digest. The verify command prints a JSON report containing `status`, `bundle_digest`, and `sketch_digest`. A validation, execution, integrity, or artifact failure returns exit status 2 and a concise error on standard error.

## Deliberate limits and nonclaims

Version 0.1 is not a general 2D constraint solver or a full mechanical feature modeller. It does not provide arcs, circles, splines, tangency, angles, equal-length constraints, symmetry, construction geometry, reference dimensions, datum systems, fillets, chamfers, shells, lofts, sweeps, draft, threads, or partial-depth pockets.

The minimum-feature check covers nominal polygon edge length, extrusion distance, and separation between non-adjacent or separate loop segments. It does not establish tolerance-conditioned wall or ligament thickness, tool accessibility, internal-corner radius, cutter compensation, stock allowance, feeds and speeds, fixturing, surface finish, distortion, residual stress, or manufacturability for the named process.

The SVG is a profile visualization, not a controlled manufacturing drawing. The STEP file has no AP242 product-manufacturing information, GD&T, semantic face naming, or persistent topological references. The STL is never engineering authority.

Mass and envelope checks are deterministic screening gates, not structural, thermal, fatigue, vibration, fluid, contamination, cleaning, or process simulations. The bundled synthetic material example is not a qualified material record. Every output is marked `unqualified_demonstration`; passing compilation or verification does not make a part safe, certified, validated, GMP compliant, or released for manufacture.
