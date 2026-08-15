# Design programs and agent isolation

Contrainte separates a design program from the engines that execute it. A program is a strict, canonical directed acyclic graph. It records the goal contract, task dependencies, declared inputs and outputs, execution authority, acceptance criteria, and human gates before expensive CAD or solver work begins.

The current schema is `contrainte.design-program/0.1`. Unknown fields fail validation. Work products have one producer, every consumed product must come from a direct dependency, self-dependencies fail, and cycles fail. Topological ordering and ready-task calculation are deterministic.

## Durable workspace

`DesignWorkspace` stores immutable bytes under `objects/sha256`, pins canonical program documents by digest, and writes a digest-protected run state. A run can be reopened without reconstructing state from a chat transcript. Required outputs must exist in the object store and match their declared media types before a task can complete.

The status vocabulary distinguishes `pending`, `running`, `completed`, `failed`, and `blocked`. Only completed dependencies unlock downstream tasks. Failed work can be retried. Interrupted, failed, or blocked tasks can be reset; completed work requires a new run rather than silent history rewriting.

## Codex and Claude adapters

Both adapters use installed subscription CLIs. Contrainte does not collect API keys.

Codex runs through non-interactive `codex exec` with an ephemeral session, JSONL events, a JSON output schema, a captured final message, and the `workspace-write` sandbox. Claude runs through print mode with streaming JSON, a JSON schema, `acceptEdits`, and no session persistence. Both receive an isolated task directory and an explicit prohibition on Git operations or writes outside that directory.

`dual` means two independent candidate artifacts. It is not a majority vote and does not establish engineering truth. A deterministic checker, independent solver, test, or named human gate must resolve consequential disagreements.

## CLI

```text
contrainte program validate examples/design-program.json
contrainte program ready examples/design-program.json --completed requirements
contrainte workspace init examples/design-program.json --root artifacts/design --run-id demo
contrainte workspace status examples/design-program.json --root artifacts/design --run-id demo
contrainte agents doctor
```

The public CLI deliberately does not turn an agent response directly into released CAD. Higher-level products may orchestrate candidate generation, but they must preserve this authority boundary.
