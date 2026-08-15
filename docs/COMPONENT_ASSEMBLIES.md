# Geometry-backed component assemblies

`contrainte.component-assembly/0.1` closes the public boundary between exact
semantic interface placement and local Open CASCADE geometry. It does not search
for a new pose. It accepts a previously solved interface assembly, independently
replays that finite exact search result, verifies every local component release,
reconstructs every component B-rep from its source engineering bundle, and only
then evaluates interference and clearance.

The output is `contrainte.component-assembly-bundle/0.1`. Every output remains an
`unqualified_demonstration` regardless of the text present in an input component.

## Input contract

A component assembly declares:

- a stable assembly identifier, revision, and title;
- digest-bound source files for one `contrainte.interface-assembly/0.1` document
  and one `contrainte.interface-assembly-result/0.1` document;
- one sorted local component-manifest binding for every interface occurrence;
- a non-negative exact rational default clearance in millimetres; and
- optional sorted, unique pair-specific exact rational clearances.

The interface result must be `solved`. Inconclusive and unsatisfiable results are
not spatial candidates and cannot be compiled.

Each component binding contains the occurrence ID, manifest locator, exact file
digest, and canonical manifest digest. The local file must parse as
`contrainte.component-manifest/0.3`, must pass the complete local release verifier,
and must exactly equal the component embedded in the corresponding interface
occurrence. Matching an identifier or revision is insufficient.

Version 0.1 accepts two to 64 component bindings. Every pair is checked, so 64
components imply 2,016 pair evaluations. Locators are bounded relative POSIX paths
under an explicit source root. Absolute paths, parent traversal, backslashes,
Windows reserved names, links, reparse points, hard-linked source files, missing
files, and source documents over four MiB are rejected.

The compiler consumes each interface document, result, and manifest from one
bounded byte snapshot. File identity, size, modification time, link count, and
open-handle/path continuity are checked around the read; the declared digest is
computed from those consumed bytes. Release artifacts receive the same treatment
before a private snapshot of the complete release is replayed. A release may
contain at most 128 artifacts, each engineering bundle is limited to four MiB,
each other release artifact to 64 MiB, and the captured release chain to 128 MiB.
Those limits are checked from file metadata before allocating or reading the
affected file.

## Exact authority and kernel projection

The solved occurrence transforms retain Contrainte's exact rational, proper,
right-handed basis as semantic authority. The compiler does not convert that basis
to Euler angles. It writes the three basis columns and exact translation directly
to an Open CASCADE `gp_Trsf` matrix.

Open CASCADE uses binary double precision. Consequently, the B-rep placement is a
kernel projection of the exact pose rather than a claim that arbitrary rationals
are represented exactly in binary. Contrainte reads the matrix back, compares all
twelve binary coefficients as exact `Fraction.from_float` values against the exact
rational transform, and rejects a projection whose maximum coefficient error
exceeds `0.000000000001`. This acceptance decision performs no decimal rounding.
Only its display value is rendered under a closed, pinned, trap-disabled decimal
context. The evidence bundle retains the exact transform, projection method,
measured error, and limit for every occurrence.

This separation is intentional:

1. interface compatibility, mate equations, anchor preservation, candidate order,
   and graph closure are exact rational claims;
2. the B-rep transform is an explicit, checked numerical projection; and
3. collision and distance are Open CASCADE measurements with declared kernel-noise
   thresholds.

## Geometry authority

The compiler never treats a component STL or an unverified supplier STEP file as
geometry authority. For every binding it:

1. verifies the manifest's exact bytes against the binding;
2. verifies lifecycle and qualification cannot have been promoted;
3. verifies the source engineering-bundle byte digest;
4. runs the appropriate CAD, sketch, solid-program, or assembly bundle verifier;
5. verifies every local artifact digest;
6. reconstructs the B-rep from the normalized engineering definition; and
7. proves the reconstructed bounds still equal the manifest bounds.

The currently supported source bundles are:

- `contrainte.cad-bundle/0.1`;
- `contrainte.sketch-bundle/0.1` and `/0.2`;
- `contrainte.solid-bundle/0.1`; and
- `contrainte.assembly-bundle/0.1`.

`reproduce_local_component_shape` exposes this same verified handoff to other
deterministic integration engines. That handoff captures the bounded manifest and
complete release chain once, verifies private copies of those exact bytes, and
rebuilds the shape from the same verified engineering-bundle document. It never
verifies one manifest and then rereads another from the caller's path.

## Spatial decisions

Every unordered occurrence pair is evaluated exhaustively. The compiler records:

- Open CASCADE minimum distance;
- required exact rational clearance;
- boolean-common volume; and
- `passed`, `interference`, or `clearance_violation` status.

Kernel distance and common-solid volume values are converted directly from their
binary floats into exact fractions. Common volumes are summed and both thresholds
are evaluated as rational comparisons, independent of ambient decimal precision,
rounding, flags, or traps. The decimal strings in the report are a separately
quantized display and have no authority over pass/fail decisions.

Common volume above `0.000001 mm3` is interference. When common volume remains
within that kernel-noise limit, measured distance plus `0.000001 mm` must be at
least the exact required clearance. These thresholds absorb numerical kernel noise;
they are not dimensional tolerances, fit allowances, or manufacturing acceptance
limits.

Any failed pair prevents STEP, STL, and bundle export. A successful compilation
emits deterministic normalized STEP, deterministic STL, artifact hashes, source
records, exact semantic digests, kernel identity, complete spatial analysis, and a
digest over the whole bundle content.

## Independent replay

Verification reopens every digest-bound source beneath the supplied source root,
replays the independent interface-result oracle, re-verifies every local release,
and rebuilds every B-rep. Its exact-to-kernel matrix construction and pair loop are
separate from the compiler implementations. It compares the reproduced analysis,
source records, semantic digests, kernel identity, check set, and artifact bytes
with the stored bundle.

