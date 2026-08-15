# Contrainte

Contrainte is an evidence-first engineering compiler for constrained physical design. The long-term system joins editable parametric CAD, source-aware commercial parts, contextual materials, verified physics, contamination analysis, cleaning analysis, and controlled engineering records.

The central rule is: AI may propose, but deterministic engines, evidence, and named reviewers establish authority.

This public repository is at its first executable engineering milestone. It contains the complete [technical specification](TECHNICAL_SPEC.md), a deterministic evidence core, a constrained Open CASCADE CAD path, and a durable design-program runtime. 

Contrainte is a component rather than a closed application. A factory designer, process simulator, PLM integration, or digital-twin runtime can consume a versioned component manifest without taking ownership of Contrainte's engineering semantics. The [integration contract](docs/INTEGRATION_CONTRACT.md) defines that boundary.

## Current capabilities

- Exact decimal parsing for engineering values.
- Typed quantities with SI conversion and dimensional checks.
- Evidence references whose inline content is verified by SHA-256.
- Claims that retain basis, status, applicability, and evidence links.
- A deterministic analytical axial-tension solver.
- Canonical JSON with stable SHA-256 bundle identifiers.
- Content-addressed component manifests with typed interfaces, exact rational interface frames, and exact-geometry bounds reproduced from the source B-rep.
- Exact rational rigid-transform algebra with proper-rotation proofs, composition, inversion, point application, and bounded canonical evidence.
- Bounded exact interface-assembly search with ranked mating alternatives, cycle closure, explicit inconclusive states, and an independent first-feasible replay oracle.
- Digest-sealed reference components with evidence ceilings, physical frames, occupied/keepout/access/service envelopes, exact mass properties, unknown-field blockers, legal-workflow nonclaims, and independently replayed design-around projections.
- Evidence-backed material records with density, elasticity, yield, and Poisson claims.
- A strict prismatic-part feature model with dimensional tolerances, worst-case edge-distance checks, and worst-case hole web checks.
- Optional build123d/Open CASCADE compilation to exact STEP, STL, and SVG, followed by B-rep validity and independent volume checks.
- Exact rigid assemblies with exhaustive pairwise interference and minimum-clearance checks, reproducible STEP/STL exports, and independently reproducible analysis.
- Geometry-backed component assemblies that bind replayed exact interface solutions to verified local component releases, project rational poses directly into Open CASCADE matrices, and reject interference or insufficient clearance before deterministic export.
- General exact-solid feature DAGs with boxes, cylinders, spheres, rigid transforms, boolean construction, graph validation, feature-size rules, and mass/envelope limits.
- Fully constrained sketches solved with exact rational arithmetic, strict polygon topology, exact-diameter circular through-holes, symbolic circular-area evidence, and evidence-backed Open CASCADE extrusion.
- Strict design-program DAGs with declared work products, execution authority, acceptance criteria, and human gates.
- Content-addressed resumable workspaces that detect state or object tampering.
- Isolated subscription-CLI adapters for Codex, Claude, or two independent candidates.
- CLI commands for CAD, program validation, workspace state, provider diagnostics, and the original analytical bundle.
- Standard-library-only base runtime; the exact CAD backend is an isolated optional extra.

The analytical solver is a screening demonstration. It assumes a uniform prismatic member, centered axial tensile load, small strain, linear elasticity, and no stress concentrations. It is not a general structural analysis or a qualified engineering release tool.

## Run it

Install the base library and run the deterministic tests:

```powershell
$env:PYTHONPATH = "src"
python -m contrainte compile examples/axial-member.json --output artifacts/axial-member.bundle.json
python -m contrainte verify artifacts/axial-member.bundle.json
python -m unittest discover -s tests -v
```

Install the exact CAD backend, compile the constrained mounting plate, and verify every artifact:

```powershell
python -m pip install -e ".[cad]"
python -m contrainte cad compile examples/mounting-plate.json --output-dir artifacts/mounting-plate
python -m contrainte cad verify artifacts/mounting-plate/plate.demo.cad-bundle.json
```

