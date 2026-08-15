# Exact assemblies

Contrainte assemblies place validated part definitions into a common coordinate system and make pairwise spatial acceptance explicit. An assembly build is rejected before export when exact Open CASCADE geometry intersects or when the measured separation is below the declared clearance.

## Contract

An `contrainte.assembly/0.1` document contains:

- a self-contained library of digestible prismatic part definitions;
- one or more named occurrences that reference those parts;
- a rigid translation and XYZ rotation for every occurrence;
- a non-negative default minimum clearance; and
- optional pair-specific clearance overrides in canonical identifier order.

The self-contained part library is intentional. The assembly digest cannot silently change because an external file or mutable catalogue entry changed. Repeated occurrences reuse one part definition while retaining independent placements.

## Authority boundary

`compile_assembly` builds each part as an exact B-rep, applies its rigid transform, and evaluates every unordered occurrence pair. A pair fails if its boolean common volume exceeds `0.000001 mm3`, or if its exact shape distance is more than `0.000001 mm` below the applicable clearance. These numeric tolerances exist to absorb kernel-scale noise; they are not manufacturing tolerances.

The output bundle records:

- the canonical input assembly and its digest;
- exact pair distances, common volumes, limits, and statuses;
- the assembly bounding box and analytical total mass;
- a deterministic STEP assembly and STL visualization mesh; and
- SHA-256, media type, role, and size for every artifact.

STEP timestamps and Open CASCADE's process-global assembly occurrence counter are normalized. Identical inputs therefore produce identical artifact and bundle digests even in a long-running worker process.

`verify_assembly_bundle` checks the bundle digest, reparses the strict schema, rebuilds the exact geometry, reproduces the analysis, and verifies every artifact byte-for-byte. It does not assert fitness for service or replace load cases, tolerance stacks, joint verification, or qualified engineering review.

## CLI

```powershell
python -m contrainte assembly compile examples/plate-pair-assembly.json --output-dir artifacts/plate-pair
python -m contrainte assembly verify artifacts/plate-pair/assembly.plate-pair.assembly-bundle.json
```

The example is a synthetic geometry fixture. Its clearances and material claims are demonstrations, not released engineering data.
