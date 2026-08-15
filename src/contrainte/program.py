from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .canonical import digest, loads_strict
from .errors import InputError

PROGRAM_SCHEMA = "contrainte.design-program/0.1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class TaskKind(str, Enum):
    REQUIREMENTS = "requirements"
    RESEARCH = "research"
    CAD = "cad"
    MATERIALS = "materials"
    SIMULATION = "simulation"
    OPTIMIZATION = "optimization"
    VERIFICATION = "verification"
    INTEGRATION = "integration"
    HUMAN_REVIEW = "human_review"


class ExecutionAuthority(str, Enum):
    DETERMINISTIC = "deterministic"
    CODEX = "codex"
    CLAUDE = "claude"
    DUAL = "dual"
    HUMAN = "human"


def _object(raw: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, dict):
        raise InputError(f"{field} must be an object")
    return raw


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise InputError(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _string(raw: Mapping[str, Any], name: str, field: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{field}.{name} must be a non-empty string")
    return value.strip()


def _identifier(value: str, field: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise InputError(
            f"{field} must start with a lowercase letter and contain only lowercase "
            "letters, digits, '.', '_' or '-'"
        )
    return value


def _strings(raw: Any, field: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(
        isinstance(item, str) and item.strip() for item in raw
    ):
        raise InputError(f"{field} must be a list of non-empty strings")
    values = tuple(item.strip() for item in raw)
    if non_empty and not values:
        raise InputError(f"{field} must not be empty")
    if len(values) != len(set(values)):
        raise InputError(f"{field} values must be unique")
    return values


def _string_map(raw: Any, field: str) -> Mapping[str, str]:
    if not isinstance(raw, dict) or not all(
        isinstance(key, str)
        and key
        and isinstance(value, str)
        and value
        for key, value in raw.items()
    ):
        raise InputError(f"{field} must map non-empty strings to non-empty strings")
    return dict(raw)


@dataclass(frozen=True)
class GoalContract:
    statement: str
    locale: str
    intended_use: str
    success_criteria: tuple[str, ...]
    constraints: tuple[str, ...]
    assumptions: tuple[str, ...]
    exclusions: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "goal") -> GoalContract:
        value = _object(raw, field)
        _reject_unknown(
            value,
            {
                "statement",
                "locale",
                "intended_use",
                "success_criteria",
                "constraints",
                "assumptions",
                "exclusions",
            },
            field,
        )
        return cls(
            statement=_string(value, "statement", field),
            locale=_string(value, "locale", field),
            intended_use=_string(value, "intended_use", field),
            success_criteria=_strings(
                value.get("success_criteria"),
                f"{field}.success_criteria",
                non_empty=True,
            ),
            constraints=_strings(value.get("constraints", []), f"{field}.constraints"),
            assumptions=_strings(value.get("assumptions", []), f"{field}.assumptions"),
            exclusions=_strings(value.get("exclusions", []), f"{field}.exclusions"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "locale": self.locale,
            "intended_use": self.intended_use,
            "success_criteria": list(self.success_criteria),
            "constraints": list(self.constraints),
            "assumptions": list(self.assumptions),
            "exclusions": list(self.exclusions),
        }


@dataclass(frozen=True)
class WorkProduct:
    product_id: str
    role: str
    media_type: str
    required: bool

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> WorkProduct:
        value = _object(raw, field)
        _reject_unknown(value, {"product_id", "role", "media_type", "required"}, field)
        required = value.get("required")
        if not isinstance(required, bool):
            raise InputError(f"{field}.required must be a boolean")
        return cls(
            product_id=_identifier(_string(value, "product_id", field), f"{field}.product_id"),
            role=_identifier(_string(value, "role", field), f"{field}.role"),
            media_type=_string(value, "media_type", field),
            required=required,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "role": self.role,
            "media_type": self.media_type,
            "required": self.required,
        }


@dataclass(frozen=True)
class DesignTask:
    task_id: str
    title: str
    objective: str
    kind: TaskKind
    authority: ExecutionAuthority
    depends_on: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[WorkProduct, ...]
    acceptance_criteria: tuple[str, ...]
    human_gate: bool
    instructions: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str) -> DesignTask:
        value = _object(raw, field)
        _reject_unknown(
            value,
            {
                "task_id",
                "title",
                "objective",
                "kind",
                "authority",
                "depends_on",
                "inputs",
                "outputs",
                "acceptance_criteria",
                "human_gate",
                "instructions",
            },
            field,
        )
        try:
            kind = TaskKind(_string(value, "kind", field))
        except ValueError as exc:
            raise InputError(f"{field}.kind is unsupported: {value.get('kind')!r}") from exc
        try:
            authority = ExecutionAuthority(_string(value, "authority", field))
        except ValueError as exc:
            raise InputError(
                f"{field}.authority is unsupported: {value.get('authority')!r}"
            ) from exc
        human_gate = value.get("human_gate")
        if not isinstance(human_gate, bool):
            raise InputError(f"{field}.human_gate must be a boolean")
        if authority is ExecutionAuthority.HUMAN and not human_gate:
            raise InputError(f"{field} with human authority must set human_gate=true")

        outputs_raw = value.get("outputs")
        if not isinstance(outputs_raw, list) or not outputs_raw:
            raise InputError(f"{field}.outputs must be a non-empty list")
        outputs = tuple(
            WorkProduct.from_dict(item, field=f"{field}.outputs[{index}]")
            for index, item in enumerate(outputs_raw)
        )
        output_ids = [item.product_id for item in outputs]
        if len(output_ids) != len(set(output_ids)):
            raise InputError(f"{field}.output product identifiers must be unique")

        return cls(
            task_id=_identifier(_string(value, "task_id", field), f"{field}.task_id"),
            title=_string(value, "title", field),
            objective=_string(value, "objective", field),
            kind=kind,
            authority=authority,
            depends_on=_strings(value.get("depends_on", []), f"{field}.depends_on"),
            inputs=_strings(value.get("inputs", []), f"{field}.inputs"),
            outputs=outputs,
            acceptance_criteria=_strings(
                value.get("acceptance_criteria"),
                f"{field}.acceptance_criteria",
                non_empty=True,
            ),
            human_gate=human_gate,
            instructions=_strings(value.get("instructions", []), f"{field}.instructions"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "objective": self.objective,
            "kind": self.kind.value,
            "authority": self.authority.value,
            "depends_on": list(self.depends_on),
            "inputs": list(self.inputs),
            "outputs": [item.as_dict() for item in self.outputs],
            "acceptance_criteria": list(self.acceptance_criteria),
            "human_gate": self.human_gate,
            "instructions": list(self.instructions),
        }


@dataclass(frozen=True)
class DesignProgram:
    schema_version: str
    program_id: str
    revision: str
    goal: GoalContract
    tasks: tuple[DesignTask, ...]
    metadata: Mapping[str, str]

    @classmethod
    def from_dict(cls, raw: Any, *, field: str = "program") -> DesignProgram:
        value = _object(raw, field)
        _reject_unknown(
            value,
            {"schema_version", "program_id", "revision", "goal", "tasks", "metadata"},
            field,
        )
        schema = _string(value, "schema_version", field)
        if schema != PROGRAM_SCHEMA:
            raise InputError(f"unsupported design-program schema: {schema!r}")
        tasks_raw = value.get("tasks")
        if not isinstance(tasks_raw, list) or not tasks_raw:
            raise InputError(f"{field}.tasks must be a non-empty list")
        tasks = tuple(
            DesignTask.from_dict(item, field=f"{field}.tasks[{index}]")
            for index, item in enumerate(tasks_raw)
        )
        task_ids = [item.task_id for item in tasks]
        if len(task_ids) != len(set(task_ids)):
            raise InputError(f"{field}.task identifiers must be unique")
        known_tasks = set(task_ids)
        produced_by: dict[str, str] = {}
        for task in tasks:
            if task.task_id in task.depends_on:
                raise InputError(f"task {task.task_id!r} cannot depend on itself")
            missing = sorted(set(task.depends_on) - known_tasks)
            if missing:
                raise InputError(
                    f"task {task.task_id!r} depends on unknown tasks: {', '.join(missing)}"
                )
            for output in task.outputs:
                previous = produced_by.get(output.product_id)
                if previous is not None:
                    raise InputError(
                        f"work product {output.product_id!r} is produced by both "
                        f"{previous!r} and {task.task_id!r}"
                    )
                produced_by[output.product_id] = task.task_id
        for task in tasks:
            for product_id in task.inputs:
                producer = produced_by.get(product_id)
                if producer is None:
                    raise InputError(
                        f"task {task.task_id!r} requires unknown work product {product_id!r}"
                    )
                if producer not in task.depends_on:
                    raise InputError(
                        f"task {task.task_id!r} consumes {product_id!r} but does not "
                        f"depend on producer {producer!r}"
                    )
        program = cls(
            schema_version=schema,
            program_id=_identifier(_string(value, "program_id", field), f"{field}.program_id"),
            revision=_string(value, "revision", field),
            goal=GoalContract.from_dict(value.get("goal"), field=f"{field}.goal"),
            tasks=tasks,
            metadata=_string_map(value.get("metadata", {}), f"{field}.metadata"),
        )
        program.topological_order()
        return program

    @property
    def program_digest(self) -> str:
        return digest(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "program_id": self.program_id,
            "revision": self.revision,
            "goal": self.goal.as_dict(),
            "tasks": [item.as_dict() for item in self.tasks],
            "metadata": dict(self.metadata),
        }

    def topological_order(self) -> tuple[str, ...]:
        dependencies = {task.task_id: set(task.depends_on) for task in self.tasks}
        order: list[str] = []
        while dependencies:
            ready = sorted(task_id for task_id, deps in dependencies.items() if not deps)
            if not ready:
                cycle_members = ", ".join(sorted(dependencies))
                raise InputError(f"design program contains a dependency cycle: {cycle_members}")
            order.extend(ready)
            for task_id in ready:
                dependencies.pop(task_id)
            for deps in dependencies.values():
                deps.difference_update(ready)
        return tuple(order)

    def ready_tasks(self, completed: Iterable[str]) -> tuple[DesignTask, ...]:
        completed_set = set(completed)
        known = {task.task_id for task in self.tasks}
        unknown = sorted(completed_set - known)
        if unknown:
            raise InputError(f"completed set contains unknown tasks: {', '.join(unknown)}")
        return tuple(
            task
            for task in sorted(self.tasks, key=lambda item: item.task_id)
            if task.task_id not in completed_set
            and set(task.depends_on).issubset(completed_set)
        )


def load_program(path: str | Path) -> DesignProgram:
    source = Path(path)
    try:
        raw = loads_strict(source.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read design program {source}: {exc}") from exc
    return DesignProgram.from_dict(raw)
