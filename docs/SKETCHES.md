# Constrained sketch extrusions

The `contrainte.sketch-extrusion/0.1` contract turns a fully constrained, straight-line planar profile into a single Open CASCADE B-rep. The backward-compatible `contrainte.sketch-extrusion/0.2` contract adds exact-diameter circular through-holes whose centres are ordinary fully constrained sketch points. The additive `contrainte.sketch-extrusion/0.3` contract keeps the 0.2 profile and adds one exact `midpoint` relation. All three add editable dimensional intent without making a language model, a mesh, or an opaque kernel result the authority for the sketch dimensions.

The contracts deliberately separate two kinds of computation. Point coordinates, polygon areas, circular radii, clearance comparisons, and the rational coefficients of symbolic circular area and volume expressions are exact. Version 0.2 records those expressions in the form `rational_constant + pi * pi_coefficient`. A pinned 100-place decimal expansion of pi is used only to compare the expression with build123d and Open CASCADE; it is never presented as exact mathematical pi or as the engineering authority. Kernel volume must agree with the independent analytic comparison within a relative error of `0.00000001`.

## Input document

A sketch extrusion contains exactly these top-level fields:

| Field | Meaning |
| --- | --- |
| `schema_version` | `contrainte.sketch-extrusion/0.1`, `/0.2`, or `/0.3`. |
| `part_id` | Stable, filesystem-safe part identity. |
| `revision` | Source revision label. |
| `title` | Human-readable description. |
| `material` | Complete evidence-backed `contrainte.material-record/0.1`. |
| `manufacturing` | Process intent and a positive `minimum_feature_size`. |
| `limits` | Positive maximum mass and maximum XYZ bounding box. |
| `points` | Canonically ordered point declarations. |
| `constraints` | Canonically ordered linear constraint equations. |
| `profile` | One outer polygon, inner polygon loops, and, in 0.2 and 0.3, canonically ordered circular holes. |
| `extrusion_distance` | Positive extrusion length. |

Unknown fields are rejected. Point and constraint identifiers must be unique and ordered lexically. Each profile loop starts with its lexically lowest point identifier; inner loops are ordered by their first identifier. Versions 0.2 and 0.3 require a `circular_holes` list ordered by unique `circle_id`. Every circle contains exactly `circle_id`, `center_point_id`, and a positive length `diameter`. These canonical ordering rules make semantically identical documents converge on one content digest instead of allowing incidental list order to affect authority.

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

### Midpoint relation in version 0.3

Version 0.3 accepts every 0.2 document shape and adds exactly one constraint kind:

| Kind | Required data | Equation |
| --- | --- | --- |
| `midpoint` | `first_point_id`, `second_point_id`, `midpoint_point_id` | `2 * midpoint - first - second = 0` in X and in Y. |

The three point IDs must be distinct, declared points. The relation adds two rational equations to the same elimination as every other constraint, so it is subject to the same rank, consistency, and redundancy rules. A midpoint combined with a fixed position for the same centre is redundant when it agrees and inconsistent when it does not. The midpoint of finite decimal endpoints is itself a finite decimal, so evidence stays exact.

The intended use is locating a circular hole centre midway between two existing profile points. If those endpoints are re-dimensioned, the centre follows. Circle-centre containment and clearance checks then run on the derived position. For example:

```json
{
  "constraint_id": "c15",
  "kind": "midpoint",
  "first_point_id": "p0",
  "second_point_id": "h0",
  "midpoint_point_id": "q0"
}
```

Versions 0.1 and 0.2 keep their closed five-kind vocabulary and reject `midpoint`. Their parsing, serialization, digests, analyses, and bundles are unchanged. Input 0.3 produces `contrainte.sketch-bundle/0.3`. Its analysis fields and check list are the same as 0.2, because the relation changes how points are solved, not the geometry vocabulary.

### Circular holes in version 0.2

