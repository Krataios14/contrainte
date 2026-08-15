from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import digest, digest_bytes, dumps_pretty, loads_strict
from .errors import InputError, IntegrityError
from .program import DesignProgram

WORKSPACE_SCHEMA = "contrainte.workspace/0.1"
RUN_SCHEMA = "contrainte.run-state/0.1"
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")
_RUN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_TERMINAL = {"completed", "blocked", "failed"}


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        raise InputError(f"cannot atomically write {path}: {exc}") from exc


@dataclass(frozen=True)
class ObjectRef:
    digest: str
    media_type: str
    size_bytes: int

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "object_ref") -> ObjectRef:
        if not isinstance(raw, dict) or set(raw) != {"digest", "media_type", "size_bytes"}:
            raise IntegrityError(
                f"{field} must contain exactly digest, media_type, and size_bytes"
            )
        declared = raw.get("digest")
        media_type = raw.get("media_type")
        size = raw.get("size_bytes")
        if not isinstance(declared, str) or not _DIGEST.fullmatch(declared):
            raise IntegrityError(f"{field}.digest is not a lowercase SHA-256 digest")
        if not isinstance(media_type, str) or not media_type:
            raise IntegrityError(f"{field}.media_type must be a non-empty string")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise IntegrityError(f"{field}.size_bytes must be a non-negative integer")
        return cls(digest=declared, media_type=media_type, size_bytes=size)

    def as_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
        }


