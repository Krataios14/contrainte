# Contrainte

## Technical specification

- Document version: `0.1.0-draft`.
- Document date: `2026-08-14`.
- Product status: pre-alpha architecture baseline.
- Repository status: private development workspace.
- Intended audience: mechanical engineers, materials engineers, simulation engineers, validation engineers, quality assurance, software engineers, and technical reviewers.
- Normative vocabulary: `MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, and `MAY` have their ordinary requirements-engineering meanings in this document.
- This document is a build specification, not marketing copy.
- This document does not claim that Contrainte is validated, approved, certified, or suitable for an undeclared regulated use.
- A deployment can only be validated for a defined intended use by the regulated organization operating it.
- References to standards identify design inputs and do not imply certification by the issuing organization.

---

## 1. Product definition

- Contrainte is an evidence-first engineering system for creating, modifying, sourcing, evaluating, and releasing parametric physical designs.
- Contrainte turns human intent into an editable engineering model rather than a disposable mesh or image.
- Contrainte combines constrained CAD, source-aware components, contextual material models, verified physics workflows, contamination analysis, cleaning analysis, and controlled engineering records.
- Contrainte uses AI to interpret, synthesize, retrieve, explain, and propose.
- Contrainte uses deterministic engines to construct, calculate, check, serialize, and reproduce.
- Contrainte uses human approval to authorize consequential engineering claims and regulated records.
- Contrainte treats every design value as a claim with context, origin, applicability, and status.
- Contrainte treats every simulation as an argument with assumptions, numerical evidence, and an applicability envelope.
- Contrainte treats every generated solver as untrusted research software until it passes a declared qualification process.
- Contrainte treats every supplier part as a revisioned external dependency rather than timeless geometry.
- Contrainte treats every material property as conditional on material identity, state, environment, and evidence basis.
- Contrainte treats contamination and cleaning as first-class design constraints rather than downstream checklists.
- Contrainte treats data integrity as a product feature rather than a documentation exercise.
- Contrainte is designed to be useful before it is fully qualified.
- Contrainte separates useful exploratory behavior from controlled and qualified behavior so those goals do not corrupt one another.

### 1.1 Product thesis

- Existing AI-CAD systems tend to optimize visible shape similarity or program executability.
- Visible similarity is insufficient for engineering release.
- Executable CAD code is insufficient for engineering release.
- A geometrically valid solid can still have the wrong dimensions, constraints, tolerances, material, joints, load paths, cleanability, or evidence.
- A numerically converged simulation can still solve the wrong equations or use invalid inputs.
- A manufacturer CAD model can still be stale, simplified, misconfigured, or outside the selected product revision.
- A material database value can still be inapplicable to the selected product form, temperature, orientation, or heat treatment.
- A cleaning simulation can support a risk assessment but cannot by itself validate a cleaning process.
- Contrainte therefore optimizes for traceable engineering correctness rather than plausible appearance.
- The central artifact is a typed design-and-evidence graph called the Contrainte Intermediate Representation.
- The central workflow is proposal, compilation, verification, review, and controlled release.
- The central safety property is that uncertainty and unsupported inference remain visible.

### 1.2 Product promise

- A user can state what a component or assembly must do in natural language.
- A user can add sketches, drawings, tables, catalog pages, STEP files, measurement files, and prior designs.
- Contrainte can propose a parameterized feature history and assembly structure.
- Contrainte can expose degrees of freedom, ambiguities, conflicts, and unresolved requirements.
- Contrainte can build an exact boundary-representation model through an approved geometry kernel.
- Contrainte can attach semantic product and manufacturing information to stable design entities.
- Contrainte can locate candidate standard and commercial parts through governed source adapters.
- Contrainte can preserve the exact source, revision, retrieval time, configuration, and content hash for selected parts.
- Contrainte can select candidate material models from governed evidence packs.
- Contrainte can refuse a material property when its applicability does not cover the analysis state.
- Contrainte can construct a physics plan from declared physics intent and applicability rules.
- Contrainte can run approved analytical and numerical solver capsules in reproducible sandboxes.
- Contrainte can generate a new solver capsule in research mode when no suitable approved capsule exists.
- Contrainte can prevent that generated capsule from entering a controlled release until qualification gates pass.
- Contrainte can model contamination sources, transport paths, deposition, retention, and cleaning access.
- Contrainte can generate evidence packages that connect requirements to design, analysis, tests, risks, and approvals.
- Contrainte can reproduce a released result from immutable inputs and pinned execution artifacts.

### 1.3 Product boundaries

- Contrainte is not an autonomous approver.
- Contrainte is not a universal truth engine.
- Contrainte is not a replacement for engineering competence.
- Contrainte is not a replacement for physical testing.
- Contrainte is not a replacement for process validation.
- Contrainte is not a replacement for quality assurance.
- Contrainte is not a replacement for a product lifecycle management system in the first release.
- Contrainte is not a replacement for enterprise resource planning.
- Contrainte is not a supplier qualification system in the first release.
- Contrainte is not a laboratory information management system.
- Contrainte is not a manufacturing execution system.
- Contrainte is not a regulatory submission generator without human review.
- Contrainte does not claim a single numerical confidence score represents engineering certainty.
- Contrainte does not permit an LLM to silently invent dimensions, tolerances, materials, boundary conditions, or acceptance limits.
- Contrainte does not label exploration artifacts as qualified artifacts.

---

## 2. Research baseline

### 2.1 AI-CAD state of the art

- The 2026 BenchCAD benchmark contains execution-verified CadQuery programs across industrial part families and reports that current models often recover coarse geometry but fail at faithful parametric programs.
- BenchCAD reports recurring failures on fine structure, engineering parameters, sweeps, lofts, and twist-extrudes.
- BenchCAD uses deterministic execution-grounded scoring rather than an LLM judge for its core generation metrics.
- The 2026 Text2CAD-Bench work reports substantial degradation as topology and feature complexity increase.
- The 2026 CADTestBench work argues for executable tests of geometric and topological requirements.
- The August 2026 CADEngBench preprint extends evaluation to B-Rep validity, design-for-manufacture checks, parameter perturbations, editing, matched finite-element response, joint retrieval, and kinematics.
- The research baseline supports a test-driven approach to AI-CAD rather than visual evaluation alone.
- Contrainte MUST evaluate generated designs under parameter perturbation.
- Contrainte MUST evaluate semantic constraints independently of rendered appearance.
- Contrainte MUST evaluate whether selected faces, edges, joints, and load regions remain meaningfully grounded after edits.
- Contrainte MUST include physics equivalence checks where a reference analysis exists.
- Contrainte MUST maintain a benchmark split containing unseen part families.
- Contrainte SHOULD import public benchmark tasks where licensing permits.
- Contrainte SHOULD publish its own evidence-rich benchmark only after the private core is stable.

### 2.2 Geometry and digital-thread baseline

- ISO 10303-242:2025 defines managed model-based 3D engineering information for parts, assemblies, tools, raw materials, configuration, and change.
- STEP AP242 is the primary neutral exchange target for exact product definition.
- ASME Y14.5-2018, reaffirmed in 2024, is a primary authority for geometric dimensioning and tolerancing in the ASME ecosystem.
- ASME Y14.41-2026 establishes practices for digital product definition data sets.
- ISO 23952:2020 defines the Quality Information Framework for model-based manufacturing quality information.
- QIF connects model-based definition, inspection planning, resources, execution, results, and statistics.
- NIST digital-thread research emphasizes semantic PMI, persistent identifiers, and traceability across the product lifecycle.
- Contrainte MUST preserve semantic product intent when exchanging geometry.
- Contrainte MUST distinguish authoritative exact geometry from visualization meshes.
- Contrainte MUST distinguish native design semantics from imported semantics.
- Contrainte MUST record losses, approximations, and unsupported entities during translation.
- Contrainte SHOULD export STEP AP242.
- Contrainte SHOULD import and export QIF where manufacturing-quality workflows require it.
- Contrainte MAY support other neutral formats through explicitly qualified translators.

### 2.3 Geometry-kernel baseline

- Open CASCADE Technology provides exact CAD geometry, topology, modeling algorithms, STEP translation, document structure, and shape-healing facilities.
- OCCT is the baseline exact geometry kernel for the first native implementation.
- OCCT shapes are not themselves sufficient as stable business identifiers.
- OCAF concepts inform parameter dependency, document history, and undo behavior.
- Gmsh can query native OpenCASCADE geometry and create physical groups for simulation regions.
- Direct native-kernel meshing reduces avoidable translation loss.
- Contrainte MUST isolate kernel-specific identifiers behind semantic references.
- Contrainte MUST run geometry validity checks after every committed feature operation.
- Contrainte MUST record kernel version, build flags, and tolerance policy in compiled artifacts.
- Contrainte MUST not use tessellation as the authoritative model for dimensional release.

### 2.4 Simulation credibility baseline

- NASA-STD-7009B defines requirements for credible modeling and simulation across a lifecycle.
- ASME V&V 10 addresses verification and validation in computational solid mechanics.
- ASME V&V 20 addresses computational fluid dynamics and heat transfer.
- ASME VVUQ standards separate code verification, solution verification, validation, and uncertainty quantification.
- PETSc provides scalable linear and nonlinear algebra for PDE applications.
- DOLFINx provides a finite-element environment integrated with PETSc and Gmsh.
- MFEM provides scalable high-order finite elements and adaptive refinement.
- preCICE provides partitioned coupling between existing solvers.
- OpenFOAM provides finite-volume solvers across fluid, thermal, combustion, chemistry, and multiphase domains.
- Code_Aster provides broad structural and thermomechanical finite-element capabilities with extensive validation cases.
- SU2 provides open-source PDE solution and PDE-constrained optimization, especially for CFD.
- Contrainte MUST qualify solver versions and configurations rather than treating a solver brand as universally valid.
- Contrainte MUST distinguish numerical convergence from model validation.
- Contrainte MUST quantify discretization sensitivity for release-grade numerical results.
- Contrainte MUST retain residual histories, conservation checks, mesh metrics, and solver logs.

### 2.5 Materials-data baseline

- NIST Materials Data Resources aggregate experimental, computational, and reference data with varying review status.
- The NIST Materials Data Repository explicitly does not guarantee the utility, veracity, or reliability of deposited data.
- NIST Thermodynamics Research Center data are critically evaluated with provenance and uncertainty for supported domains.
- NIST Alloy Data includes composition, processing, uncertainty, and citations for each data point.
- Materials Project exposes computed material properties and provenance through an API.
- JARVIS exposes computed and experimental materials datasets.
- Computed databases are valuable evidence but are not automatically certified engineering allowables.
- MMPDS is a primary source of statistically based metallic design allowables for relevant aerospace applications.
- MAPTIS provides NASA materials and process data subject to access terms.
- The NASA outgassing database reports data based on ASTM E595-family testing.
- Contrainte MUST rank evidence by authority, review status, applicability, and uncertainty.
- Contrainte MUST not collapse measured, evaluated, computed, predicted, and inferred properties into one undifferentiated number.
- Contrainte MUST preserve licensing and access restrictions on materials data.

### 2.6 GMP and data-integrity baseline

- EU GMP Annex 1 requires a facility-wide contamination control strategy for sterile manufacture.
- EU GMP Annex 11 currently governs computerized systems and is under revision as of this document date.
- EU GMP Annex 15 requires lifecycle qualification and validation, including risk-based cleaning validation.
- ICH Q9(R1) provides quality-risk-management principles.
- ICH Q10 describes a pharmaceutical quality system across the product lifecycle.
- FDA data-integrity guidance expects reliable and accurate data under current good manufacturing practice.
- MHRA and PIC/S guidance expand ALCOA into complete, consistent, enduring, and available records.
- 21 CFR Part 11 applies to qualifying electronic records and electronic signatures under predicate rules.
- GAMP 5 second edition supports a risk-based lifecycle approach focused on intended use.
- Software is not generically "GMP certified."
- A regulated company remains responsible for its intended use, procedures, controls, validation, and records.
- Contrainte MUST describe itself as validation-ready or GMP-enabling only when the corresponding capabilities exist.
- Contrainte MUST NOT claim that installation alone makes an organization compliant.
- Contrainte MUST expose configuration and evidence needed for customer validation.

### 2.7 AI-in-GMP baseline

- The European Commission published a draft Annex 22 on artificial intelligence for consultation in 2025.
- The draft applies to trained AI models in critical applications with direct impact on patient safety, product quality, or data integrity.
- The draft covers static deterministic models and excludes continuously adapting models from critical GMP use.
- The draft says probabilistic-output models should not be used in critical GMP applications.
- The draft says generative AI and large language models should not be used in critical GMP applications.
- The draft permits consideration in non-critical applications with qualified human responsibility for output suitability.
- The draft requires intended-use definition, acceptance criteria, representative independent tests, explainability where applicable, confidence handling, change control, configuration control, monitoring, and human review.
- The draft is not final law or a final GMP annex as of this document date.
- Contrainte nevertheless adopts the draft's conservative boundary as a forward-looking design constraint.
- Generative AI MUST remain outside the qualified critical decision path.
- AI output MUST enter the controlled system as a proposal with provenance.
- A deterministic compiler MUST reject incomplete or invalid proposals.
- A human with an assigned role MUST approve critical promotion decisions.
- An approved deterministic artifact MAY be used in a qualified workflow even when an AI proposal helped create its precursor.
- The final record MUST disclose AI involvement and the controls applied to it.

### 2.8 Contamination and cleaning baseline

- ISO 14644-1:2015 classifies air cleanliness by airborne particle concentration.
- ISO 14644-3:2019 defines cleanroom and clean-zone test methods.
- ISO 14644-8:2022 addresses air cleanliness by chemical concentration.
- ISO 14644-9:2022 addresses surface cleanliness by particle concentration.
- ISO 14644-13:2026 gives guidance for cleaning surfaces to defined particle and chemical cleanliness levels.
- ISO 14644-14:2026 addresses equipment suitability by airborne particle concentration.
- ISO 14644-17:2021 addresses particle deposition rate on vulnerable surfaces.
- FDA cleaning guidance expects scientifically justified limits, written procedures, protocols, suitable sampling, sensitive analytical methods, and documented results.
- FDA states that rinse samples alone are not generally sufficient where direct surface methods are feasible.
- ICH Q7 connects worst-case selection to solubility, cleaning difficulty, potency, toxicity, and stability.
- NASA-STD-6016C controls materials and processes that can damage or contaminate spacecraft hardware.
- Contamination physics spans particles, molecular films, ions, viable organisms, residues, and process-specific species.
- Contrainte MUST keep these contaminant classes distinct.
- Contrainte MUST represent empirical cleaning evidence separately from predicted cleaning performance.
- Contrainte MUST never infer sterility from geometry or CFD alone.

### 2.9 Metrology and canonical-data baseline

- The BIPM SI Brochure is the authority for the International System of Units.
- JCGM 100 establishes general rules for evaluating and expressing measurement uncertainty.
- JCGM 106 addresses uncertainty in conformity assessment.
- UCUM provides unambiguous machine-readable unit expressions.
- RFC 8785 defines a JSON canonicalization scheme for repeatable hashing and signing.
- W3C PROV-O provides a general model for interoperable provenance.
- SLSA provenance describes how software artifacts were produced.
- OCI images are content addressable and provide a portable solver-capsule format.
- SPDX and CycloneDX provide machine-readable software-bill-of-materials formats.
- Sigstore supports identity-linked signatures and attestations for artifacts.
- Contrainte MUST use SI internally for physical calculations.
- Contrainte MUST preserve the user's display unit and original source unit.
- Contrainte MUST reject dimensionally invalid operations before solver execution.
- Contrainte MUST preserve uncertainty and significant-digit intent where supplied.
- Contrainte MUST canonicalize authoritative structured artifacts before hashing.

### 2.10 Source links

- AI-CAD benchmark: https://arxiv.org/abs/2605.10865
- CAD engineering benchmark: https://arxiv.org/abs/2608.09296
- CAD tests benchmark: https://arxiv.org/abs/2605.07807
- Text-to-CAD benchmark: https://arxiv.org/abs/2605.18430
- STEP AP242: https://www.iso.org/standard/84300.html
- ASME Y14.5: https://www.asme.org/codes-standards/find-codes-standards/y14-5-dimensioning-tolerancing/2018
- ASME Y14.41: https://www.asme.org/codes-standards/find-codes-standards/y14-41-digital-product-definition-data-practices
- QIF: https://committee.iso.org/standard/77461.html
- NIST digital thread: https://www.nist.gov/programs-projects/digital-thread-smart-manufacturing
- OCCT documentation: https://dev.opencascade.org/doc/overview/html/
- Gmsh documentation: https://gmsh.info/doc/texinfo/
- NASA-STD-7009B: https://standards.nasa.gov/standard/nasa/nasa-std-7009
- ASME VVUQ: https://www.asme.org/codes-standards/publications-information/verification-validation-uncertainty
- PETSc: https://petsc.org/release/
- DOLFINx: https://docs.fenicsproject.org/
- MFEM: https://mfem.org/
- preCICE: https://precice.org/docs.html
- OpenFOAM: https://www.openfoam.com/documentation/overview
- Code_Aster: https://codeaster.readthedocs.io/en/
- SU2: https://github.com/su2code/SU2
- NIST materials resources: https://www.nist.gov/mgi/materials-data-resources
- NIST Alloy Data: https://www.nist.gov/mml/acmd/trc/nist-alloy-data
- Materials Project: https://docs.materialsproject.org/
- JARVIS: https://jarvis.nist.gov/
- MMPDS: https://www.mmpds.org/
- MAPTIS: https://maptis.nasa.gov/
- NASA outgassing: https://outgassing.nasa.gov/Description
- EU GMP Volume 4: https://health.ec.europa.eu/medicinal-products/eudralex/eudralex-volume-4_en
- EU Annex 1: https://health.ec.europa.eu/latest-updates/revision-manufacture-sterile-medicinal-products-2022-08-25_en
- EU Annex 15: https://health.ec.europa.eu/document/download/7c6c5b3c-4902-46ea-b7ab-7608682fb68d_en?filename=2015-10_annex15.pdf
- Current EU Annex 11: https://health.ec.europa.eu/document/download/8d305550-dd22-4dad-8463-2ddb4a1345f1_en
- Draft EU Annex 22: https://health.ec.europa.eu/document/download/5f38a92d-bb8e-4264-8898-ea076e926db6_en?filename=mp_vol4_chap4_annex22_consultation_guideline_en.pdf
- FDA data integrity: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/data-integrity-and-compliance-drug-cgmp-questions-and-answers
- FDA Part 11 guidance: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application
- PIC/S data integrity: https://picscheme.org/docview/4234
- FDA cleaning validation: https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/inspection-guides/validation-cleaning-processes-793
- ISO 14644-13:2026: https://www.iso.org/standard/91614.html
- ISO 14644-14:2026: https://www.iso.org/standard/91615.html
- BIPM SI Brochure: https://www.bipm.org/en/publications/si-brochure
- JCGM 100: https://www.bipm.org/en/doi/10.59161/jcgm100-2008e
- UCUM: https://ucum.org/ucum
- RFC 8785: https://www.rfc-editor.org/info/rfc8785/
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- NIST SSDF: https://www.nist.gov/publications/secure-software-development-framework-ssdf-version-11-recommendations-mitigating-risk
- SLSA: https://slsa.dev/spec/v1.2/provenance
- OCI: https://opencontainers.org/
- SPDX: https://spdx.dev/use/specifications/
- Sigstore: https://docs.sigstore.dev/
- TraceParts API: https://developers.traceparts.com/v2/docs
- 3Dfindit: https://www.cadenas.de/en/products/ecatalogsolutions/innovative-marketing-strategies/3dfindit-com

---

## 3. Goals, non-goals, and success criteria

### 3.1 Primary goals

- G-001: Produce editable parametric designs from multimodal engineering intent.
- G-002: Preserve explicit requirements and design rationale throughout the design history.
- G-003: Compile proposals into deterministic, typed, inspectable engineering artifacts.
- G-004: Support exact B-Rep geometry for released models.
- G-005: Support stable semantic references across routine parameter changes.
- G-006: Make unresolved ambiguity visible before model generation.
- G-007: Make overconstraint, underconstraint, and contradictory constraint states diagnosable.
- G-008: Source commercial and standard components with revisioned provenance.
- G-009: Source dimensions from manufacturer-authoritative or approved standard evidence when possible.
- G-010: Preserve conflicts between sources instead of silently selecting a convenient value.
- G-011: Represent materials with context-dependent properties and constitutive models.
- G-012: Support structural, thermal, fluid, transport, and coupled analyses through governed solver capsules.
- G-013: Support solver authoring and retrieval in an isolated research workflow.
- G-014: Provide a promotion path from experimental solver to qualified solver capsule.
- G-015: Model contamination generation, transport, deposition, retention, and removal.
- G-016: Model cleaning coverage, chemistry, hydraulics, accessibility, and residue risk.
- G-017: Connect simulated results to physical validation plans.
- G-018: Generate an immutable evidence bundle for every controlled result.
- G-019: Support risk-based computerized-system validation.
- G-020: Support French and English user-facing content from the data model upward.
- G-021: Operate on-premises or in a private cloud without requiring external AI calls.
- G-022: Permit useful local operation when external catalog services are unavailable.
- G-023: Remain buildable by a focused engineering team through staged delivery.
- G-024: Establish deterministic evaluation before scaling model training.
- G-025: Earn trust through inspectability and repeatability rather than confidence theater.

### 3.2 Explicit non-goals

- NG-001: The first release will not replace a mature general-purpose CAD workstation for every surface-modeling workflow.
- NG-002: The first release will not support every physics domain.
- NG-003: The first release will not qualify generated solver code automatically.
- NG-004: The first release will not certify material allowables.
- NG-005: The first release will not scrape arbitrary websites in qualified mode.
- NG-006: The first release will not autonomously purchase parts.
- NG-007: The first release will not autonomously release a design.
- NG-008: The first release will not issue legally binding electronic signatures without a configured identity and signature provider.
- NG-009: The first release will not claim cleaning validation from a simulation.
- NG-010: The first release will not claim sterilization validation from a simulation.
- NG-011: The first release will not claim biological safety from material-name matching.
- NG-012: The first release will not infer missing regulatory requirements as facts.
- NG-013: The first release will not allow continuously learning models inside qualified execution.
- NG-014: The first release will not expose arbitrary shell execution to end users.
- NG-015: The first release will not implement microservices solely for organizational fashion.

### 3.3 Product-level success criteria

- SC-001: A reviewer can trace every released scalar input to evidence, a computation, or an explicit assumption.
- SC-002: Recompiling the same canonical input with the same pinned toolchain produces identical authoritative structured output.
- SC-003: Geometry exports remain valid after the supported parameter-perturbation suite.
- SC-004: Unsupported geometry translations fail visibly with a loss report.
- SC-005: Every released simulation includes a declared governing model and applicability statement.
- SC-006: Every released numerical simulation includes solution-verification evidence appropriate to its class.
- SC-007: Every qualified workflow blocks unapproved solver, material, part, and model versions.
- SC-008: Every AI-assisted change is distinguishable from a human-authored or deterministic change.
- SC-009: Every controlled change records actor, reason, before state, after state, and time.
- SC-010: French-language requirements can be entered, reviewed, searched, rendered, and exported without semantic loss.
- SC-011: Numeric parsing remains locale-safe between French and English interfaces.
- SC-012: The first vertical slice completes locally without network access or third-party Python dependencies.
- SC-013: A clean installation can run the test suite from documented commands.
- SC-014: The benchmark reports failure categories, not only an aggregate score.
- SC-015: No release metric implies certainty beyond its measured statistical or evidentiary basis.

---

## 4. Users and governed roles

### 4.1 Primary personas

- The design engineer defines geometry, interfaces, tolerances, and manufacturing intent.
- The simulation engineer defines physics intent, model form, discretization, and credibility evidence.
- The materials engineer approves material identity, property sources, and model applicability.
- The contamination-control engineer defines contamination species, zones, budgets, and transfer mechanisms.
- The cleaning-validation engineer defines cleaning procedures, residues, sampling, and acceptance evidence.
- The manufacturing engineer defines processes, tooling, accessibility, and inspection plans.
- The metrology engineer defines measurement strategy, uncertainty, and conformity rules.
- The quality-assurance reviewer assesses regulated impact, validation status, deviations, and release evidence.
- The system owner owns intended use, configuration, access, lifecycle, and periodic review.
- The process owner owns the business process supported by Contrainte.
- The administrator manages technical configuration without gaining authority to approve engineering content.
- The auditor reads immutable records without altering them.
- The data steward governs catalog and material source packs.
- The solver steward governs solver capsules and their qualification state.
- The AI steward governs model versions, prompts, evaluation, monitoring, and permitted use.

### 4.2 Role separation

- A proposer MAY create or modify a draft.
- A verifier MUST independently check designated critical claims.
- An approver MAY promote an artifact when assigned authority for its scope.
- A system administrator MUST NOT gain approval authority merely through technical privileges.
- A solver author MUST NOT self-approve a solver capsule for qualified use.
- A material-pack importer MUST NOT self-approve an authoritative material pack when segregation is required.
- A model trainer MUST NOT have unrestricted access to held-out qualification test data.
- A quality reviewer MUST be able to reject a promotion without editing the underlying technical content.
- Role assignments MUST be effective-dated.
- Delegations MUST record delegator, delegate, scope, start, expiry, and reason.
- Emergency access MUST be time limited and retrospectively reviewed.
- Read access to controlled intellectual property MUST be independently configurable from approval authority.

### 4.3 Representative use cases

- UC-001: Create a parametric equipment bracket from a French natural-language requirement and a dimensioned sketch.
- UC-002: Identify missing load, interface, and tolerance requirements before geometry generation.
- UC-003: Modify a port diameter while preserving wall-thickness and cleaning-access constraints.
- UC-004: Select a sanitary fitting from an approved manufacturer catalog and retain the exact source revision.
- UC-005: Compare two conflicting supplier drawings without silently merging them.
- UC-006: Select a stainless-steel material state valid for temperature, weld condition, and cleaning chemistry.
- UC-007: Run a linear-static screen and show why the model is or is not applicable.
- UC-008: Escalate from an analytical screen to a nonlinear finite-element analysis.
- UC-009: Couple conjugate heat transfer and structural expansion through approved solver adapters.
- UC-010: Generate a research advection-diffusion solver capsule for a novel contamination mechanism.
- UC-011: Qualify that solver capsule against manufactured solutions, reference data, and review gates.
- UC-012: Identify shadowed regions in a spray-cleaning process.
- UC-013: Compute a conservative residue-risk map using declared recovery and detection assumptions.
- UC-014: Export STEP AP242 with semantic PMI and an export-loss report.
- UC-015: Export an inspection plan through QIF.
- UC-016: Reproduce a released analysis five years later using archived artifacts.
- UC-017: Assess the impact of a supplier part revision on geometry, materials, cleanability, and validated state.
- UC-018: Compare an as-built scan and inspection result to the as-designed model.
- UC-019: Produce a design review package in French while preserving canonical identifiers.
- UC-020: Show an auditor every transformation from source document to released engineering claim.

---

## 5. Architectural invariants

- INV-001: AI output is never authoritative merely because it is fluent or confident.
- INV-002: Deterministic compilation is the boundary between proposal and engineering artifact.
- INV-003: No released numerical claim exists without a unit and quantity kind.
- INV-004: No released external factual claim exists without evidence or an explicit approved assumption.
- INV-005: No released simulation exists without an intended use.
- INV-006: No released simulation exists without declared assumptions.
- INV-007: No released simulation exists without pinned software and model versions.
- INV-008: No qualified execution can access an unapproved network source.
- INV-009: No generated code can execute in qualified mode before solver-capsule qualification.
- INV-010: No visualization mesh can silently replace exact geometry.
- INV-011: No kernel topology identifier can serve as the sole persistent semantic identity.
- INV-012: No source revision can mutate an already released artifact.
- INV-013: No audit event can be updated in place.
- INV-014: No electronic signature can be detached from the meaning and content that was signed.
- INV-015: No approval can survive a content change unless the approval policy explicitly identifies the changed content as non-impacting.
- INV-016: No artifact may represent an unqualified result as qualified.
- INV-017: No aggregate confidence score may hide a failed critical gate.
- INV-018: No property extrapolation may occur without an explicit extrapolation record.
- INV-019: No locale-specific display formatting may alter canonical numeric meaning.
- INV-020: No external source may be treated as current without a retrieval or effective date.
- INV-021: No solver pass may be inferred from process exit code alone.
- INV-022: No contamination limit may be created by the simulator.
- INV-023: No cleaning acceptance limit may be created by the simulator.
- INV-024: No risk control may be considered effective without verification evidence.
- INV-025: Every controlled artifact is content addressed.
- INV-026: Every controlled artifact declares its schema version.
- INV-027: Every derived artifact records its direct inputs.
- INV-028: Every promotion is a new immutable state, not an overwrite.
- INV-029: Every approximation is typed and visible.
- INV-030: Every failure is attributable to a stage and machine-readable reason code.

---

## 6. Operating modes and trust boundaries

### 6.1 Exploration mode

- Exploration mode is the default mode for new ideas and incomplete requirements.
- Exploration mode MAY use hosted or local generative models allowed by project policy.
- Exploration mode MAY query non-approved sources when licensing and access rules permit.
- Exploration mode MAY generate geometry programs, extraction rules, material correlations, and solver code.
- Exploration mode MUST label all outputs `exploratory`.
- Exploration mode MUST display unresolved assumptions.
- Exploration mode MUST display source quality and retrieval status.
- Exploration mode MUST retain AI model identity and generation settings when available.
- Exploration mode MUST prevent electronic release signatures.
- Exploration mode MUST prevent an artifact from being represented as production-approved.
- Exploration mode SHOULD optimize iteration speed while preserving enough provenance for later promotion.
- Exploration mode MAY tolerate nondeterministic proposal generation.
- Exploration mode MUST still use deterministic validators for syntax, units, geometry, and schema.
- Exploration mode MUST sandbox all generated code.
- Exploration mode MUST disable credentials inside generated-code sandboxes.
- Exploration mode output MAY be deleted under ordinary project retention rules unless placed on hold.

### 6.2 Controlled engineering mode

- Controlled engineering mode supports formal design and analysis before regulated qualification.
- Controlled engineering mode MUST use authenticated named users.
- Controlled engineering mode MUST use versioned project configurations.
- Controlled engineering mode MUST use approved or explicitly exceptioned source adapters.
- Controlled engineering mode MUST pin geometry-kernel and solver-capsule versions.
- Controlled engineering mode MUST create append-only audit events for controlled changes.
- Controlled engineering mode MUST require change reasons for designated fields.
- Controlled engineering mode MUST run configured technical review gates.
- Controlled engineering mode MAY accept AI proposals only through the deterministic compiler.
- Controlled engineering mode MUST preserve the proposal-to-artifact transformation record.
- Controlled engineering mode MAY allow unqualified tools if the output remains clearly non-release.
- Controlled engineering mode MUST block promotion while critical evidence gaps remain.
- Controlled engineering mode MUST support independent review.
- Controlled engineering mode MUST support immutable baselines.
- Controlled engineering mode MUST support formal supersession rather than record replacement.

### 6.3 Qualified/GxP mode

- Qualified/GxP mode is an installation-specific configuration, not a universal product badge.
- Qualified/GxP mode MUST be enabled only under an approved intended-use statement.
- Qualified/GxP mode MUST use an approved configuration baseline.
- Qualified/GxP mode MUST use only approved solver capsules.
- Qualified/GxP mode MUST use only approved material packs.
- Qualified/GxP mode MUST use only approved part-source packs or controlled internal masters.
- Qualified/GxP mode MUST use only qualified geometry translators for authoritative exchange.
- Qualified/GxP mode MUST prohibit arbitrary code execution.
- Qualified/GxP mode MUST prohibit live generative AI in the critical calculation and release path.
- Qualified/GxP mode MUST prohibit automatically adapting models.
- Qualified/GxP mode MUST prohibit unpinned probabilistic behavior for critical functions.
- Qualified/GxP mode MUST default to no outbound network access during execution.
- Qualified/GxP mode MUST enforce electronic-signature meaning and reauthentication policy.
- Qualified/GxP mode MUST enforce review and approval workflows defined by the regulated user.
- Qualified/GxP mode MUST enforce retention, backup, restore, and archive policies.
- Qualified/GxP mode MUST produce inspection-ready audit exports.
- Qualified/GxP mode MUST make its exact system configuration retrievable.
- Qualified/GxP mode MUST support periodic review of validated state.
- Qualified/GxP mode MUST send detected integrity failures to the configured incident process.
- Qualified/GxP mode MUST fail closed when policy state cannot be established.

### 6.4 Trust zones

- Zone Z0 contains untrusted external bytes.
- Zone Z0 includes web responses, uploads, email attachments, catalog exports, and generated source code.
- Zone Z1 contains parsed but unverified candidate data.
- Zone Z1 content MUST retain a pointer to the exact Z0 bytes.
- Zone Z2 contains schema-valid proposals.
- Zone Z2 content MUST pass type, unit, reference, and structural validation.
- Zone Z3 contains deterministically compiled engineering artifacts.
- Zone Z3 content MUST be reproducible from declared inputs and toolchain.
- Zone Z4 contains independently reviewed controlled artifacts.
- Zone Z4 content MUST satisfy project review policy.
- Zone Z5 contains released or qualified records under an approved baseline.
- Promotion from Z0 to Z1 requires a parser and malware/content safety gate.
- Promotion from Z1 to Z2 requires schema validation and provenance capture.
- Promotion from Z2 to Z3 requires deterministic compilation and technical checks.
- Promotion from Z3 to Z4 requires configured verification and human review.
- Promotion from Z4 to Z5 requires authorization, signature, and release criteria.
- No promotion may skip a zone without an explicit approved exception workflow.
- Demotion creates a new status event and does not erase the prior state.
- Revocation creates a new event and preserves the revoked content.

### 6.5 Artifact status model

- `draft` identifies mutable authoring state.
- `proposed` identifies a complete candidate awaiting deterministic checks.
- `compiled` identifies a deterministic artifact that passed compiler checks.
- `verified` identifies an artifact with completed technical verification.
- `approved` identifies an artifact approved for a declared scope.
- `released` identifies an immutable deliverable baseline.
- `rejected` identifies a candidate that failed review.
- `superseded` identifies an artifact replaced by a later approved artifact.
- `revoked` identifies an artifact whose prior use authorization has been withdrawn.
- `quarantined` identifies an artifact isolated because integrity or security is uncertain.
- Status transitions MUST be enforced by a policy engine.
- Status transitions MUST record the policy version used.
- Status transitions MUST record unmet and waived criteria.
- A waiver MUST have scope, rationale, owner, approval, and expiry where appropriate.
- Expired waivers MUST automatically block new releases.

---

## 7. System architecture

### 7.1 Architectural style

- The initial product MUST be a modular monolith with isolated workers.
- The initial product MUST avoid distributed transactions.
- The initial product MUST use stable module boundaries that can later become services if evidence justifies it.
- The authoritative core MUST be independent of the web interface.
- The authoritative core MUST be usable through a command-line interface.
- The authoritative core MUST be testable without network access.
- Expensive geometry and solver work MUST execute in workers rather than request processes.
- Worker inputs MUST be immutable manifests.
- Worker outputs MUST be immutable result bundles.
- The orchestrator MUST be retry-safe.
- Pipeline stages MUST be idempotent for the same canonical inputs and toolchain.
- Caches MUST be keyed by canonical input and toolchain digests.
- Cache hits MUST not bypass authorization or release checks.
- Volatile metadata MUST be separated from deterministic scientific content.
- The system MUST expose a complete stage graph for each run.

### 7.2 Logical modules

- The Intent module owns user requirements, ambiguities, assumptions, and acceptance statements.
- The CIR module owns schemas, identifiers, canonicalization, references, and migrations.
- The Constraint module owns dimensional, geometric, logical, and assembly constraints.
- The Geometry module owns feature compilation, B-Rep validation, semantic topology, and exchange.
- The Catalog module owns external part search, retrieval, source snapshots, comparison, and approval.
- The Materials module owns material identity, properties, models, evidence packs, and applicability.
- The Physics module owns physics intent, solver selection, meshes, execution, and result normalization.
- The Solver Forge module owns experimental solver generation, retrieval, tests, packaging, and promotion.
- The Contamination module owns species, sources, transfer, deposition, surface budgets, and evidence.
- The Cleaning module owns cleaning recipes, access, coverage, removal models, sampling plans, and evidence.
- The Evidence module owns claims, sources, provenance edges, uncertainty, signatures, and reports.
- The Quality module owns intended use, risks, traceability, deviations, CAPA links, and validation records.
- The Identity module owns authentication, roles, delegations, and signing identities.
- The Policy module owns mode-specific authorization and promotion decisions.
- The Artifact module owns content-addressed storage, manifests, retention, legal hold, and archive.
- The Workflow module owns long-running orchestration, approvals, retries, and human tasks.
- The Localization module owns terminology, translations, locale-safe presentation, and bilingual exports.
- The Evaluation module owns benchmarks, regression suites, scorecards, and drift monitoring.
- The Interface module owns API, CLI, web application, and integration adapters.

### 7.3 Initial technology choices

- Python 3.12 or later is the initial orchestration and domain-model language.
- Python is selected for scientific ecosystem access and rapid domain iteration.
- Rust MAY be introduced for canonicalization, high-assurance parsing, and performance-critical services after profiling.
- Open CASCADE Technology is the initial exact geometry kernel.
- Python bindings MAY use CadQuery or pythonOCC only behind a Contrainte geometry interface.
- Kernel bindings MUST NOT leak into the CIR schema.
- PostgreSQL is the target transactional metadata store.
- PostgreSQL row-level security SHOULD be evaluated for tenant isolation.
- S3-compatible object storage is the target artifact store.
- A local filesystem artifact store MUST remain supported for development and air-gapped single-node use.
- OCI-compatible registries are the target solver-capsule distribution mechanism.
- React and TypeScript are the target interactive client stack.
- A WebAssembly geometry or visualization component MAY be used only for non-authoritative interaction.
- glTF is the preferred browser visualization format.
- STEP remains the preferred exact neutral geometry exchange format.
- OpenTelemetry is the preferred observability model.
- OpenID Connect is the preferred enterprise authentication protocol.
- An external qualified signature provider SHOULD be supported through a narrow interface.

### 7.4 Deployment profiles

- The developer profile runs the core, CLI, local artifact store, and tests on one workstation.
- The team profile runs the application, PostgreSQL, object storage, and worker pool in a private network.
- The enterprise profile integrates corporate identity, managed keys, backup, monitoring, and controlled registries.
- The air-gapped profile uses offline source packs, material packs, solver packs, and license manifests.
- The GxP profile overlays validated configuration, procedural controls, restricted updates, and evidence retention.
- Deployment profiles MUST share the same canonical artifact semantics.
- Deployment profiles MAY differ in identity, storage, queue, and observability implementations.
- Export between profiles MUST preserve hashes and signatures.
- Import into a more trusted profile MUST pass quarantine and verification.

### 7.5 Execution sequence

- Stage S01 captures user intent and input artifacts.
- Stage S02 classifies inputs and establishes provenance.
- Stage S03 extracts candidate requirements and claims.
- Stage S04 detects ambiguity, missing data, and contradictions.
- Stage S05 creates or edits a CIR proposal.
- Stage S06 validates schema, units, references, and policies.
- Stage S07 solves declarative constraints.
- Stage S08 compiles the feature graph into exact geometry.
- Stage S09 validates B-Rep integrity and semantic topology.
- Stage S10 resolves approved part and material dependencies.
- Stage S11 constructs a physics-intent graph.
- Stage S12 selects an approved solver plan or opens a research gap.
- Stage S13 generates meshes or analytical discretizations.
- Stage S14 executes solver capsules in a sandbox.
- Stage S15 performs solution verification and normalizes results.
- Stage S16 performs contamination and cleaning assessments where scoped.
- Stage S17 evaluates acceptance criteria and uncertainty.
- Stage S18 assembles the evidence graph and trace matrix.
- Stage S19 routes independent review tasks.
- Stage S20 signs and releases an immutable baseline.
- Every stage MUST accept a manifest rather than mutable shared process state.
- Every stage MUST emit a status and structured diagnostics.
- Every stage SHOULD emit partial artifacts useful for diagnosis.
- A failed stage MUST not corrupt prior artifacts.
- A retried stage MUST not duplicate authoritative records.

---

## 8. Contrainte Intermediate Representation

### 8.1 CIR purpose

- CIR is the authoritative semantic representation of a Contrainte design.
- CIR is not a geometry-kernel serialization.
- CIR is not a prompt transcript.
- CIR is not a vendor CAD file.
- CIR is not a simulation input deck.
- CIR can compile into geometry, solver inputs, reports, and exchange files.
- CIR can be reconstructed from a released canonical document and referenced artifacts.
- CIR MUST remain readable without executing untrusted code.
- CIR MUST have an explicit semantic version.
- CIR MUST support forward migrations through reviewed migration functions.
- CIR migrations MUST preserve the source artifact.
- CIR migrations MUST produce a migration report.
- CIR migrations MUST be deterministic.
- CIR migrations MUST be independently tested on released fixtures.

### 8.2 Top-level document

- A CIR document MUST contain `schema_version`.
- A CIR document MUST contain `artifact_id`.
- A CIR document MUST contain `revision`.
- A CIR document MUST contain `status`.
- A CIR document MUST contain `title`.
- A CIR document MUST contain `canonical_language`.
- A CIR document MUST contain `intended_use`.
- A CIR document MUST contain `requirements`.
- A CIR document MUST contain `assumptions`.
- A CIR document MUST contain `parameters`.
- A CIR document MUST contain `constraints`.
- A CIR document MUST contain `feature_graph`.
- A CIR document MUST contain `assembly_graph` when assemblies exist.
- A CIR document MUST contain `materials` when physical properties are used.
- A CIR document MUST contain `parts` when external components are used.
- A CIR document MUST contain `physics_intents` when analysis is requested.
- A CIR document MUST contain `contamination_model` when contamination is in scope.
- A CIR document MUST contain `cleaning_model` when cleaning is in scope.
- A CIR document MUST contain `claims`.
- A CIR document MUST contain `evidence`.
- A CIR document MUST contain `approvals` when controlled promotion has occurred.
- A CIR document MUST contain `extensions` for namespaced experimental data.
- Unknown mandatory fields MUST cause validation failure.
- Unknown optional extension namespaces MUST be preserved even when not interpreted.

### 8.3 Identifiers

- Artifact identifiers MUST be globally unique.
- Semantic entity identifiers MUST remain stable across ordinary revisions.
- Revision identifiers MUST be immutable.
- Requirement identifiers MUST use the `REQ-` namespace.
- Assumption identifiers MUST use the `ASM-` namespace.
- Parameter identifiers MUST use the `PAR-` namespace.
- Constraint identifiers MUST use the `CON-` namespace.
- Feature identifiers MUST use the `FEA-` namespace.
- Assembly occurrence identifiers MUST use the `OCC-` namespace.
- Interface identifiers MUST use the `IFC-` namespace.
- Surface-region identifiers MUST use the `SUR-` namespace.
- Material identifiers MUST use the `MAT-` namespace.
- Part dependency identifiers MUST use the `PRT-` namespace.
- Physics-intent identifiers MUST use the `PHY-` namespace.
- Solver-run identifiers MUST use the `RUN-` namespace.
- Claim identifiers MUST use the `CLM-` namespace.
- Evidence identifiers MUST use the `EVD-` namespace.
- Risk identifiers MUST use the `RSK-` namespace.
- Test identifiers MUST use the `TST-` namespace.
- Approval identifiers MUST use the `APR-` namespace.
- Human-readable IDs MAY coexist with immutable UUIDs.
- Renaming a label MUST NOT change the immutable entity identifier.

### 8.4 Quantities

- A quantity MUST contain an exact decimal lexical value when entered as a decimal.
- A quantity MUST contain a machine-readable unit code.
- A quantity MUST contain a quantity kind such as length, pressure, force, or temperature.
- A quantity MAY contain a display unit distinct from its canonical SI unit.
- A quantity MAY contain standard uncertainty.
- A quantity MAY contain expanded uncertainty and coverage factor.
- A quantity MAY contain asymmetric uncertainty.
- A quantity MAY contain a tolerance interval.
- A quantity MAY contain a probability distribution.
- A quantity MAY contain significant-digit metadata.
- A quantity MAY contain a measurement method reference.
- A quantity MAY contain an environmental condition reference.
- A quantity MUST reject incompatible arithmetic.
- Absolute temperature and temperature difference MUST be distinct quantity kinds.
- Plane angle MUST be explicit even when treated dimensionlessly in numerical libraries.
- Ratios MUST declare numerator and denominator semantics when ambiguity matters.
- Gauge pressure and absolute pressure MUST be distinguishable.
- Mass fraction, mole fraction, and volume fraction MUST be distinguishable.
- Surface concentration and bulk concentration MUST be distinguishable.
- Decimal commas MAY be accepted in French UI input.
- Canonical serialization MUST use locale-independent decimal points.
- Floating-point `NaN` and infinities MUST be forbidden in canonical CIR.

### 8.5 Claims

- A claim represents an assertion about an entity or relationship.
- A claim MUST identify its subject.
- A claim MUST identify its predicate.
- A claim MUST contain a value or object reference.
- A claim MUST declare a basis.
- Supported bases MUST include `observed`.
- Supported bases MUST include `measured`.
- Supported bases MUST include `supplier_declared`.
- Supported bases MUST include `standard_specified`.
- Supported bases MUST include `computed`.
- Supported bases MUST include `critically_evaluated`.
- Supported bases MUST include `predicted`.
- Supported bases MUST include `inferred`.
- Supported bases MUST include `assumed`.
- Supported bases MUST include `ai_proposed`.
- A claim MUST declare its status.
- A claim MUST reference supporting evidence or an approved assumption.
- A computed claim MUST reference the producing run.
- A derived claim MUST reference its parent claims.
- A claim MAY identify counter-evidence.
- A claim MAY identify a confidence interval.
- A claim MAY identify an evidence grade.
- A claim MUST declare its applicability envelope where context affects validity.
- Claim applicability MAY include temperature.
- Claim applicability MAY include pressure.
- Claim applicability MAY include humidity.
- Claim applicability MAY include chemical environment.
- Claim applicability MAY include loading rate.
- Claim applicability MAY include material orientation.
- Claim applicability MAY include product form.
- Claim applicability MAY include manufacturing route.
- Claim applicability MAY include regulatory jurisdiction.
- An AI proposal MUST never silently change its basis to measured or verified.

### 8.6 Evidence references

- An evidence reference MUST identify its evidence type.
- Evidence types MUST include source document.
- Evidence types MUST include web resource snapshot.
- Evidence types MUST include database record.
- Evidence types MUST include test record.
- Evidence types MUST include certificate.
- Evidence types MUST include standard.
- Evidence types MUST include supplier declaration.
- Evidence types MUST include inspection result.
- Evidence types MUST include solver result.
- Evidence types MUST include human rationale.
- Evidence types MUST include source code.
- An evidence reference MUST identify its locator.
- An evidence reference MUST include a content digest when content is retrievable.
- An evidence reference MUST include a retrieval timestamp for external sources.
- An evidence reference SHOULD include an effective or publication date.
- An evidence reference SHOULD include a revision or edition.
- An evidence reference SHOULD include an issuing authority.
- An evidence reference SHOULD include a title.
- An evidence reference SHOULD include a language.
- An evidence reference SHOULD include licensing metadata.
- A document extraction SHOULD include page and bounding-box coordinates.
- A table extraction SHOULD include row, column, and header context.
- An image extraction SHOULD include region coordinates and OCR confidence.
- Evidence content MUST remain immutable after use in a released artifact.
- A later source retrieval creates new evidence rather than mutating old evidence.

### 8.7 Provenance graph

- Provenance MUST model entities, activities, and agents in a W3C PROV-compatible shape.
- A source snapshot is an entity.
- A CIR revision is an entity.
- A geometry build is an activity.
- A solver execution is an activity.
- A human reviewer is an agent.
- An AI model service is an agent with a recorded model version.
- A deterministic compiler is an agent with a recorded build digest.
- `wasDerivedFrom` MUST connect derived artifacts to inputs.
- `wasGeneratedBy` MUST connect artifacts to activities.
- `wasAssociatedWith` MUST connect activities to accountable agents.
- `used` MUST connect activities to all material inputs.
- Provenance export SHOULD support PROV-JSON or JSON-LD.
- The internal model MAY be narrower than full PROV-O.
- Internal provenance MUST preserve enough information for lossless export of supported concepts.

### 8.8 Canonicalization and hashing

- Canonical authoritative JSON SHOULD conform to RFC 8785.
- Large exact decimals that cannot round-trip through I-JSON number rules MUST be encoded as typed strings.
- Canonicalization MUST normalize object-key ordering.
- Canonicalization MUST preserve array order where order is semantic.
- Canonicalization MUST reject duplicate object keys.
- Canonicalization MUST use UTF-8.
- Canonicalization MUST not include presentation whitespace.
- Canonicalization MUST not include transient database identifiers.
- Canonicalization MUST not include wall-clock generation time unless time is a declared scientific input.
- Artifact digests MUST use SHA-256 initially.
- The digest algorithm MUST be included with the digest.
- Hash agility MUST be supported by schema design.
- A manifest MUST list the digest of every direct artifact.
- A Merkle-style root MAY summarize a result bundle.
- Signatures MUST cover canonical content and signature meaning.
- A timestamp token MAY be attached without changing the underlying artifact digest.

### 8.9 Requirements and traceability

- A requirement MUST have a unique identifier.
- A requirement MUST have normative text.
- A requirement MUST have an owner.
- A requirement MUST have a source.
- A requirement MUST have a criticality.
- A requirement MUST have a verification method.
- A requirement SHOULD have rationale.
- A requirement MAY have localized renderings.
- A localized rendering MUST reference the same canonical requirement identity.
- A requirement MAY decompose into child requirements.
- A requirement MAY conflict with another requirement only while draft.
- A controlled baseline MUST resolve or formally waive detected conflicts.
- Trace links MUST connect requirements to design entities.
- Trace links MUST connect requirements to risk controls.
- Trace links MUST connect requirements to tests or analyses.
- Trace links MUST connect requirements to results.
- Trace links MUST connect requirements to approvals.
- Orphan released requirements MUST fail the traceability gate unless justified.
- Orphan tests MUST be reported because they may indicate undocumented requirements.
- Trace coverage MUST be reported by criticality, not only as one percentage.

### 8.10 Assumptions and decisions

- An assumption MUST have an identifier.
- An assumption MUST have an owner.
- An assumption MUST have a rationale.
- An assumption MUST have an impact statement.
- An assumption MUST have a verification or retirement plan.
- An assumption MUST have a status.
- A critical open assumption MUST block release unless formally accepted.
- A decision record MUST list considered alternatives.
- A decision record MUST list selection criteria.
- A decision record MUST list consequences.
- A decision record MUST link to the evidence available at decision time.
- Superseding a decision MUST preserve the original rationale.

---

## 9. Intent acquisition and AI subsystem

### 9.1 Input classes

- The system MUST accept structured CIR input.
- The system MUST accept plain-language requirements.
- The system MUST accept French and English requirements.
- The system SHOULD accept mixed French and English technical terminology.
- The system SHOULD accept raster sketches.
- The system SHOULD accept vector drawings.
- The system SHOULD accept PDF drawings and specifications.
- The system SHOULD accept STEP and related CAD exchange files.
- The system SHOULD accept supplier catalog tables.
- The system SHOULD accept spreadsheet parameter tables.
- The system SHOULD accept point clouds and meshes as reference geometry.
- The system SHOULD accept inspection results.
- The system MAY accept photographs as contextual evidence.
- The system MUST classify each input by trust zone before processing.
- The system MUST retain original input bytes.
- The system MUST compute a digest before parsing.
- The system MUST scan uploaded active content before opening it in a privileged process.

### 9.2 Requirement extraction

- Requirement extraction MUST produce candidates rather than silently modifying controlled requirements.
- Each extracted candidate MUST cite its source region.
- Each extracted candidate MUST preserve the source language.
- Each extracted numeric expression MUST preserve the original lexical text.
- The parser MUST distinguish decimal commas from list punctuation using locale and syntax context.
- The parser MUST distinguish nominal values from limits.
- The parser MUST distinguish symmetric and asymmetric tolerances.
- The parser MUST distinguish minimum, maximum, target, and reference dimensions.
- The parser MUST distinguish requirements from explanatory statements.
- The parser MUST distinguish external obligations from design preferences.
- The parser MUST flag modal ambiguity such as should versus shall.
- The parser MUST identify unresolved pronouns and spatial references.
- The parser MUST identify missing units.
- The parser MUST identify mixed-unit requirements.
- The parser MUST identify contradictory bounds.
- The parser MUST identify impossible tolerance stacks where determinable.
- The parser SHOULD propose a normalized technical translation for review.
- Translation MUST NOT replace the original text.
- Approved translations MUST record the reviewer and terminology version.

### 9.3 Ambiguity protocol

- The AI subsystem MUST produce an ambiguity ledger.
- Each ambiguity MUST identify affected entities and downstream consequences.
- Each ambiguity MUST propose at least one precise resolution when feasible.
- The system MUST prioritize questions by expected reduction in design risk.
- The system SHOULD batch independent low-risk questions.
- The system SHOULD avoid asking questions answerable from approved project context.
- The system MUST not fabricate an answer to avoid a user question.
- The system MAY use an explicit conservative assumption when project policy permits.
- A conservative assumption MUST state what makes it conservative.
- A conservative assumption MUST be re-evaluated when interacting failure modes exist.
- A conservative geometric assumption is not necessarily conservative for cleaning or flow.
- A conservative stiffness assumption is not necessarily conservative for thermal stress.
- The ambiguity ledger MUST survive into review evidence.

### 9.4 Proposal generation

- AI proposal output MUST target a versioned proposal schema.
- AI proposal output MUST not contain executable free-form code as the primary geometry representation.
- AI MAY select operations from an approved feature vocabulary.
- AI MAY propose parameters and symbolic expressions.
- AI MAY propose constraint relationships.
- AI MAY propose semantic selections by role rather than transient topology index.
- AI MAY propose catalog queries.
- AI MAY propose material candidates.
- AI MAY propose physics intents.
- AI MAY propose solver-capsule requirements.
- AI MAY propose contamination pathways.
- AI MAY propose cleaning-risk regions.
- AI MUST state evidence gaps.
- AI MUST state assumptions.
- AI MUST not relabel its own proposal as verified.
- Proposal sampling parameters MUST be recorded when technically available.
- Hosted model requests MUST follow project data-classification rules.
- Sensitive model inputs MUST be redacted or kept local according to policy.

### 9.5 Model registry

- Every AI model MUST have a model-registry record.
- The record MUST identify provider.
- The record MUST identify model and immutable version when available.
- The record MUST identify deployment endpoint class.
- The record MUST identify input and output data policy.
- The record MUST identify intended uses.
- The record MUST identify prohibited uses.
- The record MUST identify benchmark results.
- The record MUST identify known limitations.
- The record MUST identify context-window and modality limits.
- The record MUST identify retirement status.
- A prompt template MUST be versioned independently of the model.
- Retrieval configuration MUST be versioned independently of the model.
- Tool schemas MUST be versioned independently of the model.
- A model change MUST trigger impact assessment for affected intended uses.
- A silent provider-side model change MUST cause controlled-mode quarantine when version pinning is unavailable.

### 9.6 AI evaluation

- AI evaluation MUST use held-out artifacts unavailable during prompt and model development.
- AI evaluation MUST separate geometry validity from requirement satisfaction.
- AI evaluation MUST separate exact numeric accuracy from semantic adequacy.
- AI evaluation MUST separate part-family familiarity from generalization.
- AI evaluation MUST include French-only inputs.
- AI evaluation MUST include bilingual mixed-terminology inputs.
- AI evaluation MUST include adversarially ambiguous drawings.
- AI evaluation MUST include source conflicts.
- AI evaluation MUST include missing information.
- AI evaluation MUST measure appropriate abstention.
- AI evaluation MUST measure unsupported-claim rate.
- AI evaluation MUST measure critical omission rate.
- AI evaluation MUST measure constraint recovery.
- AI evaluation MUST measure edit stability under parameter changes.
- AI evaluation MUST report subgroup performance.
- Aggregate performance MUST not hide a failed safety-critical subgroup.
- Model promotion MUST use acceptance criteria approved before final testing.
- Test-set access MUST be logged.
- Repeated test-set use MUST be disclosed.

---

## 10. Constraint and geometry system

### 10.1 Constraint vocabulary

- The constraint engine MUST support scalar equality.
- The constraint engine MUST support scalar inequality.
- The constraint engine MUST support closed and open intervals.
- The constraint engine MUST support symbolic expressions.
- The constraint engine MUST support dimensional consistency.
- The constraint engine MUST support coincidence.
- The constraint engine MUST support collinearity.
- The constraint engine MUST support parallelism.
- The constraint engine MUST support perpendicularity.
- The constraint engine MUST support tangency.
- The constraint engine MUST support concentricity.
- The constraint engine MUST support symmetry.
- The constraint engine MUST support fixed distance.
- The constraint engine MUST support fixed angle.
- The constraint engine MUST support equal length.
- The constraint engine MUST support equal radius.
- The constraint engine MUST support horizontal and vertical sketch constraints.
- The constraint engine MUST support assembly mate constraints.
- The constraint engine MUST support axis alignment.
- The constraint engine MUST support planar offset.
- The constraint engine MUST support joint limits.
- The constraint engine MUST support clearance and interference bounds.
- The constraint engine MUST support tolerance-stack expressions.
- The constraint engine SHOULD support logical implication.
- The constraint engine SHOULD support conditional configuration constraints.
- The constraint engine SHOULD support optimization objectives separately from hard constraints.

### 10.2 Constraint diagnostics

- The solver MUST report remaining degrees of freedom.
- The solver MUST report redundant constraints.
- The solver MUST report inconsistent constraints.
- The solver SHOULD compute a minimal or near-minimal unsatisfiable subset.
- The solver MUST distinguish numerical failure from logical inconsistency.
- The solver MUST record convergence tolerances.
- The solver MUST record initial conditions when they affect the solution.
- The solver MUST provide deterministic ordering for equivalent solutions where possible.
- Symmetric solution branches MUST remain explicit when engineering meaning differs.
- Automatically removed redundancy MUST be reported.
- Constraint relaxation MUST require explicit authorization.
- A relaxed constraint MUST remain visible in the evidence graph.
- Constraint satisfaction MUST be re-evaluated after every geometry build.
- Constraint diagnostics MUST reference user-facing semantic entities.

### 10.3 Feature graph

- The feature graph MUST be a directed acyclic graph for ordinary feature dependencies.
- Cyclic design equations MUST be represented in a dedicated solve group.
- Each feature MUST have a stable identifier.
- Each feature MUST have a type from a versioned vocabulary.
- Each feature MUST reference typed inputs.
- Each feature MUST declare expected outputs.
- Each feature MUST declare failure conditions.
- Each feature MUST preserve construction rationale when supplied.
- Supported initial features MUST include datum plane.
- Supported initial features MUST include datum axis.
- Supported initial features MUST include datum coordinate system.
- Supported initial features MUST include 2D sketch.
- Supported initial features MUST include extrusion.
- Supported initial features MUST include revolution.
- Supported initial features MUST include additive boolean.
- Supported initial features MUST include subtractive boolean.
- Supported initial features MUST include intersection.
- Supported initial features MUST include hole.
- Supported initial features MUST include fillet.
- Supported initial features MUST include chamfer.
- Supported later features SHOULD include sweep.
- Supported later features SHOULD include loft.
- Supported later features SHOULD include shell.
- Supported later features SHOULD include draft.
- Supported later features SHOULD include linear pattern.
- Supported later features SHOULD include polar pattern.
- Supported later features SHOULD include mirror.
- Supported later features SHOULD include thread semantics.
- Supported later features SHOULD include sheet-metal operations.
- Supported later features MAY include freeform surface operations.

### 10.4 Exact geometry compilation

- Feature compilation MUST execute against a pinned OCCT build.
- Compiler inputs MUST be canonical CIR fragments.
- Compiler outputs MUST include exact B-Rep.
- Compiler outputs MUST include a semantic entity map.
- Compiler outputs MUST include geometry diagnostics.
- Compiler outputs MUST include mass-property readiness status.
- Compiler outputs MUST include kernel tolerance metadata.
- Compiler outputs MUST include a build manifest.
- Boolean operations MUST be checked for failure, invalidity, and unexpected body counts.
- Fillet and chamfer operations MUST report partial success as failure unless policy explicitly permits partial behavior.
- Small-edge and sliver-face creation MUST be detected against project thresholds.
- Self-intersection MUST be detected.
- Non-manifold topology MUST be rejected for solid bodies unless intentionally modeled.
- Open shells MUST be rejected where a solid is required.
- Body orientation MUST be checked.
- Geometry healing MUST never occur silently.
- Geometry healing MUST create a report of modifications.
- Healing beyond approved tolerances MUST require review.
- Compiler logs MUST not be the sole geometry evidence.

### 10.5 Persistent semantic topology

- Semantic references MUST describe engineering role rather than topology order.
- A port bore surface MAY be referenced by the port feature and cylindrical-role selector.
- A mounting face MAY be referenced by datum relationship and feature ancestry.
- A load region MAY be defined through semantic tags or robust geometric predicates.
- A cleaning-critical surface MUST remain identifiable after ordinary dimension edits.
- Entity matching MUST use feature ancestry.
- Entity matching SHOULD use geometry type.
- Entity matching SHOULD use adjacency signatures.
- Entity matching SHOULD use orientation and relative position.
- Entity matching SHOULD use invariant geometric properties.
- Entity matching MAY use learned ranking only as a proposal.
- Ambiguous matches MUST block dependent controlled operations.
- Broken references MUST not be silently rebound.
- Rebinding MUST record old candidates, new candidate, method, and reviewer where required.
- Persistent naming performance MUST be part of the benchmark suite.

### 10.6 Sketch solving

- Sketch entities MUST include point.
- Sketch entities MUST include line segment.
- Sketch entities MUST include circle.
- Sketch entities MUST include circular arc.
- Sketch entities SHOULD include ellipse.
- Sketch entities SHOULD include elliptical arc.
- Sketch entities SHOULD include B-spline with explicit degree and knots.
- Construction geometry MUST be distinct from profile geometry.
- Closed-profile detection MUST be deterministic.
- Profile winding MUST be normalized.
- Duplicate and near-duplicate entities MUST be diagnosed.
- Zero-length entities MUST be rejected.
- Degenerate arcs MUST be rejected or normalized with an explicit report.
- Solver tolerance MUST scale appropriately with declared model scale.
- Sketch solution MUST expose degrees of freedom.
- Fully constrained status MUST not be inferred from visual immobility.

### 10.7 Assemblies and joints

- An assembly MUST distinguish part definition from part occurrence.
- Multiple occurrences MAY reference one part revision.
- Each occurrence MUST have a stable identifier.
- Each occurrence MUST have a transform.
- Each occurrence MAY have configuration overrides allowed by the part definition.
- Assembly constraints MUST reference semantic interfaces.
- Supported joints MUST include rigid.
- Supported joints MUST include revolute.
- Supported joints MUST include prismatic.
- Supported joints SHOULD include cylindrical.
- Supported joints SHOULD include spherical.
- Supported joints SHOULD include planar.
- Supported joints SHOULD include screw.
- Joint limits MUST carry units and evidence.
- Assembly solving MUST report unconstrained motion.
- Assembly solving MUST report overconstraint.
- Static interference MUST be checked.
- Motion-envelope interference SHOULD be checked.
- Assembly mass properties MUST include occurrence transforms.
- Purchased subassemblies MAY be represented as black boxes with declared interfaces.

### 10.8 PMI, tolerances, and surface semantics

- Dimensions MUST reference semantic geometry.
- Tolerances MUST identify governing standard and interpretation context.
- Datum systems MUST be explicit.
- Feature-control frames MUST be structured data rather than display text.
- Surface texture requirements MUST be structured where supported.
- Weld symbols SHOULD be structured where supported.
- Material and process notes MUST be linked to affected entities.
- General tolerances MUST not override explicit tolerances.
- Conflicting tolerance rules MUST be diagnosed.
- Basic dimensions MUST remain distinguishable from toleranced dimensions.
- Reference dimensions MUST remain non-authoritative where standards prescribe.
- Inspection characteristics MUST be derivable from released PMI.
- PMI export MUST include a conformance and loss report.
- Visual annotation placement MUST not change semantic meaning.

### 10.9 Geometry exchange

- STEP AP242 is the preferred exact release exchange.
- STEP import MUST retain the exact input artifact.
- STEP import MUST record translator version and settings.
- STEP import MUST record validation properties when present.
- STEP import MUST attempt to retain names, colors, layers, materials, and PMI where supported.
- STEP import MUST report unsupported entities.
- STEP export MUST compute validation properties for comparison.
- STEP round-trip tests MUST compare topology, geometry, mass properties, and PMI coverage.
- Parasolid support MAY be implemented only when licensing permits.
- IGES MAY be supported as a legacy surface exchange with warnings.
- STL MUST be treated as tessellated manufacturing or visualization data, not exact product definition.
- glTF MUST be treated as visualization data.
- Mesh import MUST not create fabricated parametric history without marking it as inferred.
- Reverse-engineered features MUST retain fit residuals and uncertainty.

### 10.10 Geometry acceptance gates

- A release solid MUST pass kernel validity checks.
- A release solid MUST satisfy required body count.
- A release solid MUST satisfy dimensional requirements within declared calculation tolerance.
- A release solid MUST satisfy volume and mass-property sanity checks.
- A release solid MUST satisfy minimum-feature rules for selected manufacturing processes where scoped.
- A release model MUST pass the configured parameter-perturbation suite.
- A release model MUST preserve critical semantic references under configured perturbations.
- A release assembly MUST pass static interference checks unless waived.
- A release export MUST pass format conformance checks available to the implementation.
- A release export MUST include a translation-loss statement.

---

## 11. Parts, dimensions, and sourcing

### 11.1 Source hierarchy

- Source tier A contains signed or controlled internal engineering masters.
- Source tier B contains current manufacturer-controlled product data.
- Source tier C contains applicable published standards and specifications.
- Source tier D contains manufacturer-authorized catalog platforms.
- Source tier E contains authorized distributors reproducing manufacturer data.
- Source tier F contains qualified third-party databases.
- Source tier G contains unqualified third-party data.
- Source tier H contains AI inference or geometric measurement from a model.
- A lower alphabetical tier is preferred only when applicability and currency are equal.
- Source tier alone MUST NOT override an applicability mismatch.
- A manufacturer CAD model MUST not outrank a newer manufacturer drawing without conflict review.
- A standard nominal dimension MUST not overwrite a product-specific deviation.
- AI-inferred dimensions MUST never silently fill controlled part masters.

### 11.2 Source adapter contract

- A source adapter MUST declare source identity.
- A source adapter MUST declare authentication method.
- A source adapter MUST declare license and permitted-use constraints.
- A source adapter MUST declare rate limits.
- A source adapter MUST declare supported locales.
- A source adapter MUST declare retrieval endpoints.
- A source adapter MUST return original source references.
- A source adapter MUST return retrieval timestamp.
- A source adapter MUST return manufacturer identity when available.
- A source adapter MUST return part number and configuration.
- A source adapter MUST return revision or publication date when available.
- A source adapter MUST return units exactly as supplied.
- A source adapter MUST return a content digest for downloaded artifacts.
- A source adapter MUST distinguish search result from authoritative selection.
- A source adapter MUST surface partial failures.
- A source adapter MUST not bypass website terms or technical access controls.
- A source adapter MUST support a record-only dry run for qualification testing.
- Adapter behavior MUST be covered by contract fixtures.

### 11.3 Candidate part model

- A candidate part MUST have a manufacturer.
- A candidate part MUST have a manufacturer part number.
- A candidate part MUST have a configuration key.
- A candidate part MUST have lifecycle status when known.
- A candidate part MUST have source evidence.
- A candidate part SHOULD have manufacturer name normalization.
- A candidate part SHOULD have alternates and supersession links.
- A candidate part SHOULD have lead-time evidence separated from engineering definition.
- A candidate part SHOULD have regulatory declarations where relevant.
- A candidate part SHOULD have material declarations where relevant.
- A candidate part SHOULD have exact geometry or a declared simplification level.
- A candidate part SHOULD have mating interfaces.
- A candidate part SHOULD have envelope dimensions.
- A candidate part SHOULD have mass and center of gravity.
- A candidate part MAY have cost, but cost MUST be time-stamped and non-authoritative for geometry.

### 11.4 Dimension extraction

- Every extracted dimension MUST cite its source region.
- Every extracted dimension MUST preserve original text.
- Every extracted dimension MUST identify nominal, minimum, maximum, or reference status.
- Every extracted dimension MUST identify unit.
- Every extracted tolerance MUST preserve tolerance form.
- OCR confidence MUST be stored separately from engineering confidence.
- Table headers MUST be bound to row values before candidate creation.
- Ditto marks and merged cells MUST be resolved explicitly.
- Footnotes MUST remain associated with affected values.
- Drawing scale MUST not be used to infer a dimension when an explicit dimension exists.
- Pixel measurement MAY produce an inferred candidate only.
- Geometry measurement MAY produce an inferred candidate only unless the model is the approved master.
- Dimension comparison MUST normalize units without discarding original units.
- Conflicting candidates MUST remain separate until adjudicated.

### 11.5 Part verification

- Part verification MUST compare identifiers across sources.
- Part verification MUST compare revision dates.
- Part verification MUST compare configured options.
- Part verification MUST compare critical dimensions.
- Part verification MUST compare interface geometry.
- Part verification MUST compare material declarations.
- Part verification MUST compare mass when available.
- Part verification MUST compare regulatory or conformity declarations when scoped.
- Part verification MUST check lifecycle status.
- Part verification MUST check whether the source artifact is a simplified model.
- A critical dimension SHOULD require two concordant sources or one designated authoritative source.
- Source disagreement MUST create a review task.
- A reviewer decision MUST explain selection and rejected evidence.
- Approved part masters MUST be immutable revisions.

### 11.6 Part dependency management

- A selected part MUST be pinned by manufacturer, part number, configuration, and source revision.
- A selected part MUST be pinned by artifact digest when files are included.
- A selected part MUST declare approved usage scope.
- A selected part MUST declare whether substitution is allowed.
- A selected part MUST declare critical characteristics.
- A later catalog update MUST not alter existing design baselines.
- A later catalog update SHOULD trigger an impact notification.
- Supersession analysis MUST identify affected assemblies.
- Supersession analysis MUST identify affected interfaces.
- Supersession analysis MUST identify affected simulations.
- Supersession analysis MUST identify affected cleaning and contamination assessments.
- Supersession analysis MUST identify affected validation evidence.
- Supplier availability data MUST be cached separately from controlled engineering definition.

---

## 12. Materials system

### 12.1 Material identity

- A material identity MUST be more specific than a colloquial material name.
- A material identity MUST include material class.
- A material identity SHOULD include specification and grade.
- A material identity SHOULD include composition limits.
- A material identity SHOULD include product form.
- A material identity SHOULD include temper or heat-treatment condition.
- A material identity SHOULD include manufacturing route.
- A material identity SHOULD include processing history relevant to properties.
- A material identity SHOULD include orientation or anisotropy axes.
- A material identity SHOULD include surface treatment.
- A material identity SHOULD include coating system.
- A material identity MAY include heat, lot, or batch identity.
- A material identity MAY include supplier.
- A material identity MAY include certificate references.
- Two materials with the same nominal grade but different applicable state MUST remain distinct identities.

### 12.2 Property record

- A material property MUST identify quantity kind.
- A material property MUST contain value, function, tensor, interval, or distribution.
- A material property MUST contain units.
- A material property MUST contain evidence basis.
- A material property MUST contain applicability.
- A material property SHOULD contain uncertainty.
- A material property SHOULD contain test method.
- A material property SHOULD contain specimen orientation.
- A material property SHOULD contain sample count when statistically derived.
- A material property SHOULD contain statistical basis such as A-basis or B-basis where applicable.
- A material property SHOULD contain temperature dependence.
- A material property SHOULD contain strain-rate dependence where relevant.
- A material property SHOULD contain humidity or conditioning dependence where relevant.
- A material property SHOULD contain aging dependence where relevant.
- A material property SHOULD contain chemical-environment dependence where relevant.
- A scalar approximation of tensor data MUST be labeled as a model reduction.
- Interpolation MUST identify method and bracketing points.
- Extrapolation MUST identify distance outside source domain.
- Extrapolation beyond policy limits MUST be blocked.

### 12.3 Evidence grading

- Grade M0 denotes an unsupported or AI-proposed value.
- Grade M1 denotes an unreviewed third-party value.
- Grade M2 denotes a traceable computational prediction without application validation.
- Grade M3 denotes a traceable experimental publication or supplier value with method context.
- Grade M4 denotes critically evaluated data with uncertainty or a qualified internal test dataset.
- Grade M5 denotes an approved design allowable or batch-specific certificate accepted for the declared use.
- Evidence grade MUST be independent of whether the numerical value looks plausible.
- Evidence grade MUST be independent of source popularity.
- A high evidence grade MUST not compensate for an applicability mismatch.
- Project policy MUST define minimum grade by property and decision type.
- Screening analysis MAY use lower grades with visible margins and restrictions.
- Release analysis MUST satisfy configured grade requirements.

### 12.4 Supported property families

- The material system MUST support density.
- The material system MUST support elastic modulus.
- The material system MUST support Poisson ratio.
- The material system MUST support shear modulus.
- The material system MUST support yield strength.
- The material system MUST support ultimate strength.
- The material system MUST support elongation.
- The material system MUST support fracture toughness.
- The material system MUST support fatigue data.
- The material system MUST support creep data.
- The material system MUST support thermal conductivity.
- The material system MUST support heat capacity.
- The material system MUST support thermal expansion.
- The material system MUST support emissivity.
- The material system MUST support electrical conductivity.
- The material system MUST support permeability.
- The material system MUST support diffusivity.
- The material system MUST support solubility.
- The material system MUST support partition coefficients.
- The material system MUST support adsorption and desorption parameters.
- The material system MUST support outgassing metrics.
- The material system MUST support corrosion compatibility.
- The material system MUST support cleaning-agent compatibility.
- The material system SHOULD support surface energy and wettability.
- The material system SHOULD support roughness-dependent behavior.
- The material system SHOULD support microbial adhesion evidence.

### 12.5 Constitutive-model registry

- A constitutive model MUST have a stable identifier.
- A constitutive model MUST identify governing equations.
- A constitutive model MUST identify required parameters.
- A constitutive model MUST identify state variables.
- A constitutive model MUST identify valid material classes.
- A constitutive model MUST identify valid loading regimes.
- A constitutive model MUST identify calibration evidence.
- A constitutive model MUST identify validation evidence.
- A constitutive model MUST identify implementation capsules.
- A constitutive model MUST identify known limitations.
- The registry MUST initially support isotropic linear elasticity.
- The registry SHOULD support orthotropic elasticity.
- The registry SHOULD support elastoplasticity with declared hardening laws.
- The registry SHOULD support hyperelasticity.
- The registry SHOULD support linear and nonlinear viscoelasticity.
- The registry SHOULD support creep.
- The registry SHOULD support fatigue life and crack-growth models.
- The registry SHOULD support cohesive-zone models.
- The registry SHOULD support continuum damage models.
- The registry MAY support phase-field fracture.
- The registry MAY support peridynamics.
- The registry SHOULD support Fourier and anisotropic heat conduction.
- The registry SHOULD support Fickian and non-Fickian diffusion.
- The registry SHOULD support sorption kinetics.
- The registry SHOULD support reaction and degradation kinetics.

### 12.6 Material selection

- Material selection MUST begin with functional and environmental requirements.
- Material selection MUST include manufacturing-process compatibility.
- Material selection MUST include joining compatibility.
- Material selection MUST include cleaning compatibility when in scope.
- Material selection MUST include contamination contribution when in scope.
- Material selection MUST include regulatory and biocompatibility constraints when in scope.
- Material selection MUST include availability of applicable property evidence.
- Material selection SHOULD include lifecycle and obsolescence risk.
- Material selection SHOULD include inspectability.
- Material selection SHOULD include repairability.
- Material selection SHOULD include sustainability only with declared metrics and boundaries.
- Ranking weights MUST be explicit.
- Hard exclusions MUST remain separate from ranking preferences.
- AI MAY explain tradeoffs but MUST not fabricate missing evidence.
- Final selection MUST record why rejected candidates were rejected when decision criticality requires it.

### 12.7 Material packs

- A material pack is an immutable, versioned collection of material records and evidence.
- A material pack MUST declare schema version.
- A material pack MUST declare issuer.
- A material pack MUST declare scope.
- A material pack MUST declare source licenses.
- A material pack MUST declare compilation method.
- A material pack MUST declare effective date.
- A material pack MUST declare content digest.
- A qualified material pack MUST declare verification status.
- A qualified material pack MUST declare applicable intended uses.
- A pack update MUST create a new version.
- Material-pack diffs MUST distinguish data changes from metadata changes.
- Material-pack promotion MUST require a data-steward review.
- Restricted source content MUST not be redistributed beyond its license.

---

## 13. Physics intent and solver system

### 13.1 Physics intent

- A physics intent defines the engineering question before selecting software.
- A physics intent MUST identify the decision it supports.
- A physics intent MUST identify target outputs.
- A physics intent MUST identify acceptance criteria or explain why it is exploratory.
- A physics intent MUST identify modeled bodies and regions.
- A physics intent MUST identify excluded bodies and simplifications.
- A physics intent MUST identify physical domains.
- A physics intent MUST identify time character as steady, transient, cyclic, or stochastic.
- A physics intent MUST identify expected nonlinearities.
- A physics intent MUST identify relevant scales.
- A physics intent MUST identify loads and boundary conditions.
- A physics intent MUST identify initial conditions when relevant.
- A physics intent MUST identify interfaces and coupling.
- A physics intent MUST identify material model requirements.
- A physics intent MUST identify expected failure modes.
- A physics intent MUST identify uncertainty sources.
- A physics intent MUST identify validation evidence available or planned.
- A physics intent MUST identify model-form alternatives considered for critical analyses.
- Physics intent review MUST precede expensive release-grade execution.

### 13.2 Physics domains

- The platform MUST support analytical solid-mechanics screens first.
- The platform SHOULD support linear static solid mechanics.
- The platform SHOULD support modal analysis.
- The platform SHOULD support transient structural dynamics.
- The platform SHOULD support contact mechanics.
- The platform SHOULD support geometric nonlinearity.
- The platform SHOULD support material nonlinearity.
- The platform SHOULD support fracture mechanics.
- The platform SHOULD support fatigue and durability.
- The platform SHOULD support steady heat conduction.
- The platform SHOULD support transient heat transfer.
- The platform SHOULD support convection and radiation boundary models.
- The platform SHOULD support incompressible flow.
- The platform SHOULD support compressible flow where qualified.
- The platform SHOULD support laminar and turbulence-model workflows.
- The platform SHOULD support species transport.
- The platform SHOULD support particle transport.
- The platform SHOULD support conjugate heat transfer.
- The platform SHOULD support fluid-structure interaction through coupling.
- The platform SHOULD support thermo-mechanical coupling.
- The platform MAY support electromagnetics.
- The platform MAY support acoustics.
- The platform MAY support chemical reaction networks.
- The platform MAY support population-balance models.
- The platform MUST not expose an unsupported domain as available merely because a general PDE engine can express it.

### 13.3 Applicability rules

- Applicability rules MUST map physics intent to candidate model forms.
- Applicability rules MUST be versioned.
- Applicability rules MUST cite governing references or approved engineering rationale.
- Applicability rules MUST identify necessary dimensionless groups where relevant.
- Beam theory selection MUST consider slenderness and local stress needs.
- Shell theory selection MUST consider thickness-to-curvature and through-thickness effects.
- Linear elasticity selection MUST consider strain, material behavior, contact, and geometric change.
- Steady-state selection MUST compare process and response time scales.
- Incompressible-flow selection MUST consider Mach number and density variation.
- Turbulence-model selection MUST consider Reynolds number, wall treatment, separation, and target quantities.
- Continuum assumptions MUST consider Knudsen number where rarefaction matters.
- Diffusion-model selection MUST consider transport mechanism and concentration regime.
- A violated applicability rule MUST block qualified execution.
- A marginal applicability rule MUST create a warning and review task.
- Rules MAY recommend a hierarchy from simple analytical model to higher-fidelity numerical model.

### 13.4 Solver plan

- A solver plan MUST identify governing equations.
- A solver plan MUST identify constitutive laws.
- A solver plan MUST identify geometry idealization.
- A solver plan MUST identify dimensionality.
- A solver plan MUST identify spatial discretization.
- A solver plan MUST identify temporal discretization when relevant.
- A solver plan MUST identify nonlinear solution strategy when relevant.
- A solver plan MUST identify linear solvers and preconditioners when relevant.
- A solver plan MUST identify tolerances.
- A solver plan MUST identify stabilization or turbulence closure.
- A solver plan MUST identify boundary and initial conditions.
- A solver plan MUST identify coupling order and convergence for multiphysics.
- A solver plan MUST identify requested field outputs and derived quantities.
- A solver plan MUST identify verification activities.
- A solver plan MUST identify validation comparison.
- A solver plan MUST identify computational resource limits.
- A solver plan MUST identify the solver capsule by immutable digest.
- A solver plan MUST be canonical and content addressed.

### 13.5 Solver adapters

- A solver adapter translates normalized physics artifacts into a specific solver interface.
- A solver adapter MUST have a versioned schema contract.
- A solver adapter MUST validate all required fields before execution.
- A solver adapter MUST reject unsupported combinations.
- A solver adapter MUST generate deterministic input decks.
- A solver adapter MUST capture solver stdout and stderr.
- A solver adapter MUST capture exit status.
- A solver adapter MUST capture solver-native convergence information.
- A solver adapter MUST parse results into normalized result schemas.
- A solver adapter MUST preserve native result files.
- A solver adapter MUST identify units for every normalized field.
- A solver adapter MUST record any result transformation.
- A solver adapter MUST be tested against golden decks and results.
- Solver-specific defaults MUST be explicit rather than hidden.
- Vendor or open-source solver licensing MUST be honored by deployment packaging.

### 13.6 Solver capsule

- A solver capsule is a self-describing immutable executable analysis package.
- A solver capsule MUST have an identifier and semantic version.
- A solver capsule MUST have an OCI image digest or equivalent content digest.
- A solver capsule MUST declare supported physics intents.
- A solver capsule MUST declare governing equations.
- A solver capsule MUST declare numerical methods.
- A solver capsule MUST declare input and output schemas.
- A solver capsule MUST declare hardware and architecture support.
- A solver capsule MUST declare deterministic behavior expectations.
- A solver capsule MUST declare external libraries.
- A solver capsule MUST include an SPDX or CycloneDX SBOM.
- A solver capsule MUST include license metadata.
- A solver capsule MUST include build provenance.
- A solver capsule MUST include verification tests.
- A solver capsule MUST include validation references where claimed.
- A solver capsule MUST include known limitations.
- A solver capsule MUST include security scan status.
- A qualified capsule MUST be signed by an approved identity.
- Qualified execution MUST verify digest and signature before starting.
- A capsule tag MUST never substitute for a digest in controlled execution.

### 13.7 Solver Forge research workflow

- Solver Forge MAY search an approved registry for relevant existing capsules.
- Solver Forge MAY retrieve source code from allowlisted repositories in exploration mode.
- Solver Forge MAY synthesize solver source code in exploration mode.
- Solver Forge MUST create a research capsule before execution.
- Solver Forge MUST never run generated code in the application process.
- Solver Forge MUST run generated code with no ambient credentials.
- Solver Forge MUST default to no network during execution.
- Solver Forge MUST use read-only input mounts.
- Solver Forge MUST use a dedicated writable scratch space.
- Solver Forge MUST enforce CPU, memory, process, file, and wall-time limits.
- Solver Forge MUST record all retrieved source commits and digests.
- Solver Forge MUST record generated source and generation provenance.
- Solver Forge MUST generate unit tests for parsing and algebraic components.
- Solver Forge MUST generate dimensional-consistency tests.
- Solver Forge MUST include at least one independent benchmark problem.
- PDE capsules SHOULD include a method-of-manufactured-solutions test where feasible.
- Numerical capsules SHOULD include refinement or convergence studies.
- Conservation-law capsules MUST include conservation checks.
- Solver Forge MUST label the output `research_unqualified`.
- Solver Forge MUST produce a gap report when qualification evidence is insufficient.

### 13.8 Solver-capsule qualification

- Qualification Q0 means the capsule builds and its schema validates.
- Qualification Q1 means unit tests and static checks pass.
- Qualification Q2 means code-verification benchmarks pass.
- Qualification Q3 means solution-verification behavior is characterized.
- Qualification Q4 means validation against independent experimental or accepted reference data passes for a declared domain.
- Qualification Q5 means the capsule is approved for a specific organizational intended use.
- Qualification levels MUST not imply validity outside the declared applicability envelope.
- Qualification acceptance criteria MUST be approved before final testing.
- Qualification test data MUST be independent of development where practical.
- Qualification MUST record reviewers and evidence.
- Qualification MUST record compiler and dependency versions.
- Qualification MUST record numerical reproducibility constraints.
- A capsule change MUST trigger impact-based requalification.
- A dependency vulnerability MAY trigger suspension without numerical failure.
- A validation failure MUST revoke affected intended-use approvals.
- Historical results MUST remain linked to the capsule version originally used.

### 13.9 Meshing

- A mesh specification MUST identify geometry revision.
- A mesh specification MUST identify element or cell types.
- A mesh specification MUST identify order.
- A mesh specification MUST identify target sizes.
- A mesh specification MUST identify curvature and proximity controls.
- A mesh specification MUST identify boundary layers where applicable.
- A mesh specification MUST identify named physical regions.
- A mesh specification MUST identify quality thresholds.
- A mesh specification MUST identify refinement regions.
- A mesh build MUST retain tool version and settings.
- A mesh build MUST report element counts by type.
- A mesh build MUST report quality distributions.
- A mesh build MUST report failed or inverted elements.
- A mesh build MUST verify region coverage.
- A mesh build MUST verify boundary-condition targets are non-empty.
- Mesh-to-geometry association MUST use semantic references.
- Remeshing MUST not silently move boundary semantics.
- Release-grade numerical analyses MUST include a mesh-sensitivity rationale.

### 13.10 Boundary and initial conditions

- A boundary condition MUST reference a semantic region.
- A boundary condition MUST identify physical type.
- A boundary condition MUST identify value or law.
- A boundary condition MUST identify units.
- A boundary condition MUST identify evidence or assumption.
- A boundary condition MUST identify temporal variation where relevant.
- A boundary condition MUST identify spatial variation where relevant.
- A boundary condition SHOULD identify uncertainty.
- A boundary condition MUST report if the target region changes area materially after design edits.
- Point constraints that create singularities MUST be flagged.
- Overconstrained structural models MUST be detected where feasible.
- Flow models MUST check inlet-outlet consistency.
- Thermal models MUST check energy-balance closure.
- Initial conditions MUST be compatible with solver and material-state definitions.
- Mapped fields MUST record mapping error metrics.

### 13.11 Execution sandbox

- Each run MUST receive a unique ephemeral execution environment.
- Inputs MUST be mounted by digest.
- Qualified inputs MUST be read only.
- The root filesystem SHOULD be read only.
- Network MUST be disabled unless explicitly required and approved.
- System calls SHOULD be restricted by platform policy.
- Privileged execution MUST be forbidden.
- Host device access MUST be allowlisted.
- GPU access MUST be explicit and recorded.
- Environment variables MUST be allowlisted.
- Locale and timezone MUST be fixed for deterministic execution.
- Random seeds MUST be explicit where randomness is used.
- Thread count MUST be recorded where it affects numerical results.
- CPU architecture and accelerator model MUST be recorded when relevant.
- Resource exhaustion MUST return a distinct status from solver failure.
- Partial outputs MUST be quarantined until integrity checks complete.

### 13.12 Verification, validation, and uncertainty

- Code verification asks whether equations were implemented correctly.
- Solution verification asks whether the discrete solution adequately approximates the implemented equations.
- Validation asks whether the model adequately represents reality for the intended use.
- Calibration estimates model parameters and MUST not be misreported as validation.
- Numerical convergence MUST not be misreported as physical validation.
- Agreement with one experiment MUST not imply universal validity.
- Verification plans MUST be proportional to decision risk.
- Analytical benchmarks SHOULD be used where closed-form solutions exist.
- Manufactured solutions SHOULD be used for PDE implementation verification where feasible.
- Cross-solver comparison MAY support verification but MUST not replace independent truth.
- Mesh or time-step convergence MUST report observed order where feasible.
- Iterative error MUST be small relative to discretization and decision margins.
- Conservation residuals MUST be reported for conservative models.
- Uncertainty sources MUST include input uncertainty.
- Uncertainty sources MUST include numerical uncertainty.
- Uncertainty sources SHOULD include model-form uncertainty.
- Uncertainty propagation MAY use linearization, sampling, polynomial methods, or bounded analysis as appropriate.
- Correlated inputs MUST not be sampled independently without justification.
- Conformity decisions MUST state the decision rule.
- Guard bands MUST be explicit where used.
- A result without quantified uncertainty MUST state why and describe the consequence.

### 13.13 Result model

- A solver result MUST identify its run manifest.
- A solver result MUST identify completion status.
- A solver result MUST identify convergence status separately.
- A solver result MUST identify verification status separately.
- A solver result MUST identify validation applicability separately.
- A solver result MUST include scalar quantities with units.
- A solver result MAY include field artifacts with coordinate and unit metadata.
- A solver result MUST include derived-quantity formulas.
- A solver result MUST include extrema with semantic locations.
- A solver result MUST state whether extrema are singular or mesh-sensitive.
- A solver result MUST include acceptance evaluations.
- A solver result MUST include warnings and failed gates.
- A solver result MUST include an uncertainty summary.
- A solver result MUST include a human-readable applicability statement.
- A solver result MUST not use color maps without numeric legends and unit labels.

---

## 14. Contamination-control system

### 14.1 Scope and safety boundary

- The contamination system supports design analysis and contamination-control strategy evidence.
- The contamination system does not itself certify a cleanroom.
- The contamination system does not itself validate aseptic processing.
- The contamination system does not itself establish patient-safe residue limits.
- The contamination system does not infer sterility assurance from simulated counts.
- The contamination system MUST state whether each output is predicted, measured, or assumed.
- The contamination system MUST connect design predictions to monitoring or test plans.
- The contamination system MUST support conservative screening and higher-fidelity analyses as separate levels.

### 14.2 Contaminant species

- A contaminant species MUST have an identifier.
- A contaminant species MUST have a class.
- Classes MUST include nonviable particulate.
- Classes MUST include viable or microbe-carrying particulate.
- Classes MUST include molecular condensable contamination.
- Classes MUST include ionic contamination.
- Classes MUST include organic residue.
- Classes MUST include inorganic residue.
- Classes MUST include cleaning-agent residue.
- Classes MUST include process-product carryover.
- A species MUST identify size or size distribution when relevant.
- A species MUST identify density when relevant.
- A species MUST identify shape factor when relevant.
- A species MUST identify charge when relevant.
- A species MUST identify volatility or vapor pressure when relevant.
- A species MUST identify diffusivity when relevant.
- A species MUST identify solubility when relevant.
- A species MUST identify adsorption parameters when relevant.
- A species MUST identify viability or inactivation behavior when relevant.
- A species MUST identify analytical detection method where monitored.
- A species MUST identify health or product-quality limit evidence externally rather than inventing a limit.

### 14.3 Surface regions

- Every contamination-relevant surface MUST have a stable semantic region identifier.
- A surface region MUST identify material and surface treatment.
- A surface region SHOULD identify roughness.
- A surface region SHOULD identify surface energy or contact-angle evidence.
- A surface region SHOULD identify temperature history.
- A surface region SHOULD identify product contact status.
- A surface region SHOULD identify cleanroom vulnerability status.
- A surface region SHOULD identify visibility and inspection access.
- A surface region SHOULD identify swab access.
- A surface region SHOULD identify drainability.
- A surface region SHOULD identify crevice or dead-leg classification.
- A surface region SHOULD identify joints, seals, and discontinuities.
- A surface region MAY identify an empirical recovery factor.
- A surface region MAY identify a contamination budget.
- Surface-region changes MUST trigger impact analysis for linked contamination and cleaning models.

### 14.4 Source and transfer model

- A contamination source MUST identify species.
- A contamination source MUST identify location.
- A contamination source MUST identify rate or inventory.
- A contamination source MUST identify temporal behavior.
- A contamination source MUST identify evidence and uncertainty.
- Sources MAY include personnel.
- Sources MAY include equipment wear.
- Sources MAY include lubricants.
- Sources MAY include process aerosols.
- Sources MAY include incoming materials.
- Sources MAY include outgassing.
- Sources MAY include cleaning materials.
- Sources MAY include prior product residues.
- Transfer mechanisms MUST include advection where applicable.
- Transfer mechanisms MUST include molecular diffusion where applicable.
- Transfer mechanisms SHOULD include gravitational settling.
- Transfer mechanisms SHOULD include inertial impaction.
- Transfer mechanisms SHOULD include Brownian deposition.
- Transfer mechanisms SHOULD include interception.
- Transfer mechanisms SHOULD include thermophoresis.
- Transfer mechanisms SHOULD include electrostatic transport.
- Transfer mechanisms SHOULD include resuspension.
- Transfer mechanisms SHOULD include contact transfer.
- Transfer mechanisms SHOULD include adsorption and desorption.
- Transfer mechanisms SHOULD include permeation and outgassing.
- Transfer mechanisms MAY include microbial growth and inactivation with strict model limitations.

### 14.5 Contamination network model

- The system MUST support a low-order compartment model.
- A compartment MUST have volume, surface area, and exchange interfaces.
- A transfer edge MUST have direction, mechanism, rate law, and evidence.
- A sink MUST identify capacity or removal law.
- A filter MUST identify efficiency as a function of relevant particle size or species.
- A leak MUST identify directionality and driving conditions.
- A door-opening event MAY be represented as a transient exchange.
- A cleaning event MAY reset or transform surface inventory according to evidence.
- The network model MUST conserve mass subject to declared sources, sinks, and reactions.
- Conservation error MUST be reported.
- Low-order results MUST identify spatial limitations.
- A compartment model MAY trigger escalation to CFD when mixing assumptions fail.

### 14.6 Particle and species CFD

- CFD-based contamination analysis MUST start from an approved flow solution or coupled plan.
- Eulerian species transport MAY be used for dilute scalar transport where applicable.
- Lagrangian tracking MAY be used for discrete particles where applicable.
- Particle-size distributions MUST be discretized with a documented method.
- Near-wall deposition models MUST identify their empirical or theoretical basis.
- Turbulent dispersion settings MUST be recorded.
- Particle-wall interaction MUST distinguish capture, rebound, and resuspension.
- Brownian effects MUST be considered for sufficiently small particles.
- One-way coupling MUST be justified by loading.
- Two-way coupling MUST be considered when particle loading affects flow.
- Results MUST include deposition flux by semantic surface.
- Results MUST include uncertainty or sensitivity to poorly known deposition parameters.
- Validation SHOULD use tracer, deposition-coupon, particle-counter, or equivalent measurements appropriate to the mechanism.

### 14.7 Contamination-control strategy support

- A CCS artifact MUST identify critical contamination hazards.
- A CCS artifact MUST identify preventive controls.
- A CCS artifact MUST identify monitoring controls.
- A CCS artifact MUST identify response actions.
- A CCS artifact MUST identify linked facility, utility, equipment, process, and personnel factors.
- A CCS artifact MUST identify evidence gaps.
- A CCS artifact MUST distinguish design control from procedural control.
- A CCS artifact MUST distinguish prediction from qualification evidence.
- A CCS artifact MUST support lifecycle review after change.
- Contrainte MAY assemble CCS evidence but MUST not declare the CCS adequate without authorized review.

---

## 15. Cleaning and decontamination system

### 15.1 Cleaning intent

- A cleaning intent MUST identify equipment and product-contact scope.
- A cleaning intent MUST identify prior product or contaminant.
- A cleaning intent MUST identify cleaning endpoint.
- A cleaning intent MUST identify externally established acceptance limits.
- A cleaning intent MUST identify cleaning method.
- A cleaning intent MUST identify agent composition and concentration.
- A cleaning intent MUST identify contact time.
- A cleaning intent MUST identify temperature.
- A cleaning intent MUST identify flow, pressure, spray, or mechanical action.
- A cleaning intent MUST identify rinse strategy.
- A cleaning intent MUST identify drying strategy.
- A cleaning intent MUST identify dirty hold time.
- A cleaning intent MUST identify clean hold time.
- A cleaning intent MUST identify disassembly and reassembly assumptions.
- A cleaning intent MUST identify sampling strategy.
- A cleaning intent MUST identify analytical methods.
- A cleaning intent MUST identify material-compatibility constraints.
- A cleaning intent MUST identify validation status.

### 15.2 Cleanability geometry

- The system MUST detect inaccessible product-contact regions.
- The system MUST detect enclosed voids not represented as intentional process volumes.
- The system SHOULD detect crevices against project-specific geometry rules.
- The system SHOULD detect internal corners below cleanability radius rules.
- The system SHOULD detect reverse slopes and pooling regions.
- The system SHOULD detect dead legs using configured definitions.
- The system SHOULD detect unvented high points and undrainable low points.
- The system SHOULD assess line-of-sight for manual inspection.
- The system SHOULD assess tool and swab accessibility.
- The system SHOULD assess spray line-of-sight.
- The system SHOULD assess shadowing by internal components.
- The system SHOULD assess gasket intrusion and seal exposure.
- The system SHOULD assess disassembly clearance.
- Each finding MUST reference semantic geometry.
- Each finding MUST state the rule and threshold used.
- A geometric cleanability pass MUST not imply cleaning-process validation.

### 15.3 Cleaning physics

- Cleaning-fluid analysis MAY evaluate wetting coverage.
- Cleaning-fluid analysis MAY evaluate wall shear stress.
- Cleaning-fluid analysis MAY evaluate local velocity.
- Cleaning-fluid analysis MAY evaluate turbulence proxies where model appropriate.
- Cleaning-fluid analysis MAY evaluate residence time.
- Cleaning-fluid analysis MAY evaluate temperature distribution.
- Cleaning-fluid analysis MAY evaluate detergent concentration distribution.
- Cleaning-fluid analysis MAY evaluate rinse dilution and displacement.
- Cleaning-fluid analysis MAY evaluate spray impact coverage.
- Cleaning-fluid analysis MAY evaluate drain-down and retained liquid.
- Residue-removal models MAY combine dissolution, desorption, reaction, shear, and mass transfer.
- Residue-removal models MUST identify calibrated parameters.
- Residue-removal models MUST identify surface and residue applicability.
- Empirical removal factors MUST retain study conditions.
- Scale-up assumptions MUST be explicit.
- A prediction MUST not substitute for swab, rinse, direct extraction, or other required validation evidence.

### 15.4 Worst-case selection

- Worst-case product selection MUST consider potency or health-based limits supplied by approved evidence.
- Worst-case product selection MUST consider solubility.
- Worst-case product selection MUST consider cleanability.
- Worst-case product selection MUST consider stickiness or film formation.
- Worst-case product selection MUST consider degradation products.
- Worst-case product selection MUST consider batch size and equipment train.
- Worst-case product selection MUST consider campaign length.
- Worst-case product selection MUST consider surface material.
- Worst-case product selection MUST consider hold time.
- Worst-case selection weights MUST be explicit.
- A single composite rank MUST not hide a hard worst case in one critical dimension.
- Bracketing and matrix approaches MUST retain scientific rationale.
- AI MAY propose a matrix but an authorized SME MUST approve it.

### 15.5 Sampling and analytical evidence

- A sampling plan MUST identify locations by semantic surface.
- A sampling plan MUST identify method.
- A sampling plan MUST identify area or volume.
- A sampling plan MUST identify recovery factor.
- A sampling plan MUST identify detection and quantitation limits.
- A sampling plan MUST identify sample handling.
- A sampling plan MUST identify timing.
- A sampling plan MUST identify replicates.
- A sampling plan MUST identify rationale for inaccessible locations.
- Direct surface sampling SHOULD be used where feasible and required by the applicable procedure.
- Rinse sampling MUST identify solvent suitability and coverage limitations.
- Recovery studies MUST be specific enough to support the surface-residue-method combination.
- Visual inspection MUST be represented separately from analytical testing.
- Microbial and endotoxin evidence MUST remain separate from chemical-residue evidence.
- Analytical result imports MUST preserve raw data references.
- Calculations MUST propagate recovery corrections and uncertainty transparently.

### 15.6 Cleaning validation evidence package

- The package MUST include approved protocol reference.
- The package MUST include equipment configuration.
- The package MUST include cleaning procedure revision.
- The package MUST include executed parameters.
- The package MUST include deviations.
- The package MUST include sampling records.
- The package MUST include analytical results.
- The package MUST include acceptance evaluation.
- The package MUST include investigation and CAPA links where applicable.
- The package MUST include final conclusion by authorized personnel.
- Simulation artifacts MAY support location selection and rationale.
- Simulation artifacts MUST be labeled supporting evidence.
- Continued-verification monitoring MUST be linkable to the validated cleaning process.
- A design change MUST trigger cleaning-validation impact assessment.

---

## 16. Quality, GMP enablement, and data integrity

### 16.1 Intended-use governance

- Every controlled installation MUST maintain an intended-use statement.
- The intended-use statement MUST identify supported business processes.
- The intended-use statement MUST identify regulated records.
- The intended-use statement MUST identify critical functions.
- The intended-use statement MUST identify excluded uses.
- The intended-use statement MUST identify user groups.
- The intended-use statement MUST identify interfaces.
- The intended-use statement MUST identify operating modes.
- The intended-use statement MUST identify applicable regulations and guidance selected by the organization.
- The intended-use statement MUST identify risk classification.
- The intended-use statement MUST be approved by process owner, system owner, and quality roles defined by procedure.
- Intended-use changes MUST trigger validation impact assessment.

### 16.2 Lifecycle deliverables

- The quality system MUST support a validation plan.
- The quality system MUST support user requirements specifications.
- The quality system MUST support functional specifications.
- The quality system MUST support design specifications.
- The quality system MUST support configuration specifications.
- The quality system MUST support risk assessments.
- The quality system MUST support supplier assessments.
- The quality system MUST support traceability matrices.
- The quality system MUST support installation qualification evidence.
- The quality system MUST support operational qualification evidence.
- The quality system MUST support performance qualification or user-acceptance evidence as defined by intended use.
- The quality system MUST support validation summary reports.
- The quality system MUST support release authorization.
- The quality system MUST support periodic review.
- The quality system MUST support retirement and archival plans.
- Deliverable names MAY vary by organization while semantic content remains mapped.

### 16.3 Risk management

- Risk management MUST follow an approved lifecycle procedure.
- Risk records MUST identify hazardous situation or failure mode.
- Risk records MUST identify cause.
- Risk records MUST identify effect on patient safety, product quality, data integrity, engineering safety, or business continuity.
- Risk records MUST identify existing controls.
- Risk records MUST identify initial risk evaluation.
- Risk records MUST identify additional controls where required.
- Risk records MUST identify control verification.
- Risk records MUST identify residual risk.
- Risk-scoring scales MUST be defined and versioned.
- Detectability scoring MUST not be used to disguise unacceptable severity.
- Risk acceptance MUST identify authorized role.
- Risks MUST link to requirements and tests.
- AI MAY propose risks but MUST not approve risk acceptance.
- Risk reviews MUST occur after significant changes and incidents.

### 16.4 ALCOA+ controls

- Attributable records MUST identify the responsible human or system agent.
- Legible records MUST remain readable in human and machine form for the retention period.
- Contemporaneous records MUST use trusted time and record delayed entry explicitly.
- Original records MUST preserve original bytes or a verified true copy as applicable.
- Accurate records MUST be protected by validation, checks, and correction controls.
- Complete records MUST include relevant metadata, audit trail, invalidated results, and repetitions where required.
- Consistent records MUST preserve sequence and use synchronized time.
- Enduring records MUST use durable controlled storage.
- Available records MUST be retrievable throughout retention and inspection needs.
- Audit views MUST not omit failed or superseded events by default.
- Export MUST preserve context necessary to understand a record.
- Data-integrity controls MUST be based on criticality and vulnerability.

### 16.5 Audit trail

- An audit event MUST have a unique identifier.
- An audit event MUST identify actor.
- An audit event MUST identify action.
- An audit event MUST identify object.
- An audit event MUST identify object revision.
- An audit event MUST identify timestamp from a controlled clock.
- An audit event MUST identify before and after digests for changes.
- An audit event MUST identify reason when required.
- An audit event MUST identify originating client and session.
- An audit event MUST identify automated rule or workflow when system-generated.
- Audit events MUST be append only.
- Audit-event storage MUST be protected from ordinary administrators where feasible.
- Audit-event corrections MUST be new events.
- Audit trails MUST be searchable by object, actor, time, action, and project.
- Audit-trail review MUST be a configurable workflow.
- Audit-trail exports MUST be human readable and machine readable.
- Audit-trail retention MUST follow the regulated record.

### 16.6 Electronic signatures

- An electronic signature MUST identify signer.
- An electronic signature MUST identify signing time.
- An electronic signature MUST identify signature meaning.
- Signature meanings MUST include authorship, verification, approval, and release as configured.
- An electronic signature MUST bind to the exact content digest.
- An electronic signature MUST require authentication appropriate to policy.
- Reauthentication MUST be required at signing when policy demands it.
- Signature credentials MUST be unique to an individual.
- Shared signature accounts MUST be forbidden.
- Signature manifestation MUST show printed name, date and time, and meaning where required.
- Signature revocation MUST not erase the historical signature.
- Signature verification MUST remain possible after user deactivation.
- Signature-provider failure MUST fail closed.
- Cryptographic signatures MAY complement but do not replace procedural identity controls.

### 16.7 Access control

- Access MUST follow least privilege.
- Authentication SHOULD use enterprise single sign-on.
- Multi-factor authentication SHOULD be required for controlled and administrative access.
- Authorization MUST evaluate user, role, project, data classification, mode, and artifact status.
- Access to held-out AI test data MUST be separately controlled.
- Access to restricted standards and material data MUST honor licenses.
- Service accounts MUST be non-interactive where possible.
- Service-account credentials MUST rotate.
- Privileged actions MUST be logged.
- User creation, modification, and deactivation MUST be controlled.
- Dormant accounts MUST be reviewed.
- Access reviews MUST be periodic.
- Separation-of-duty conflicts MUST be detectable.
- Emergency access MUST be exceptional, time-limited, and reviewed.

### 16.8 Change control

- Every controlled change MUST have a change record.
- A change record MUST identify reason and scope.
- A change record MUST identify affected intended uses.
- A change record MUST identify affected requirements.
- A change record MUST identify affected risks.
- A change record MUST identify validation impact.
- A change record MUST identify data-migration impact.
- A change record MUST identify cybersecurity impact.
- A change record MUST identify training impact.
- A change record MUST identify rollback or recovery strategy.
- A change record MUST identify approvals.
- Emergency changes MUST follow retrospective review.
- Configuration changes MUST be versioned like code changes.
- Model, prompt, tool, material-pack, part-pack, and solver-capsule changes MUST all enter change control when controlled.

### 16.9 Deviations, incidents, and CAPA

- A deviation MUST identify expected and observed behavior.
- A deviation MUST identify affected artifacts and records.
- A deviation MUST identify immediate containment.
- A deviation MUST identify impact assessment.
- Significant deviations MUST have root-cause investigation.
- CAPA actions MUST have owner and due date.
- CAPA effectiveness MUST be verified.
- Software defects MUST be evaluated for retrospective impact on prior results.
- A defective solver capsule MUST trigger a query for every dependent run.
- A defective material property MUST trigger a query for every dependent design and run.
- Security incidents MUST evaluate data-integrity impact.
- Incident closure MUST not delete forensic evidence.

### 16.10 Backup, restore, archive, and retention

- Backup scope MUST include metadata, artifacts, audit events, signatures, configurations, and keys needed for recovery.
- Backup frequency MUST derive from recovery-point objectives.
- Restore procedures MUST be tested periodically.
- Restore tests MUST verify content digests.
- Recovery-time objectives MUST be defined by deployment.
- Archives MUST preserve readable formats and required execution artifacts.
- Archive retrieval MUST be tested.
- Retention rules MUST support project, artifact class, jurisdiction, and legal hold.
- Legal hold MUST override ordinary deletion.
- Retention expiry MUST use an authorized disposition workflow.
- Encryption-key retention MUST support record readability for the required period.
- Third-party service exit plans MUST include export and verification.

### 16.11 Periodic review

- Periodic review MUST examine intended use.
- Periodic review MUST examine validated configuration.
- Periodic review MUST examine changes.
- Periodic review MUST examine deviations and incidents.
- Periodic review MUST examine CAPA effectiveness.
- Periodic review MUST examine access and privileges.
- Periodic review MUST examine audit-trail review outcomes.
- Periodic review MUST examine security vulnerabilities.
- Periodic review MUST examine backups and restore tests.
- Periodic review MUST examine supplier status.
- Periodic review MUST examine AI model performance and drift where applicable.
- Periodic review MUST examine solver-capsule qualification.
- Periodic review MUST examine obsolete material and part packs.
- Periodic review MUST conclude whether the system remains in a state of control.

---

## 17. Security and software supply chain

### 17.1 Threat model

- Threats include malicious uploaded files.
- Threats include prompt injection in source documents.
- Threats include generated-code escape.
- Threats include dependency compromise.
- Threats include solver image substitution.
- Threats include material or part data tampering.
- Threats include unauthorized record change.
- Threats include approval impersonation.
- Threats include data exfiltration through hosted models.
- Threats include denial of service through expensive geometry or meshes.
- Threats include cross-project data leakage.
- Threats include malicious or careless administrators.
- Threats include compromised source adapters.
- Threats include stale vulnerable qualified software.
- The threat model MUST be reviewed at least for major architecture changes.

### 17.2 Secure development

- Development practices SHOULD map to NIST SSDF.
- Protected branches SHOULD require review and passing checks.
- Releases MUST be built by a controlled pipeline.
- Build provenance MUST identify source revision and builder.
- Release artifacts MUST have SBOMs.
- Dependencies MUST be pinned with integrity data.
- Secrets MUST not be committed to the repository.
- Secret scanning MUST run in continuous integration.
- Static analysis MUST run on supported languages.
- Dependency vulnerability scanning MUST run regularly.
- Container scanning MUST run before capsule promotion.
- Fuzzing SHOULD target parsers, canonicalization, and geometry input boundaries.
- Security defects MUST have severity and response targets.
- Release signing keys MUST be protected by managed key infrastructure.

### 17.3 Runtime security

- API traffic MUST use authenticated encryption.
- Stored sensitive data MUST use encryption appropriate to deployment policy.
- Tenant or project boundaries MUST be enforced server-side.
- Object-store URLs MUST be short-lived and scoped.
- Uploads MUST be quarantined before processing.
- File-type detection MUST inspect content, not only extension.
- Active document content SHOULD be stripped or isolated for preview.
- External fetches MUST resist server-side request forgery.
- Source adapters MUST use domain allowlists in controlled modes.
- Egress logs MUST be retained according to policy.
- Rate limits MUST cover costly compilation and simulation endpoints.
- Worker compromise MUST not grant database-owner privileges.
- Artifact digests MUST be verified at each trust-boundary transfer.

### 17.4 Solver supply chain

- Solver source MUST be pinned to commit or archive digest.
- Solver builds MUST run in controlled builders for qualification.
- Solver images MUST be signed.
- Solver images MUST include SLSA-compatible provenance where feasible.
- Solver images MUST include an SBOM.
- Solver images MUST have license review.
- Solver images MUST have vulnerability disposition.
- Qualified registries MUST prevent mutable tag substitution.
- Admission policy MUST verify signer and digest.
- Runtime MUST record the executed image digest independently of the request.
- Source availability obligations MUST be met for redistributed copyleft components.
- A license conflict MUST block distribution even if numerical tests pass.

---

## 18. Localization and French-language correctness

### 18.1 Language model

- Canonical identifiers MUST be language neutral.
- Canonical technical semantics MUST be language neutral.
- User-facing labels MUST support French and English.
- Requirements MUST preserve original language.
- Approved translations MUST be linked, not substituted.
- Terminology entries MUST include domain, source, preferred term, synonyms, and prohibited ambiguity.
- French terminology MUST distinguish `contrainte` as mechanical stress from `contrainte` as design constraint by semantic context.
- French terminology MUST distinguish `déformation` as strain or displacement by quantity kind.
- French terminology MUST distinguish `limite d'élasticité` from elastic limit assumptions used by a specific source.
- French terminology MUST distinguish `état de surface` from generic surface condition.
- French terminology MUST support GMP terms used by French-speaking sites.
- Standards terminology MUST preserve the governing edition's meaning.