Compile a multi-part assembly only after every exact pair passes interference and clearance checks:

```powershell
python -m contrainte assembly compile examples/plate-pair-assembly.json --output-dir artifacts/plate-pair
python -m contrainte assembly verify artifacts/plate-pair/assembly.plate-pair.assembly-bundle.json
```

Compile a general single-body boolean feature program with material, manufacturing, mass, and envelope constraints:

```powershell
python -m contrainte solid compile examples/pedestal-bracket.json --output-dir artifacts/pedestal-bracket
python -m contrainte solid verify artifacts/pedestal-bracket/bracket.demo.solid-bundle.json
```

Solve a constrained polygon profile, compile its exact-kernel extrusion, and reproduce its evidence:

```powershell
python -m contrainte sketch compile examples/constrained-pocket-plate.json --output-dir artifacts/constrained-pocket-plate
python -m contrainte sketch verify artifacts/constrained-pocket-plate/plate.sketch.demo.sketch-bundle.json
```

Version 0.2 adds analytically exact circular through-hole dimensions and rational
clearance decisions while retaining symbolic pi coefficients as the area and volume
authority:

```powershell
python -m contrainte sketch compile examples/circular-through-hole-plate.json --output-dir artifacts/circular-through-hole-plate
python -m contrainte sketch verify artifacts/circular-through-hole-plate/plate.circular.demo.sketch-bundle.json
```

Verified sketch bundles use the same component-release boundary as prismatic, solid-program, and assembly bundles. Derivation preserves the exact geometry, drawing, mesh, source-bundle identity, and explicit unqualified status rather than treating the sketch as an informal precursor.

Derive an explicitly unqualified component manifest that pins the exact bundle and every local artifact, then verify the complete chain:

```powershell
python -m contrainte component derive artifacts/pedestal-bracket/bracket.demo.solid-bundle.json examples/pedestal-component.json --output artifacts/pedestal-bracket/component.fixture.demo.json
python -m contrainte component verify artifacts/pedestal-bracket/component.fixture.demo.json
```

Use the versioned framed request when a downstream assembly needs an exact engineering-bundle-local interface pose. The release compiler proves a right-handed orthonormal rational basis and checks the origin against reproduced B-rep bounds:

```powershell
python -m contrainte component derive artifacts/pedestal-bracket/bracket.demo.solid-bundle.json examples/pedestal-component-framed.json --output artifacts/pedestal-bracket/component.fixture.framed-demo.json
python -m contrainte component verify artifacts/pedestal-bracket/component.fixture.framed-demo.json
```

Bounds containment is deliberately conservative: it does not claim that the frame is attached to a face, hole, or mating surface.

Place component occurrences through exact semantic interface equations and replay the complete search result:

```powershell
python -m contrainte interface-assembly solve examples/motor-design-around-interface.json --output artifacts/motor-design-around.result.json
python -m contrainte interface-assembly verify examples/motor-design-around-interface.json artifacts/motor-design-around.result.json
```

The synthetic example anchors an existing motor and solves compatible mechanical-shaft and DC-link placements around it. Its placeholder artifact digests are deliberately unqualified and are not source evidence. The interface solver is a semantic placement gate, not a collision or physics solver. A production design-around flow must verify each referenced component release and run the resulting poses through exact geometry, tolerance, load, access, manufacturing, and qualification checks.

Compile a solved interface result against B-reps reproduced from actual local component releases:

```powershell
python -m contrainte cad compile examples/mounting-plate.json --output-dir artifacts/component-pair-source
python -m contrainte component derive artifacts/component-pair-source/plate.demo.cad-bundle.json examples/component-pair-left-release.json --output artifacts/component-pair-source/left.component.json
python -m contrainte component derive artifacts/component-pair-source/plate.demo.cad-bundle.json examples/component-pair-right-release.json --output artifacts/component-pair-source/right.component.json
python -m contrainte component-assembly prepare examples/component-pair-interface.json examples/component-pair-assembly.json --source-root . --output-dir artifacts/component-pair-prepared
python -m contrainte interface-assembly verify artifacts/component-pair-prepared/component-pair.interface.json artifacts/component-pair-prepared/component-pair.interface-result.json
python -m contrainte component-assembly compile artifacts/component-pair-prepared/component-pair.component-assembly.json --source-root . --output-dir artifacts/component-pair-assembly
python -m contrainte component-assembly verify artifacts/component-pair-assembly/component-pair.component-assembly-bundle.json --source-root .
```