A circular centre is declared in `points` and constrained with the same exact linear language as any polygon vertex. Every declared point must be used exactly once: as one polygon vertex or as one circular centre. A centre cannot be shared by circles or reused as a polygon vertex. Consequently, an omitted centre coordinate makes the whole sketch underconstrained rather than allowing the CAD kernel to infer a position.

Diameter is the only accepted input dimension. Radius is derived as the exact rational value `diameter / 2` and both are serialized in analysis. The compiler rejects non-positive diameters and diameters below `minimum_feature_size`. For example:

```json
"circular_holes": [
  {
    "circle_id": "hole.01",
    "center_point_id": "c0",
    "diameter": {"kind": "length", "unit": "mm", "value": "10"}
  }
]
```

The analytic area authority does not pretend that pi is rational. For circles with exact radii `r_i`, the profile records `polygon_net_area - pi * sum(r_i²)`. Extrusion multiplies both exact rational coefficients by the exact distance. Analysis separately declares the pinned 100-place pi value, Decimal arithmetic precision, rounding mode, and its comparison-only scope. Verification recomputes every coefficient and the comparison basis from the embedded normalized sketch.

## Profile semantics

In 0.1, every declared point must occur exactly once across the profile loops. In 0.2 and 0.3, it must occur exactly once across the loops and circle centres. The outer loop must be counter-clockwise; polygon holes must be clockwise. Loops must contain at least three distinct vertices and must not repeat the closing vertex.

The topology validator rejects self-intersection, intersections between loops, holes outside or touching the outer boundary, and nested or intersecting holes. Every polygon edge, circular diameter, and the extrusion distance must meet the manufacturing minimum feature size. Exact squared-distance comparisons enforce minimum clear material between non-adjacent polygon edges, the outer boundary and every hole, polygon holes and circles, and pairs of circles. Equality with the declared minimum passes; any smaller rational clearance fails before Open CASCADE is invoked.

Polygon boundaries remain straight segments. Version 0.2 circular holes are actual build123d `Circle` faces subtracted before extrusion, not polygonal approximations. All polygon and circular holes pass through the complete extrusion distance; neither version represents blind pockets.

## Engineering checks

Compilation proceeds only when the following checks pass:

1. Strict schema parsing and canonical identities.
2. Exact linear constraint solution with full rank.
3. Simple, correctly wound profile topology.
4. Minimum edge, wall/loop separation, and extrusion feature sizes.
5. One valid, positive-volume Open CASCADE solid.
6. Kernel volume agreement with exact polygon volume in 0.1, or the exact symbolic coefficients evaluated using the declared pinned-pi comparison basis in 0.2.
7. Mass below the declared maximum, using the embedded material density.
8. Exact-body bounding dimensions below the declared XYZ limits.

The volume cross-check and mass gate originate from the raw kernel volume. Serialized kernel measurements and bounding dimensions are normalized to nine decimal places so harmless platform-level floating-point tails do not change bundle identities.

## Evidence and verification

A successful compile writes four files beside one another:

- `<part_id>.step`, the normalized exact-geometry exchange artifact;
- `<part_id>.stl`, a deterministic visualization mesh;
- `<part_id>.svg`, a dimensionally derived profile drawing; and
- `<part_id>.sketch-bundle.json`, the evidence bundle.

Input 0.1 produces `contrainte.sketch-bundle/0.1`; input 0.2 produces `contrainte.sketch-bundle/0.2`; input 0.3 produces `contrainte.sketch-bundle/0.3`. The verifier rejects cross-version substitution. Both pin the normalized sketch and material digests, complete analysis, kernel package versions, named passed checks, artifact roles, sizes, and SHA-256 hashes. Their own digest covers the entire bundle content.

Verification is reproduction, not a checksum-only operation. It reparses the embedded sketch, solves every constraint, rebuilds and remeasures the B-rep, compares the full analysis and kernel identity, checks the exact expected check list, and verifies all three referenced artifacts.