### 18.2 Locale-safe numbers and dates

- French UI MAY display decimal commas.
- English UI MAY display decimal points.
- Canonical data MUST use locale-independent numeric serialization.
- Thousands separators MUST never be inferred ambiguously.
- Unit symbols MUST not be translated incorrectly.
- Dates MUST be stored in ISO 8601 form.
- Display dates MAY follow locale.
- Time zones MUST be explicit for audit and signature records.
- CSV import MUST require or infer locale with a reviewable preview.
- Spreadsheet formulas MUST not be trusted as static values without import policy.
- `1,234` MUST not be silently interpreted without locale context.

### 18.3 Translation quality

- Critical controlled text MUST be translated by an approved workflow.
- Machine translation MAY propose text.
- Approved bilingual terminology MUST constrain machine translation.
- Back-translation MAY support review but MUST not replace domain review.
- Translation tests MUST include numeric, unit, negation, modal, and tolerance preservation.
- A translation change MUST be traceable.
- Bilingual reports MUST display one canonical requirement identifier.
- Search SHOULD find canonical entities through either language.
- Audit events MUST preserve the language in which reasons were entered.

---

## 19. API and storage contracts

### 19.1 API principles

- The API MUST be versioned.
- The API MUST use idempotency keys for state-changing retryable operations.
- The API MUST return machine-readable error codes.
- The API MUST return correlation identifiers.
- The API MUST enforce authorization server-side.
- The API MUST support optimistic concurrency for draft edits.
- The API MUST reject edits to immutable revisions.
- Long-running work MUST return a job identifier.
- Job state MUST distinguish queued, running, succeeded, failed, canceled, and quarantined.
- Cancellation MUST be best effort and auditable.
- Pagination MUST be stable.
- API schemas MUST be published from source-controlled definitions.
- Breaking changes MUST require a major API version.