The checked-in pair templates are completed by CAD compilation, local component
derivation, and the platform-local preparation step in CI. Preparation replaces
template manifests, solves and replays the interface equations, and writes a
strict compile input pinned to the exact local release bytes. Exact rational
transforms remain semantic authority; their direct Open CASCADE matrix projection
and every nominal B-rep pair decision are separately recorded. This is not
tolerance, motion, joint, load, or service-space verification.

Protect an existing component before surrounding design begins:

```powershell
python -m contrainte reference-component seal examples/reference-motor-payload.json --output artifacts/reference-motor.json
python -m contrainte reference-component seal-request examples/reference-motor-design-around-payload.json --output artifacts/reference-motor.request.json
python -m contrainte reference-component project artifacts/reference-motor.json artifacts/reference-motor.request.json --output artifacts/reference-motor.projection.json
python -m contrainte reference-component verify artifacts/reference-motor.json artifacts/reference-motor.request.json artifacts/reference-motor.projection.json
```

The example deliberately retains unresolved torque-map and evidence-authority blockers. A scan or Gaussian splat may contribute observational geometry, but cannot silently become dimensional, material, mass, performance, or legal authority.

Inspect a design program and initialize durable state:

```powershell
python -m contrainte program validate examples/design-program.json
python -m contrainte workspace init examples/design-program.json --root artifacts/design --run-id demo
python -m contrainte agents doctor
```

Both examples use synthetic data and are explicitly unsuitable for engineering release.

## Near-term development sequence

The current CAD slice proves the authority chain on rectangular milled parts, polygonal constrained sketch extrusions with circular through-holes, strict exact-solid boolean programs, and exact rigid assemblies. It is not yet a full mechanical feature modeller. The next geometry gates are richer constraints and feature operations, persistent semantic topology, tolerance analysis, controlled drawings, STEP AP242 metadata, and broad parameter-perturbation tests. Source adapters, qualified material packs, solver capsules, contamination, cleaning, and qualified/GxP workflows follow as separate evidence gates.

The [integration contract](docs/INTEGRATION_CONTRACT.md) documents how private or third-party systems consume released components.
The [exact-transform contract](docs/EXACT_TRANSFORMS.md) defines local-to-parent composition semantics, strict rational invariants, and its evidence boundary.
The [interface-assembly contract](docs/INTERFACE_ASSEMBLIES.md) defines exact mating equations, ranked bounded search, independent terminal replay, and design-around nonclaims.
The [geometry-backed component-assembly contract](docs/COMPONENT_ASSEMBLIES.md) defines verified local-release binding, direct exact-matrix projection, nominal B-rep pair checks, and its deliberate evidence limits.
The [reference-component contract](docs/REFERENCE_COMPONENTS.md) defines evidence ceilings, protected existing-part semantics, explicit flexible domains, and independently replayed design-around projections.
The [assembly contract](docs/ASSEMBLIES.md) defines exact placement, pairwise verification, artifact reproducibility, and the limits of the current checks.
The [solid-program contract](docs/SOLID_PROGRAMS.md) defines the exact feature DAG, deterministic boolean semantics, enforced limits, and deliberate topology boundary.
The [sketch-extrusion contract](docs/SKETCHES.md) defines exact linear constraint solving, profile topology, kernel cross-checks, and deliberate geometric limits.

## Repository policy

No claim in this repository means that Contrainte is validated, certified, or GMP compliant. A regulated organization must define and validate its own intended use, configuration, procedures, controls, and records.

Contrainte is licensed under Apache-2.0. The license is intended to make the public engineering core practical to adopt and extend in commercial and open-source systems; it is not a certification or warranty of fitness for an engineering purpose.
