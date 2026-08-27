# Component-manifest JSON Schemas

Contrainte publishes closed JSON Schemas for every supported component-manifest
version. They use JSON Schema Draft 2020-12 and describe the public interchange
shape accepted by `ComponentManifest.from_dict`:

| Manifest | Logical schema identifier | Committed fixture |
| --- | --- | --- |
| `contrainte.component-manifest/0.1` | `urn:contrainte:schema:component-manifest:0.1` | `schemas/component-manifest-0.1.schema.json` |
| `contrainte.component-manifest/0.2` | `urn:contrainte:schema:component-manifest:0.2` | `schemas/component-manifest-0.2.schema.json` |
| `contrainte.component-manifest/0.3` | `urn:contrainte:schema:component-manifest:0.3` | `schemas/component-manifest-0.3.schema.json` |
| `contrainte.component-manifest/0.4` | `urn:contrainte:schema:component-manifest:0.4` | `schemas/component-manifest-0.4.schema.json` |

The schema version must be selected explicitly. There is no moving `latest`
alias.

## Deterministic export

Write schema 0.4 to standard output:

```console
python -m contrainte component schema contrainte.component-manifest/0.4
```

Write the same bytes to a file:

```console
python -m contrainte component schema contrainte.component-manifest/0.4 \
  --output component-manifest-0.4.schema.json
```

The Python API exposes both a fresh dictionary and the deterministic text form:

```python
from contrainte import (
    component_manifest_json_schema,
    component_manifest_json_schema_text,
    export_component_manifest_json_schema,
)

schema = component_manifest_json_schema("contrainte.component-manifest/0.4")
text = component_manifest_json_schema_text("contrainte.component-manifest/0.4")
export_component_manifest_json_schema(
    "contrainte.component-manifest/0.4",
    "component-manifest-0.4.schema.json",
)
```

The text export has sorted object keys, two-space indentation, UTF-8 content, LF
line endings, and one trailing newline. It contains no timestamps, filesystem
paths, locale-sensitive data, or optional runtime-provider state. The committed
fixtures are checked byte-for-byte after newline normalization against the same
generator to detect drift.

Schema export and manifest parsing remain dependency-free. Contrainte does not
install or invoke a JSON Schema validator at runtime; consumers may use any
Draft 2020-12 implementation.

## Structural validation and semantic validation

The schemas fail closed on unknown object fields and encode version-specific
shape: geometry bounds begin in 0.2, exact interface frames begin in 0.3, and
strict topology attachments plus their derived evidence begin in 0.4. They also
encode lexical digest and exact-scalar forms, enum domains, required fields,
closed attachment selectors, and the 0.4 interface-count limit.

JSON Schema cannot reproduce all exact, cross-field engineering checks. Every
export therefore carries the explicit
`x-contrainte-runtime-only-semantic-invariants` annotation. The runtime parser
continues to enforce:

- unique artifact and interface identifiers;
- exact linkage of `source_bundle_digest` to one `engineering_bundle` artifact;
- finite geometry values and strictly positive extent on every axis;
- reduced rational spellings, exact unit and orthogonal frame axes, and a
  right-handed basis;
- containment of each frame origin in its geometry bounds;
- unit attachment directions and selector/evidence surface and direction
  correspondence; and
- equality of topology evidence points and directions to the bound frame origin
  and z-axis.

A JSON Schema success is shape validation, not engineering qualification,
topology reproduction, source-artifact verification, or release approval.
Consumers that need Contrainte's semantics must also parse the document with
`ComponentManifest.from_dict`; local releases require the stronger evidence
chain checked by `contrainte component verify`.

## Verification

The focused dependency-free tests are:

```console
python -m unittest discover -s tests -p "test_component_schema.py" -v
```

When the optional third-party `jsonschema` package is present, the same suite
also checks each export against the official Draft 2020-12 meta-schema and
validates positive and negative manifest examples. Its absence does not change
the Contrainte runtime or parser tests.