### 19.2 Core endpoints

- `POST /projects` creates a project draft.
- `POST /artifacts` uploads or registers an artifact.
- `POST /intent/extractions` starts candidate extraction.
- `POST /cir/validate` validates a CIR proposal without persisting release state.
- `POST /designs/{id}/revisions` creates a new design revision.
- `POST /designs/{id}/compile` starts deterministic compilation.
- `GET /jobs/{id}` returns job state and diagnostics.
- `GET /artifacts/{digest}` retrieves an authorized artifact.
- `POST /catalog/search` searches configured source adapters.
- `POST /materials/query` queries configured material packs.
- `POST /physics/plans` creates or validates a solver plan.
- `POST /runs` starts a solver run.
- `POST /reviews` creates a review task.
- `POST /promotions` requests artifact promotion.
- `POST /signatures` executes a configured signature workflow.
- `GET /trace/{artifact_id}` returns the evidence and dependency graph.
- `GET /audit` returns authorized audit events.
- Exact endpoint shapes remain subject to implementation review.

### 19.3 Transactional storage

- PostgreSQL MUST store project metadata.
- PostgreSQL MUST store identity references and role bindings.
- PostgreSQL MUST store workflow state.
- PostgreSQL MUST store artifact manifests and digests.
- PostgreSQL MUST store claim and provenance indexes.
- PostgreSQL MUST store append-only audit-event references.
- Large binaries MUST not be stored as ordinary database rows unless deployment constraints justify it.
- Database migrations MUST be versioned.
- Database migrations MUST be tested against representative snapshots.
- Destructive migrations MUST have verified backup and rollback strategy.
- Application code MUST not depend on unspecified row order.
- Controlled timestamps SHOULD be assigned server-side.

