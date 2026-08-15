# Contrainte component integration contract

## Purpose

Contrainte owns the engineering definition of a physical component. A consuming system may arrange, schedule, simulate, visualize, procure, operate, or monitor that component, but it must not silently replace the component's dimensional, material, solver, contamination, cleaning, or evidence semantics.

The public boundary supports legacy `contrainte.component-manifest/0.1` documents and emits `contrainte.component-manifest/0.2` for geometry-backed derivations. It lets another system identify a component release, verify content-addressed artifacts, discover typed interfaces, inspect lifecycle and qualification state, and enforce a conservative spatial envelope from reproduced exact geometry.

## Authority boundary

Contrainte is authoritative for:

- component identity and revision;
- exact engineering artifacts and their digests;
- component interface declarations;
- material, dimensional, physics, cleaning, and contamination evidence;
- engineering lifecycle and qualification state.

A factory or line system is authoritative for:

- occurrences of components in a facility;
- position, orientation, adjacency, zoning, and access envelopes;
- product routes and process steps;
- production calendars, demand, buffers, and staffing;
- line-level simulation assumptions and results;
- live telemetry bindings and operational state.

OpenUSD, IFC, AutomationML, OPC UA, and other exchange representations are projections of one or both authorities. They are not automatically authoritative merely because they contain a copy of a value.

## Identity and pinning

A consumer must pin all of the following:

1. the component schema version;
2. the component identifier;
3. the human-readable revision;
4. the canonical component-manifest digest;
5. the source engineering-bundle digest;
6. any artifact digest it actually consumes.

The identifier and revision are not sufficient integrity controls. The SHA-256 digest is the immutable identity of the exact content. A revised artifact requires a new digest even when a supplier or human revision label is unchanged.

## Qualification

The public schema distinguishes `unqualified_demonstration`, `engineering_reviewed`, and `qualified_for_intended_use`. A consuming system must not promote this value. It may impose a stricter gate. For example, a regulated factory project may reject every component not qualified for the project's explicit intended use.

Qualification is contextual. A component qualified for one product, material, cleaning regime, pressure range, or jurisdiction is not thereby qualified for another.

## Artifact locators

Artifact locators are retrieval hints, not identities. A locator may be a repository-relative path, package resource, PLM URI, object-store URI, or approved document-management identifier. Consumers verify retrieved bytes against the declared digest before use.

The `engineering_bundle` artifact matching `source_bundle_digest` is mandatory. Exact geometry, drawings, meshes, scenes, material records, solver capsules, and test records are added as separate artifacts when available.

For a locally derived component, `source_bundle_digest` is the SHA-256 of the serialized engineering-bundle file. The bundle's canonical semantic digest is retained separately as `metadata.engineering_bundle_content_digest`. This distinction lets a consumer prove both the exact retrieved bytes and the canonical engineering content they contain.

`contrainte component derive` accepts only a verified CAD, solid, or assembly bundle. It always emits `lifecycle_state=concept` and `qualification=unqualified_demonstration`; neither can be supplied by the request. It carries every bundle artifact into the manifest and writes repository-local locators only when the manifest is beside the bundle. `contrainte component verify` re-runs the source bundle verifier, checks every byte digest, rejects path traversal, rejects missing geometry, and detects lifecycle or qualification promotion.

## Exact geometry bounds

Schema 0.2 requires `geometry_bounds`. The minimum and maximum x, y, and z coordinates are decimal strings in millimetres in the engineering bundle's coordinate frame. Contrainte derives them from the reproduced Open CASCADE boundary representation; release requests cannot supply or override them. Local verification rebuilds the exact geometry and rejects altered bounds even when the surrounding manifest remains structurally valid.

Bounds are an axis-aligned broad-phase contract, not a substitute for shape-level collision, tolerance, motion-sweep, access, maintenance, or human-clearance analysis. A consumer may enlarge the envelope, but must not claim that a smaller envelope contains the component.

## Interfaces

Interfaces describe where a component connects to its environment. Kinds are mechanical, material, electrical, utility, control, safety, and spatial. Directions are input, output, or bidirectional.

Interface properties in schema 0.1 are strings. This is deliberate: the initial contract preserves vendor-neutral identifiers and declarations without pretending that a free-form property map is a complete physical port model. Later schemas will add typed quantities, coordinate frames, compatibility rules, and flow conservation while retaining deterministic migration paths.

## Determinism

Manifests are parsed without binary floating-point engineering values. Canonical JSON sorts object keys, preserves list order, emits UTF-8, and hashes the resulting bytes with SHA-256. Consumers should use `ComponentManifest.manifest_digest` rather than implementing a subtly different canonicalizer.

## Compatibility policy

- Patch releases may tighten validation for malformed documents but do not change valid schema 0.1 meaning.
- Additive Python APIs may appear in minor releases.
- A manifest shape or semantic change requires a new schema identifier.
- Consumers must reject unknown schema identifiers unless an explicit migration is available.
- Public deprecations receive a documented migration path before removal.

## Security and trust

A matching digest proves content integrity, not truth, safety, ownership, malware absence, or engineering fitness. Trust additionally depends on the evidence chain, artifact source, signatures or attestations, reviewer authority, and intended-use validation.

Network retrieval, signature verification, PLM authorization, and organization-specific approval policy are deliberately outside schema 0.1.

## Minimal use

```python
from contrainte import ComponentManifest

component = ComponentManifest.from_dict(document)
print(component.component_id)
print(component.manifest_digest)
```

The parsed object can be embedded by digest in a higher-level factory model. The higher-level system should retain the full manifest as evidence or keep a resolvable, verified artifact reference.
