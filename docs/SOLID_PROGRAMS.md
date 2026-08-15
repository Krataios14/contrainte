# Exact solid programs

The `contrainte.solid-program/0.1` contract is a general, deterministic construction language for single-body mechanical geometry. It sits between the introductory prismatic-part schema and future constrained sketches, persistent topology, and domain-specific feature systems.

## Feature graph

A program is a directed acyclic graph with one declared output node. Version 0.1 provides three exact primitives and three exact boolean operations:

| Operation | Inputs | Parameters |
| --- | --- | --- |
| `box` | none | positive `x`, `y`, and `z` lengths |
| `cylinder` | none | positive `radius` and `height` lengths |
| `sphere` | none | positive `radius` length |
| `union` | two or more | none |
| `cut` | one base followed by one or more tools | none |
| `intersection` | two or more | none |

Every node has a rigid XYZ translation and rotation. Primitive transforms place stock or tools. A transform on a boolean node moves the complete result of that operation.

The compiler rejects unknown references, duplicate identifiers, cycles, unused nodes, self-references, duplicate inputs, invalid arity, unsupported parameters, and non-canonical operand order. Union and intersection operands must be lexically sorted. Cut tools must be lexically sorted after the first base operand. These rules remove ordering ambiguity from generated programs and cache identities.

## Engineering constraints

The program embeds a complete evidence-backed material record, manufacturing process intent, a minimum primitive feature size, maximum mass, and maximum XYZ bounding-box dimensions. The minimum feature rule is enforced before kernel execution. Mass and envelope limits are checked against the final exact Open CASCADE body.

The output must be a valid, positive-volume, single-solid B-rep. Disconnected collections cannot be released as one part. Each intermediate node records its operation, solid count, and canonicalized exact-kernel volume so a failed feature chain can be diagnosed without interpreting a mesh.

Kernel measurements are evaluated at raw precision against constraints, then canonicalized at `0.000000001` in the reported unit. This is far below the current geometric acceptance tolerances and prevents irrelevant platform floating-point tails from changing evidence identities.

## Evidence bundle

A successful compilation writes:

- deterministic exact STEP geometry;
- a deterministic STL visualization mesh;
- the normalized solid program and its SHA-256;
- the material-record SHA-256;
- mass, volume, envelope, and per-node results;
- build123d and Open CASCADE distribution versions;
- explicit passed checks and artifact hashes; and
- a digest over the complete bundle content.

Verification reparses the strict program, rebuilds the feature graph, reproduces all analysis, and hashes every referenced artifact. STEP timestamps and Open CASCADE process-global occurrence counters are normalized before hashing.

## CLI

```powershell
python -m contrainte solid compile examples/pedestal-bracket.json --output-dir artifacts/pedestal-bracket
python -m contrainte solid verify artifacts/pedestal-bracket/bracket.demo.solid-bundle.json
```

The example uses a synthetic material record and is not engineering-release data.

## Deliberate limits

Version 0.1 is an exact CSG program, not a sketch-constraint solver or full mechanical feature history. It does not yet provide persistent face/edge naming, fillets, chamfers, shells, lofts, sweeps, threads, GD&T, tolerance stacks, drawings, joints, or service physics. Those capabilities must be added as versioned operations with regression fixtures; they must not be inferred from unstable kernel topology.