### 19.4 Artifact storage

- Artifact paths MUST derive from content digest rather than user filename.
- User filenames MUST be metadata.
- Artifact writes MUST be atomic.
- Artifact reads MUST verify digest for controlled content.
- Artifact manifests MUST enumerate media type and size.
- Multipart uploads MUST verify final digest.
- Duplicate content MAY be deduplicated.
- Deduplication MUST not leak existence across authorization boundaries.
- Storage lifecycle rules MUST honor retention and legal hold.
- Replication MUST preserve digests.
- Archive transitions MUST preserve retrievability metadata.

### 19.5 Event model

- Domain events MUST identify event type and schema version.
- Domain events MUST identify aggregate and revision.
- Domain events MUST identify causal command.
- Domain events MUST identify correlation chain.
- Domain events MUST be immutable.
- Event consumers MUST be idempotent.
- Event delivery MAY be at least once.
- Consumers MUST tolerate duplicates.
- Outbox patterns SHOULD couple transaction state and event publication.
- Event replay MUST not repeat external side effects without safeguards.
- Audit events and domain events MAY share infrastructure but MUST retain distinct semantics.

---

## 20. User experience

### 20.1 Workspace model

- The primary workspace MUST show intent, model, evidence, and checks together.
- The interface MUST not hide warnings behind a generic success state.
- A model tree MUST show semantic features and assemblies.
- A requirements pane MUST show trace status.
- A claims pane MUST show basis and evidence.
- A geometry view MUST allow selection by semantic role.
- A physics pane MUST show assumptions, regions, and solver plan.
- A contamination pane MUST show pathways and surface budgets.
- A cleaning pane MUST show coverage, access, pooling, and sampling locations.
- A review pane MUST show unresolved critical items.
- A provenance view MUST let a reviewer traverse backward from any result.