class DesignWorkspace:
    """Durable, content-addressed state for resumable design programs."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @property
    def metadata_path(self) -> Path:
        return self.root / "workspace.json"

    def initialize(self) -> dict[str, Any]:
        for name in ("objects/sha256", "programs", "runs", "agent-sandboxes"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        metadata = {
            "schema_version": WORKSPACE_SCHEMA,
            "storage": "sha256",
            "object_layout": "objects/sha256/{first-two-hex}/{remaining-hex}",
        }
        if self.metadata_path.exists():
            current = self._read_document(self.metadata_path)
            if current != metadata:
                raise IntegrityError("workspace metadata is incompatible or has been modified")
        else:
            _atomic_write(self.metadata_path, dumps_pretty(metadata).encode("utf-8"))
        return metadata

    def put_bytes(self, content: bytes, media_type: str) -> ObjectRef:
        if not isinstance(media_type, str) or not media_type:
            raise InputError("media_type must be a non-empty string")
        self.initialize()
        declared = digest_bytes(content)
        target = self.object_path(declared)
        if target.exists():
            try:
                existing = target.read_bytes()
            except OSError as exc:
                raise InputError(f"cannot read stored object {target}: {exc}") from exc
            if existing != content:
                raise IntegrityError(f"content-address collision at {target}")
        else:
            _atomic_write(target, content)
        return ObjectRef(digest=declared, media_type=media_type, size_bytes=len(content))

    def put_document(self, document: Any, media_type: str = "application/json") -> ObjectRef:
        return self.put_bytes(dumps_pretty(document).encode("utf-8"), media_type)

    def object_path(self, declared: str) -> Path:
        match = _DIGEST.fullmatch(declared)
        if match is None:
            raise InputError("object digest must be a lowercase SHA-256 digest")
        hexadecimal = match.group(1)
        return self.root / "objects" / "sha256" / hexadecimal[:2] / hexadecimal[2:]

    def read_object(self, reference: ObjectRef) -> bytes:
        path = self.object_path(reference.digest)
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise IntegrityError(f"cannot read object {reference.digest}: {exc}") from exc
        if len(content) != reference.size_bytes:
            raise IntegrityError(f"stored object size mismatch: {reference.digest}")
        actual = digest_bytes(content)
        if actual != reference.digest:
            raise IntegrityError(
                f"stored object digest mismatch: declared {reference.digest}, actual {actual}"
            )
        return content

    def create_run(self, program: DesignProgram, run_id: str | None = None) -> dict[str, Any]:
        self.initialize()
        selected_id = run_id or f"run-{program.program_digest.removeprefix('sha256:')[:16]}"
        if not _RUN_ID.fullmatch(selected_id):
            raise InputError("run_id contains unsupported characters")
        program_path = self.root / "programs" / (
            program.program_digest.removeprefix("sha256:") + ".json"
        )
        program_content = dumps_pretty(program.as_dict()).encode("utf-8")
        if program_path.exists():
            if program_path.read_bytes() != program_content:
                raise IntegrityError("program document does not match its digest path")
        else:
            _atomic_write(program_path, program_content)

        state_path = self._state_path(selected_id)
        if state_path.exists():
            state = self.load_state(selected_id)
            if state["program_digest"] != program.program_digest:
                raise InputError(
                    f"run {selected_id!r} already belongs to a different design program"
                )
            return state
        state = {
            "schema_version": RUN_SCHEMA,
            "run_id": selected_id,
            "program_digest": program.program_digest,
            "sequence": 0,
            "tasks": {task.task_id: "pending" for task in program.tasks},
            "results": {},
        }
        self._write_state(selected_id, state)
        return state

    def load_state(self, run_id: str) -> dict[str, Any]:
        bundle = self._read_document(self._state_path(run_id))
        if not isinstance(bundle, dict) or set(bundle) != {"digest", "content"}:
            raise IntegrityError("run state must contain exactly digest and content")
        content = bundle.get("content")
        declared = bundle.get("digest")
        if not isinstance(content, dict) or not isinstance(declared, str):
            raise IntegrityError("run state bundle has invalid types")
        actual = digest(content)
        if actual != declared:
            raise IntegrityError(
                f"run state digest mismatch: declared {declared}, actual {actual}"
            )
        if content.get("schema_version") != RUN_SCHEMA or content.get("run_id") != run_id:
            raise IntegrityError("run state identity is invalid")
        return content

    def ready_tasks(self, program: DesignProgram, run_id: str) -> tuple[str, ...]:
        state = self.load_state(run_id)
        self._require_program(state, program)
        completed = {
            task_id for task_id, status in state["tasks"].items() if status == "completed"
        }
        graph_ready = program.ready_tasks(completed)
        return tuple(
            task.task_id
            for task in graph_ready
            if state["tasks"][task.task_id] in {"pending", "failed"}
        )

    def start_task(self, program: DesignProgram, run_id: str, task_id: str) -> Path:
        state = self.load_state(run_id)
        self._require_program(state, program)
        if task_id not in self.ready_tasks(program, run_id):
            raise InputError(f"task {task_id!r} is not ready")
        state["tasks"][task_id] = "running"
        state["sequence"] += 1
        self._write_state(run_id, state)
        sandbox = self.root / "agent-sandboxes" / run_id / task_id
        sandbox.mkdir(parents=True, exist_ok=True)
        if (sandbox / ".git").exists():
            raise IntegrityError("agent sandbox must not contain a Git repository")
        return sandbox

    def finish_task(
        self,
        program: DesignProgram,
        run_id: str,
        task_id: str,
        outputs: Mapping[str, ObjectRef],
        *,
        status: str = "completed",
        summary: str = "",
    ) -> dict[str, Any]:
        if status not in _TERMINAL:
            raise InputError(
                "terminal task status must be 'completed', 'blocked', or 'failed'"
            )
        state = self.load_state(run_id)
        self._require_program(state, program)
        if state["tasks"].get(task_id) != "running":
            raise InputError(f"task {task_id!r} is not running")
        task = next((item for item in program.tasks if item.task_id == task_id), None)
        if task is None:
            raise InputError(f"unknown task: {task_id}")
        declared = {product.product_id: product for product in task.outputs}
        unknown = sorted(set(outputs) - set(declared))
        if unknown:
            raise InputError(f"task result contains undeclared products: {', '.join(unknown)}")
        required = {key for key, value in declared.items() if value.required}
        missing = sorted(required - set(outputs))
        if status == "completed" and missing:
            raise InputError(f"task result is missing required products: {', '.join(missing)}")
        for product_id, reference in outputs.items():
            if declared[product_id].media_type != reference.media_type:
                raise InputError(f"media type mismatch for work product {product_id!r}")
            self.read_object(reference)
        result = {
            "status": status,
            "summary": summary,
            "outputs": {key: value.as_dict() for key, value in sorted(outputs.items())},
        }
        state["tasks"][task_id] = status
        state["results"][task_id] = result
        state["sequence"] += 1
        self._write_state(run_id, state)
        return result

    def reset_task(self, program: DesignProgram, run_id: str, task_id: str) -> None:
        state = self.load_state(run_id)
        self._require_program(state, program)
        current = state["tasks"].get(task_id)
        if current == "completed":
            raise InputError("completed tasks cannot be reset without creating a new run")
        if current not in {"running", "blocked", "failed"}:
            raise InputError(f"task {task_id!r} is not resettable from status {current!r}")
        state["tasks"][task_id] = "pending"
        state["results"].pop(task_id, None)
        state["sequence"] += 1
        self._write_state(run_id, state)

    def _require_program(self, state: Mapping[str, Any], program: DesignProgram) -> None:
        if state.get("program_digest") != program.program_digest:
            raise InputError("run state does not belong to this design program")
        expected = {task.task_id for task in program.tasks}
        tasks = state.get("tasks")
        if not isinstance(tasks, dict) or set(tasks) != expected:
            raise IntegrityError("run task set does not match the pinned design program")

    def _state_path(self, run_id: str) -> Path:
        if not _RUN_ID.fullmatch(run_id):
            raise InputError("run_id contains unsupported characters")
        return self.root / "runs" / run_id / "state.json"

    def _write_state(self, run_id: str, content: Mapping[str, Any]) -> None:
        bundle = {"digest": digest(content), "content": dict(content)}
        _atomic_write(self._state_path(run_id), dumps_pretty(bundle).encode("utf-8"))

    @staticmethod
    def _read_document(path: Path) -> Any:
        try:
            return loads_strict(path.read_bytes())
        except OSError as exc:
            raise InputError(f"cannot read {path}: {exc}") from exc