A verified 0.1, 0.2, or 0.3 sketch bundle can be passed to `contrainte component derive`. The resulting unqualified component manifest pins the source bundle, exact STEP geometry, mesh, drawing, and B-rep-derived bounds under the same release boundary as the other public CAD forms.

Release of a 0.3 bundle is additive. It uses the existing release requests 0.1 and 0.2 and component manifests 0.2 and 0.3. The manifest records `engineering_bundle_schema` as `contrainte.sketch-bundle/0.3` and keeps the existing derivation labels. Derivation and every later verification run the complete 0.3 verifier on one captured snapshot: they re-solve the midpoint relations, rebuild the B-rep from the solved coordinates, and reject a bundle relabelled as 0.2. Bounds and the geometry passed to component assemblies come from that rebuilt B-rep, never from the STEP or STL files. Topology-backed release request 0.3 still accepts only prismatic CAD bundles. Any other sketch-bundle version stays unsupported. A consumer built before this change rejects 0.3-derived components as an unsupported engineering bundle schema rather than reading them as 0.2.

## CLI

Install the optional CAD backend, then compile and verify the demonstration fixture:

```powershell
python -m pip install -e ".[cad]"
python -m contrainte sketch compile examples/constrained-pocket-plate.json --output-dir artifacts/constrained-pocket-plate
python -m contrainte sketch verify artifacts/constrained-pocket-plate/plate.sketch.demo.sketch-bundle.json
python -m contrainte sketch compile examples/circular-through-hole-plate.json --output-dir artifacts/circular-through-hole-plate
python -m contrainte sketch verify artifacts/circular-through-hole-plate/plate.circular.demo.sketch-bundle.json
python -m contrainte sketch compile examples/midpoint-hole-plate.json --output-dir artifacts/midpoint-hole-plate
python -m contrainte sketch verify artifacts/midpoint-hole-plate/plate.midpoint.demo.sketch-bundle.json
python -m contrainte component derive artifacts/midpoint-hole-plate/plate.midpoint.demo.sketch-bundle.json examples/pedestal-component.json --output artifacts/midpoint-hole-plate/component.fixture.demo.json
python -m contrainte component verify artifacts/midpoint-hole-plate/component.fixture.demo.json
```

In `examples/midpoint-hole-plate.json`, the centre of `hole.01` is the exact midpoint of the plate diagonal `p0`-`p2`, which is (50, 30).

The compile command prints the bundle digest. The verify command prints a JSON report containing `status`, `bundle_digest`, and `sketch_digest`. A validation, execution, integrity, or artifact failure returns exit status 2 and a concise error on standard error.

## Deliberate limits and nonclaims

No version is a general 2D constraint solver or a full mechanical feature modeller. Version 0.2 provides circular through-holes, but not circular bosses or arbitrary circular outer profiles. Version 0.3's midpoint is a point-to-two-points linear relation. It is not general symmetry, a point-on-line or point-on-circle relation, a pattern, or a construction line. The language does not provide arcs, ellipses, splines, tangency, angles, equal-length constraints, symmetry, construction geometry, reference dimensions, datum systems, fillets, chamfers, shells, lofts, sweeps, draft, threads, or partial-depth pockets.

The minimum-feature check covers nominal polygon edge length, circle diameter, extrusion distance, and exact nominal boundary separation. It does not establish tolerance-conditioned wall or ligament thickness, tool accessibility, internal-corner radius, cutter compensation, stock allowance, feeds and speeds, fixturing, surface finish, distortion, residual stress, or manufacturability for the named process.

The SVG is a profile visualization, not a controlled manufacturing drawing. The STEP file has no AP242 product-manufacturing information, GD&T, semantic face naming, or persistent topological references. The STL is never engineering authority.

Mass and envelope checks are deterministic screening gates, not structural, thermal, fatigue, vibration, fluid, contamination, cleaning, or process simulations. The bundled synthetic material example is not a qualified material record. Every output is marked `unqualified_demonstration`; passing compilation or verification does not make a part safe, certified, validated, GMP compliant, or released for manufacture.