### 20.2 Confidence presentation

- The UI MUST avoid one universal certainty percentage.
- The UI MUST show independent dimensions of confidence.
- Dimensions SHOULD include source authority.
- Dimensions SHOULD include applicability match.
- Dimensions SHOULD include extraction confidence.
- Dimensions SHOULD include numerical verification.
- Dimensions SHOULD include physical validation.
- Dimensions SHOULD include review status.
- A failed critical dimension MUST remain visually dominant.
- Uncertainty intervals MUST accompany estimates where available.
- AI confidence MUST not be presented as engineering probability without calibration evidence.

### 20.3 Review ergonomics

- Reviewers MUST be able to compare revisions semantically.
- Geometry diffs MUST distinguish added, removed, and modified regions.
- Parameter diffs MUST show units and prior values.
- Evidence diffs MUST show source changes.
- Solver diffs MUST show equation, setting, mesh, and capsule changes.
- Material diffs MUST show state and applicability changes.
- Reviews MUST support comments anchored to stable entities.
- Review resolution MUST not delete the original comment.
- The UI MUST make waived gates visible.
- The UI MUST show what will be signed before signature.

### 20.4 Accessibility and performance

- Keyboard navigation MUST cover primary workflows.
- Color MUST not be the sole carrier of status.
- Technical plots MUST use accessible palettes.
- Large models SHOULD stream visualization levels without changing authoritative geometry.
- The UI SHOULD remain responsive while workers run.
- Interrupted sessions MUST not lose acknowledged draft changes.

