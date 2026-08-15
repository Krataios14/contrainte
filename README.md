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
- Content-addressed component manifests with typed physical and control interfaces.
- Evidence-backed material records with density, elasticity, yield, and Poisson claims.
- A strict prismatic-part feature model with dimensional tolerances, worst-case edge-distance checks, and worst-case hole web checks.
- Optional build123d/Open CASCADE compilation to exact STEP, STL, and SVG, followed by B-rep validity and independent volume checks.
- Exact rigid assemblies with exhaustive pairwise interference and minimum-clearance checks, reproducible STEP/STL exports, and independently reproducible analysis.
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

Inspect a design program and initialize durable state:

```powershell
python -m contrainte program validate examples/design-program.json
python -m contrainte workspace init examples/design-program.json --root artifacts/design --run-id demo
python -m contrainte agents doctor
```

Both examples use synthetic data and are explicitly unsuitable for engineering release.

## Near-term development sequence

The current CAD slice proves the authority chain on rectangular milled parts with through-holes and exact rigid assemblies; it is not yet a general feature modeller. The next geometry gates are a versioned general feature graph, sketch constraint solving, persistent semantic topology, tolerance analysis, drawings, STEP AP242 metadata, and broad parameter-perturbation tests. Source adapters, qualified material packs, solver capsules, contamination, cleaning, and qualified/GxP workflows follow as separate evidence gates.

The [integration contract](docs/INTEGRATION_CONTRACT.md) documents how private or third-party systems consume released components.
The [assembly contract](docs/ASSEMBLIES.md) defines exact placement, pairwise verification, artifact reproducibility, and the limits of the current checks.

## Repository policy

No claim in this repository means that Contrainte is validated, certified, or GMP compliant. A regulated organization must define and validate its own intended use, configuration, procedures, controls, and records.

Contrainte is licensed under Apache-2.0. The license is intended to make the public engineering core practical to adopt and extend in commercial and open-source systems; it is not a certification or warranty of fitness for an engineering purpose.