Artifact verification is geometry-backed rather than hash-only. The verifier
exports a new normalized STEP and STL from the independently rebuilt compound in
a private temporary directory, then requires every declared descriptor and every
published byte to equal that regeneration. STEP and STL are individually limited
to 64 MiB, while request and bundle documents are limited to four MiB. Output
directories and files must be direct; links, reparse points, and hard-linked
artifacts are rejected.

A rehashed bundle with altered transforms, clearances, distances, source records,
checks, or substituted artifacts therefore does not verify.

## CLI

The source root is explicit so locators remain portable and no absolute host path
enters the evidence identity:

```powershell
python -m contrainte cad compile examples/mounting-plate.json --output-dir artifacts/component-pair-source
python -m contrainte component derive artifacts/component-pair-source/plate.demo.cad-bundle.json examples/component-pair-left-release.json --output artifacts/component-pair-source/left.component.json
python -m contrainte component derive artifacts/component-pair-source/plate.demo.cad-bundle.json examples/component-pair-right-release.json --output artifacts/component-pair-source/right.component.json
python -m contrainte component-assembly prepare examples/component-pair-interface.json examples/component-pair-assembly.json --source-root . --output-dir artifacts/component-pair-prepared
python -m contrainte interface-assembly verify artifacts/component-pair-prepared/component-pair.interface.json artifacts/component-pair-prepared/component-pair.interface-result.json
python -m contrainte component-assembly compile artifacts/component-pair-prepared/component-pair.component-assembly.json --source-root . --output-dir artifacts/component-pair-assembly
python -m contrainte component-assembly verify artifacts/component-pair-assembly/component-pair.component-assembly-bundle.json --source-root .
```

The first two JSON arguments to `prepare` are authoring templates. Their embedded
component manifests and digest fields show the intended topology and bindings;
they are not portable compile inputs. Exact CAD serialization can differ between
supported Open CASCADE platforms, so a release freshly derived on the current
platform can legitimately have different artifact, source-bundle, manifest-file,
and manifest semantic digests.

`prepare` resolves both templates and every binding locator beneath the explicit
source root. It stable-captures and fully reproduces each current local release,
replaces every interface occurrence's embedded manifest, solves the resulting
exact interface assembly, and independently replays the result. It then emits
three canonical files beneath the source root:

- `<assembly-id>.interface.json` with the current embedded manifests;
- `<assembly-id>.interface-result.json` with the newly replayed exact solution;
  and
- `<assembly-id>.component-assembly.json` with exact file digests for both files
  plus the current file and semantic digest for every component manifest.

The prepared component assembly is strictly reloaded and its entire source
context is replayed before the command succeeds. Preparation does not weaken the
compile schema, accept an unpinned source, or make platform-independent geometry
claims. It is a deterministic authoring step that creates a fully digest-bound
compile input for the platform-derived local releases actually present. Repeating
it over unchanged snapshots emits byte-identical documents. The CI workflow uses
that prepared input to exercise the complete clean-clone chain.

The output directory is an exact three-file transaction. It must be absent,
empty, or contain exactly one prior direct, single-link prepared set; partial
sets, foreign entries, links, reparse points, hard links, and non-regular entries
are rejected. All three canonical byte strings are first written and stably
verified in an unpredictable private direct sibling directory. POSIX transaction
directories and files are created with owner-only permissions; Windows uses the
calling identity's inherited ACL together with retained no-delete handles. The
complete staged directory is then promoted as one set. If staging, promotion,
strict reload, source replay, final capture, or deletion of the replaced backup
fails, the cached previous complete directory is reconstructed and restored
byte-for-byte as the sole visible destination, or no new visible directory
remains when there was no prior set.

Preparation binds the identity and direct-directory state of the source root and
every traversed template, release, and output ancestor. Those bindings are
rechecked before and after stable reads, release replay, staging writes,
promotion, strict context replay, and final capture. Replacing an ancestor with a
different directory, symbolic link, or Windows reparse point aborts the
transaction. The returned file digests are calculated from the final stable
canonical snapshots, not from earlier in-memory intentions or semantic reparses.
On POSIX, visible-name checks compare the retained descriptor with `stat` through
its retained parent descriptor, so preparation works on Linux, macOS, and BSD and
does not require procfs.

This transaction boundary rejects every pre-existing or observed hard-link alias.
It is not an operating-system containment boundary against a privileged process,
or a cooperating concurrent process running as the same filesystem identity,
that discovers a private staged file and races an alias into existence between a
link-count check and subsequent use, or after the final check. Run authoring in a
workspace whose write access is limited to the trusted build identity when that
threat is relevant.

## Deliberate limits and nonclaims

Version 0.1 proves a nominal static geometry condition for exact locally released
component definitions at one solved pose. It does not prove:

- manufacturing tolerances, fits, backlash, preload, fasteners, seals, or joints;
- motion sweeps, deformation, vibration, fatigue, impact, or failure modes;
- structural, thermal, fluid, electromagnetic, control, contamination, or cleaning
  behaviour;
- access, service, installation, tooling, ergonomic, guarding, or routing space;
- that an interface frame is attached to a persistent B-rep face or edge;
- the truth, authorship, authenticity, or legal usability of source evidence;
- safety, regulatory compliance, GMP validation, or fitness for manufacture; or
- collision freedom for unmodelled cables, fluids, people, tools, stock, or the
  environment.

Protected reference components backed only by drawings, measurements, scans, or
Gaussian splats are not silently promoted into exact B-reps by this engine. Their
occupied, keepout, access, and service envelopes require a separate conservative
spatial-evidence integration contract.