---

## 21. Observability and operations

### 21.1 Operational telemetry

- Services MUST emit structured logs.
- Logs MUST include correlation identifiers.
- Logs MUST not include secrets.
- Logs MUST minimize controlled proprietary geometry and content.
- Metrics MUST include request latency and errors.
- Metrics MUST include queue depth and age.
- Metrics MUST include worker utilization.
- Metrics MUST include cache hit rate.
- Metrics MUST include geometry compilation failure classes.
- Metrics MUST include solver failure classes.
- Metrics MUST include artifact-integrity failures.
- Metrics MUST include source-adapter freshness and errors.
- Traces SHOULD span API, workflow, worker, and artifact operations.
- Scientific result data MUST remain in evidence artifacts rather than monitoring logs.

### 21.2 Service objectives

- Interactive metadata operations SHOULD complete within 300 milliseconds at the 95th percentile under target load.
- Draft CIR validation SHOULD complete within two seconds for ordinary part models.
- Simple geometry compilation SHOULD complete within five seconds on reference hardware.
- Large geometry and simulations are asynchronous and MUST report progress by stage.
- The team deployment SHOULD target 99.5 percent monthly availability before enterprise hardening.
- The enterprise target MAY increase after failure-budget evidence exists.
- Recovery-point and recovery-time objectives MUST be deployment-specific.
- Scientific correctness gates MUST never be relaxed to satisfy latency objectives.

### 21.3 Operational runbooks

- Runbooks MUST cover database restore.
- Runbooks MUST cover artifact-store restore.
- Runbooks MUST cover compromised signing key.
- Runbooks MUST cover failed solver registry.
- Runbooks MUST cover source-adapter outage.
- Runbooks MUST cover integrity-check failure.
- Runbooks MUST cover stuck workflow.
- Runbooks MUST cover security incident containment.
- Runbooks MUST cover air-gapped pack import.
- Runbooks MUST identify escalation and evidence-preservation steps.

---

## 22. Verification and evaluation program

### 22.1 Test layers

- Unit tests MUST cover quantity and unit algebra.
- Unit tests MUST cover canonical serialization.
- Unit tests MUST cover digest stability.
- Unit tests MUST cover schema validation.
- Unit tests MUST cover applicability predicates.
- Unit tests MUST cover policy transitions.
- Property-based tests SHOULD cover unit conversions and dimensional algebra.
- Property-based tests SHOULD cover canonicalization invariants.
- Contract tests MUST cover every source adapter.
- Contract tests MUST cover every solver adapter.
- Golden tests MUST cover deterministic CIR compilation.
- Golden tests MUST cover geometry exports.
- Integration tests MUST cover artifact storage and manifests.
- Integration tests MUST cover workflow retries.
- Integration tests MUST cover authorization boundaries.
- End-to-end tests MUST cover proposal through evidence bundle.
- Security tests MUST cover uploaded hostile content and sandbox isolation.
- Recovery tests MUST cover backup and restore.
- Performance tests MUST cover target model sizes and concurrent jobs.
- Qualification tests MUST map to controlled requirements.

### 22.2 CAD benchmark dimensions

- The CAD benchmark MUST measure proposal schema validity.
- The CAD benchmark MUST measure successful deterministic compilation.
- The CAD benchmark MUST measure B-Rep validity.
- The CAD benchmark MUST measure body-count correctness.
- The CAD benchmark MUST measure dimensional accuracy.
- The CAD benchmark MUST measure topology and feature correctness.
- The CAD benchmark MUST measure constraint completeness.
- The CAD benchmark MUST measure design-intent recovery.
- The CAD benchmark MUST measure parameter editability.
- The CAD benchmark MUST measure stability under parameter perturbation.
- The CAD benchmark MUST measure stable semantic selection.
- The CAD benchmark MUST measure assembly-joint correctness.
- The CAD benchmark MUST measure interference behavior.
- The CAD benchmark MUST measure PMI preservation where present.
- The CAD benchmark MUST measure export fidelity.
- The CAD benchmark MUST report runtime and failure class.
- Visual similarity MAY be reported but MUST not be the primary engineering score.

### 22.3 Sourcing benchmark dimensions

- The sourcing benchmark MUST measure correct manufacturer identification.
- The sourcing benchmark MUST measure exact part-number match.
- The sourcing benchmark MUST measure configuration match.
- The sourcing benchmark MUST measure revision capture.
- The sourcing benchmark MUST measure dimension extraction accuracy.
- The sourcing benchmark MUST measure tolerance-form accuracy.
- The sourcing benchmark MUST measure source-region citation accuracy.
- The sourcing benchmark MUST measure source-conflict detection.
- The sourcing benchmark MUST measure stale-source detection.
- The sourcing benchmark MUST measure appropriate abstention.
- A hallucinated dimension MUST count as a critical error.

### 22.4 Materials benchmark dimensions

- The materials benchmark MUST measure identity normalization.
- The materials benchmark MUST measure state and product-form matching.
- The materials benchmark MUST measure unit correctness.
- The materials benchmark MUST measure applicability-envelope matching.
- The materials benchmark MUST measure evidence-grade assignment.
- The materials benchmark MUST measure interpolation correctness.
- The materials benchmark MUST measure extrapolation detection.
- The materials benchmark MUST measure source citation.
- The materials benchmark MUST measure rejection of plausible but inapplicable data.
- The materials benchmark MUST include temperature-dependent and anisotropic cases.

### 22.5 Physics benchmark dimensions

- The physics benchmark MUST measure model-selection appropriateness.
- The physics benchmark MUST measure boundary-condition grounding.
- The physics benchmark MUST measure dimensional consistency.
- The physics benchmark MUST measure analytical benchmark error.
- The physics benchmark MUST measure observed convergence behavior.
- The physics benchmark MUST measure conservation closure.
- The physics benchmark MUST measure cross-solver consistency where applicable.
- The physics benchmark MUST measure uncertainty propagation.
- The physics benchmark MUST measure applicability warnings.
- The physics benchmark MUST measure false claims of validation.
- The physics benchmark MUST include deliberately converged but physically wrong cases.

### 22.6 Contamination and cleaning benchmark dimensions

- The benchmark MUST measure contaminant-class correctness.
- The benchmark MUST measure source and pathway identification.
- The benchmark MUST measure mass-conservation closure.
- The benchmark MUST measure deposition-model applicability.
- The benchmark MUST measure cleanability-rule detection.
- The benchmark MUST measure spray-shadow detection on validated fixtures.
- The benchmark MUST measure pooling detection.
- The benchmark MUST measure sampling-location traceability.
- The benchmark MUST measure distinction between prediction and validation evidence.
- The benchmark MUST treat an unsupported sterility claim as a critical failure.

### 22.7 Reliability statistics

- Pass rates MUST include confidence intervals.
- Rare critical failures MUST be reported as counts and rates.
- Zero observed failures MUST not be presented as zero true failure probability.
- Reliability claims MUST state sample size and sampling frame.
- Repeatedly tuned benchmark sets MUST be labeled development sets.
- Final qualification sets MUST be protected from development leakage.
- Results MUST be stratified by complexity and domain.
- Regression budgets MUST be approved by criticality.
- A statistically improved aggregate score MUST not permit regression on a safety-critical gate.

### 22.8 Release quality gates

- All required tests MUST pass.
- Critical static-analysis findings MUST be resolved or formally accepted.
- Critical vulnerabilities MUST be resolved or formally dispositioned before controlled release.
- Database migrations MUST pass upgrade and rollback tests where rollback is supported.
- CIR migration fixtures MUST pass.
- Artifact canonicalization fixtures MUST remain stable or undergo explicit version migration.
- SBOM and build provenance MUST be generated.
- Release artifacts MUST be signed for controlled distributions.
- Documentation MUST match implemented configuration.
- Known limitations MUST be updated.
- Validation impact MUST be approved for qualified deployments.

---

## 23. Performance and scale envelope

### 23.1 Initial reference envelope

- The first part-model target is 500 features.
- The first assembly target is 1,000 occurrences with lightweight display representations.
- The first CIR target is 50 megabytes excluding referenced binary artifacts.
- The first evidence-graph target is 100,000 claims and edges per project.
- The first local artifact-bundle target is 10 gigabytes per run.
- The first interactive concurrent-user target is 25 users per team deployment.
- The first worker target is 100 queued jobs per deployment.
- These are engineering targets, not demonstrated guarantees.
- Benchmarks MUST publish reference hardware.
- Limits MUST fail predictably rather than through data corruption.

### 23.2 Numerical reproducibility

- Bitwise reproducibility SHOULD be targeted for canonical structured artifacts.
- Bitwise reproducibility MAY be unattainable for all parallel floating-point solvers.
- Numerical reproducibility criteria MUST therefore be solver specific.
- Criteria MAY use normed field differences and derived-quantity tolerances.
- Hardware changes MUST be recorded.
- Thread-count changes MUST be recorded.
- Library and compiler changes MUST be recorded.
- Nondeterministic solver behavior MUST be characterized before qualification.
- A result outside the reproducibility envelope MUST trigger investigation.

---

## 24. Development roadmap

### 24.1 Phase 0: evidence-first kernel

- Phase 0 duration target is two to four weeks.
- Phase 0 builds exact decimal quantities and unit checks.
- Phase 0 builds claims and evidence references.
- Phase 0 builds deterministic canonical serialization and hashing.
- Phase 0 builds a minimal typed design model.
- Phase 0 builds one analytical solver capsule in-process.
- Phase 0 builds one immutable run bundle.
- Phase 0 builds a CLI.
- Phase 0 builds offline tests.
- Phase 0 acceptance requires deterministic reruns.
- Phase 0 acceptance requires rejection of unsourced controlled inputs.
- Phase 0 acceptance requires no third-party runtime dependency.

### 24.2 Phase 1: constrained part compiler

- Phase 1 duration target is six to ten weeks.
- Phase 1 adds versioned CIR schemas.
- Phase 1 adds a 2D constraint solver.
- Phase 1 adds an OCCT geometry adapter.
- Phase 1 adds datum, sketch, extrusion, revolution, and boolean features.
- Phase 1 adds stable semantic topology version one.
- Phase 1 adds STEP import and export.
- Phase 1 adds geometry validation reports.
- Phase 1 adds parameter perturbation tests.
- Phase 1 adds a local web viewer or desktop-integrated view.
- Phase 1 acceptance requires a curated set of industrial part families.

### 24.3 Phase 2: source-aware engineering

- Phase 2 duration target is six to ten weeks.
- Phase 2 adds source adapters for one manufacturer-authorized catalog and one internal pack.
- Phase 2 adds source snapshots and dimension extraction.
- Phase 2 adds conflict comparison.
- Phase 2 adds part-master approval.
- Phase 2 adds material packs.
- Phase 2 adds temperature-dependent properties.
- Phase 2 adds applicability rules.
- Phase 2 adds bilingual terminology and report output.
- Phase 2 acceptance requires fully traceable part and material dependencies.

### 24.4 Phase 3: verified structural and thermal workflows

- Phase 3 duration target is ten to sixteen weeks.
- Phase 3 adds Gmsh integration.
- Phase 3 adds one structural finite-element adapter.
- Phase 3 adds one thermal finite-element adapter.
- Phase 3 adds solver capsules and OCI packaging.
- Phase 3 adds verification test suites.
- Phase 3 adds mesh sensitivity workflows.
- Phase 3 adds uncertainty propagation for selected quantities.
- Phase 3 adds immutable native and normalized results.
- Phase 3 acceptance requires benchmark agreement within approved tolerances.

### 24.5 Phase 4: fluid, contamination, and cleaning

- Phase 4 duration target is twelve to twenty weeks.
- Phase 4 adds a CFD adapter.
- Phase 4 adds compartment contamination models.
- Phase 4 adds particle and species transport workflows.
- Phase 4 adds semantic surface budgets.
- Phase 4 adds cleanability geometry rules.
- Phase 4 adds cleaning coverage and drainability studies.
- Phase 4 adds sampling-plan linkage.
- Phase 4 adds validation-data comparison.
- Phase 4 acceptance requires physical fixture experiments for selected claims.

### 24.6 Phase 5: Solver Forge

- Phase 5 duration target is twelve to twenty weeks.
- Phase 5 adds solver registry search.
- Phase 5 adds generated-code sandboxing.
- Phase 5 adds capsule scaffolding.
- Phase 5 adds manufactured-solution tooling.
- Phase 5 adds convergence-study automation.
- Phase 5 adds SBOM, provenance, signing, and admission policy.
- Phase 5 adds the Q0 through Q5 promotion workflow.
- Phase 5 acceptance requires demonstrated containment and qualification of a novel solver capsule.

### 24.7 Phase 6: regulated lifecycle package

- Phase 6 duration target is twelve to twenty-four weeks and depends on the selected intended use.
- Phase 6 adds enterprise identity and segregation of duties.
- Phase 6 adds electronic-signature integration.
- Phase 6 adds complete audit-trail review workflows.
- Phase 6 adds validation lifecycle templates.
- Phase 6 adds change, deviation, and CAPA integrations.
- Phase 6 adds backup, restore, archive, and periodic-review evidence.
- Phase 6 adds air-gapped pack promotion.
- Phase 6 performs supplier and infrastructure qualification activities selected by the organization.
- Phase 6 acceptance is installation-specific and cannot be inherited from this source repository alone.

### 24.8 Phase 7: advanced engineering intelligence

- Phase 7 adds assembly reasoning at scale.
- Phase 7 adds nonlinear and coupled multiphysics workflows.
- Phase 7 adds optimization under hard engineering constraints.
- Phase 7 adds inspection-feedback learning outside qualified decision paths.
- Phase 7 adds design-family retrieval and reusable engineering patterns.
- Phase 7 adds fracture, fatigue, damage, and advanced material models based on demand and evidence.
- Phase 7 adds deeper manufacturing-process simulation where justified.
- Phase 7 remains gated by benchmark and customer evidence rather than roadmap ambition.

### 24.9 Team shape

- The initial core needs one geometry/CAD engineer.
- The initial core needs one scientific-computing engineer.
- The initial core needs one product/backend engineer.
- The initial core needs shared frontend capability.
- Materials work needs a materials-domain owner.
- Contamination and cleaning work needs pharmaceutical or clean-systems domain owners.
- Qualified deployment needs quality and validation ownership from the beginning, not at release time.
- Security and infrastructure expertise is required before Solver Forge executes external or generated code.
- A small team SHOULD deliver Phases 0 and 1 before expanding organization structure.

### 24.10 Cost controls

- AI usage MUST be metered by model, workflow, and project.
- Proposal caching SHOULD avoid repeated identical inference.
- Deterministic prechecks SHOULD run before expensive AI or solver calls.
- Low-fidelity physics SHOULD screen cases before high-fidelity runs.
- Artifact deduplication SHOULD reduce storage cost.
- User-visible estimates SHOULD precede unusually expensive runs.
- Budgets MUST never cause silent reduction of verification quality.
- Cost-driven approximations MUST be explicit choices.

---

## 25. First implementation slice

### 25.1 Slice objective

- The first slice proves the evidence-first deterministic spine before building a geometry UI.
- The slice models a rectangular axial member under tensile load.
- The slice uses exact decimal arithmetic for inputs and analytical outputs.
- The slice demonstrates typed quantities and unit compatibility.
- The slice demonstrates evidence-backed claims.
- The slice demonstrates deterministic canonical JSON and SHA-256 hashes.
- The slice demonstrates solver assumptions and formulas.
- The slice demonstrates an immutable evidence bundle.
- The slice runs offline.
- The slice uses only the Python standard library.

### 25.2 Slice inputs

- Input MUST include schema version.
- Input MUST include design identifier and title.
- Input MUST include an explicit effective timestamp supplied as run context.
- Input MUST include length claim.
- Input MUST include width claim.
- Input MUST include thickness claim.
- Input MUST include elastic-modulus claim.
- Input MUST include yield-strength claim.
- Input MUST include tensile-load claim.
- Every input claim MUST reference evidence.
- Demonstration evidence MUST be labeled synthetic.
- Decimal engineering values MUST be JSON strings.
- JSON floating-point values MUST be rejected.

### 25.3 Slice calculations

- Cross-sectional area equals width multiplied by thickness.
- Axial stress equals load divided by cross-sectional area.
- Axial strain equals stress divided by elastic modulus.
- Axial displacement equals strain multiplied by length.
- Yield safety factor equals yield strength divided by axial stress.
- The solver MUST verify positive geometry and material values.
- The solver MUST verify compatible quantity kinds.
- The solver MUST state uniform uniaxial stress assumption.
- The solver MUST state small-strain linear-elastic assumption.
- The solver MUST state absence of stress concentrations.
- The solver MUST state that buckling is outside tensile-only scope.
- The solver MUST state that the screen is not a release-grade general structural analysis.

### 25.4 Slice outputs

- Output MUST include input artifact digest.
- Output MUST include solver identifier and version.
- Output MUST include equations.
- Output MUST include assumptions.
- Output MUST include area in SI units.
- Output MUST include stress in SI units.
- Output MUST include strain.
- Output MUST include displacement in SI units.
- Output MUST include safety factor.
- Output MUST include derived claims with parent references.
- Output MUST include evidence manifest.
- Output MUST include deterministic result digest.
- Output MUST separate deterministic result from volatile execution envelope.

### 25.5 Slice tests

- Test unit conversion between millimeters and meters.
- Test unit conversion between megapascals and pascals.
- Test rejection of incompatible dimensions.
- Test rejection of floats.
- Test rejection of missing evidence.
- Test rejection of zero or negative geometry.
- Test known analytical stress.
- Test known analytical displacement.
- Test known safety factor.
- Test canonical hash independence from input object key order.
- Test hash change when a material value changes.
- Test identical result hash across repeated runs with identical context.
- Test CLI generation of an evidence bundle.
- Test CLI verification of a generated bundle.

### 25.6 Slice completion gate

- The full test suite MUST pass on Windows PowerShell.
- The full test suite SHOULD pass on Linux.
- The package MUST install in editable mode without external dependencies.
- The example MUST compile from a documented command.
- The generated bundle MUST verify against its manifest.
- The repository MUST contain no generated bundle by default unless intentionally included as a fixture.
- The README MUST state limitations without marketing inflation.

---

## 26. Decision log

- ADR-001: Use `Contrainte` as the project name.
- ADR-002: Keep AI outside authoritative computation and release.
- ADR-003: Use a modular monolith before considering microservices.
- ADR-004: Use a typed CIR rather than free-form CAD code as the central artifact.
- ADR-005: Use exact B-Rep through OCCT as the geometry authority.
- ADR-006: Use STEP AP242 as the preferred neutral exact exchange.
- ADR-007: Use QIF for model-based quality interoperability where appropriate.
- ADR-008: Use SI internally with explicit machine-readable units.
- ADR-009: Treat external dimensions and properties as evidence-backed claims.
- ADR-010: Package solvers as immutable signed capsules.
- ADR-011: Permit solver generation only in isolated research mode.
- ADR-012: Make contamination and cleaning first-class domains.
- ADR-013: Support French at the semantic and validation layers, not only the UI layer.
- ADR-014: Start with a dependency-free deterministic vertical slice.
- ADR-015: Do not make commits on the user's behalf.

---

## 27. Principal risks and mitigations

- Risk R-001: Exact CAD generation remains brittle on advanced topology.
- Mitigation R-001: constrain feature vocabulary, compile deterministically, perturb parameters, and report failures.
- Risk R-002: Persistent topology breaks after edits.
- Mitigation R-002: use semantic ancestry, adjacency signatures, robust selectors, and ambiguity blocks.
- Risk R-003: Source data are stale or inconsistent.
- Mitigation R-003: snapshot, grade, compare, pin, and require conflict adjudication.
- Risk R-004: Material properties are applied outside their domain.
- Mitigation R-004: encode full material state and machine-check applicability envelopes.
- Risk R-005: A converged solver result is mistaken for truth.
- Mitigation R-005: separate convergence, verification, validation, and uncertainty statuses.
- Risk R-006: Generated solver code compromises infrastructure.
- Mitigation R-006: execute only in credential-free, network-disabled, resource-limited sandboxes.
- Risk R-007: Generated solver code is promoted on shallow tests.
- Mitigation R-007: require staged Q0-Q5 evidence and independent approval.
- Risk R-008: Cleaning simulation creates false regulatory confidence.
- Mitigation R-008: label simulation as supporting evidence and require empirical validation records.
- Risk R-009: A broad "GMP compliant" claim misleads users.
- Mitigation R-009: use installation-specific intended use and validation language.
- Risk R-010: Draft regulatory guidance changes.
- Mitigation R-010: version regulatory profiles and distinguish draft from effective requirements.
- Risk R-011: Standards licensing prevents redistribution.
- Mitigation R-011: store references and customer-licensed packs with access controls.
- Risk R-012: French translation changes engineering meaning.
- Mitigation R-012: preserve originals, use canonical IDs, governed terminology, and domain review.
- Risk R-013: The project scope overwhelms the team.
- Mitigation R-013: ship evidence-first slices and qualify domains one at a time.
- Risk R-014: Architecture becomes a plugin maze.
- Mitigation R-014: require narrow contracts and real use cases before adding extension points.
- Risk R-015: Vendor APIs change or disappear.
- Mitigation R-015: use immutable source snapshots and offline packs.
- Risk R-016: Parallel solvers are not bitwise reproducible.
- Mitigation R-016: define numerical reproducibility envelopes and capture hardware/runtime context.
- Risk R-017: Audit storage becomes performative rather than reviewable.
- Mitigation R-017: build filtered review workflows and trace-based impact views.
- Risk R-018: Users overtrust AI explanations.
- Mitigation R-018: anchor explanations to claims, evidence, compiler diagnostics, and gates.
- Risk R-019: Qualification freezes useful innovation.
- Mitigation R-019: separate exploration from controlled promotion with explicit evidence gates.
- Risk R-020: Qualified dependencies accumulate unpatched vulnerabilities.
- Mitigation R-020: combine vulnerability monitoring with risk-based controlled upgrades and requalification.

---

## 28. Open design questions

- OQ-001: Select the exact OCCT Python binding after a licensing, maintenance, and topology-control spike.
- OQ-002: Decide whether the production CIR implementation begins with Pydantic or generated schema classes.
- OQ-003: Select the 2D constraint solver after benchmark prototypes.
- OQ-004: Define the minimum AP242 conformance class for first controlled export.
- OQ-005: Define the stable semantic topology algorithm and benchmark corpus.
- OQ-006: Select the first finite-element solver adapter based on validation corpus and deployment license.
- OQ-007: Select the first CFD solver adapter based on contamination and cleaning needs.
- OQ-008: Decide whether preCICE is introduced with the first coupled workflow or later.
- OQ-009: Select the first manufacturer-authorized catalog integration and negotiate terms.
- OQ-010: Define the internal material-pack license model.
- OQ-011: Select an electronic-signature provider for target deployments.
- OQ-012: Define tenant isolation requirements before enterprise hosting.
- OQ-013: Define regulated-record scope for the first pharmaceutical intended use.
- OQ-014: Define physical validation fixtures for spray coverage and particulate deposition.
- OQ-015: Define the public/private boundary if parts of the project are later open sourced.
- OQ-016: Decide how much proprietary standards content can be referenced without embedding it.
- OQ-017: Define acceptable numerical reproducibility for each solver capsule.
- OQ-018: Define bilingual controlled terminology ownership and review cadence.
- OQ-019: Define model-hosting constraints for sensitive aerospace and pharmaceutical projects.
- OQ-020: Define long-term archive strategy for executable solver environments.

---

## 29. Definition of done for the product vision

- The vision is not done when a prompt produces an attractive solid.
- The vision is not done when one solver produces a colored contour plot.
- The vision is not done when a report contains the word validated.
- The vision is done for a declared domain only when requirements, geometry, sources, materials, physics, uncertainty, tests, risks, and approvals remain connected.
- A domain is done only when unsupported inputs fail visibly.
- A domain is done only when ordinary edits preserve design intent.
- A domain is done only when independent benchmark cases pass predefined criteria.
- A domain is done only when results can be reproduced from immutable inputs.
- A qualified use is done only when the regulated organization approves its intended use and lifecycle evidence.
- Contrainte succeeds when it makes the honest engineering path easier than the plausible shortcut.
