from __future__ import annotations

import copy
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import contrainte
from contrainte.canonical import dumps_pretty, loads_strict
from contrainte.cli import main as cli_main
from contrainte.errors import InputError
from contrainte.exact_transform import ExactRigidTransform
from contrainte.interface_assembly import (
    INTERFACE_ASSEMBLY_SCHEMA,
    MAX_ALTERNATIVES_PER_MATE,
    MAX_ARTIFACTS_PER_COMPONENT,
    MAX_CANDIDATE_BUDGET,
    MAX_CAPABILITIES_PER_COMPONENT,
    MAX_COMPONENT_METADATA_FIELDS,
    MAX_EXACT_MATE_EVALUATIONS,
    MAX_INTERFACE_PROPERTIES,
    MAX_INTERFACES_PER_COMPONENT,
    MAX_MATES,
    MAX_OCCURRENCES,
    MAX_PROPERTIES_PER_MATE,
    InconclusiveReason,
    InterfaceAssembly,
    InterfaceAssemblyResult,
    InterfaceEndpoint,
    SelectedMateAlternative,
    SolvedOccurrence,
    SolveStatus,
    solve_interface_assembly,
    verify_interface_assembly_result,
    verify_interface_assembly_solution,
)

DIGEST = "sha256:" + "1" * 64


def rational_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def transform(
    x: int | Fraction = 0,
    y: int | Fraction = 0,
    z: int | Fraction = 0,
    *,
    basis: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": {
            "x": rational_text(Fraction(x)),
            "y": rational_text(Fraction(y)),
            "z": rational_text(Fraction(z)),
        },
        "basis": basis
        or {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def frame(
    origin: tuple[str, str, str] = ("0", "0", "0"),
    *,
    basis: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "reference": "engineering_bundle",
        "unit": "mm",
        "origin": dict(zip(("x", "y", "z"), origin, strict=True)),
        "basis": basis
        or {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def interface(
    interface_id: str,
    direction: str,
    *,
    origin: tuple[str, str, str] = ("0", "0", "0"),
    kind: str = "mechanical",
    medium: str = "dry",
    properties: dict[str, str] | None = None,
    basis: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "interface_id": interface_id,
        "kind": kind,
        "direction": direction,
        "medium": medium,
        "properties": properties or {"standard": "ISO", "size": "M8"},
        "frame": frame(origin, basis=basis),
    }


def component(
    component_id: str, interfaces: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": "contrainte.component-manifest/0.3",
        "component_id": component_id,
        "revision": "A",
        "title": component_id,
        "lifecycle_state": "released",
        "qualification": "engineering_reviewed",
        "source_bundle_digest": DIGEST,
        "artifacts": [
            {
                "artifact_id": "bundle",
                "role": "engineering_bundle",
                "media_type": "application/json",
                "digest": DIGEST,
                "locator": "bundle.json",
            }
        ],
        "interfaces": interfaces,
        "capabilities": [],
        "geometry_bounds": {
            "frame": "engineering_bundle",
            "unit": "mm",
            "minimum": {"x": "-100", "y": "-100", "z": "-100"},
            "maximum": {"x": "100", "y": "100", "z": "100"},
        },
        "metadata": {},
    }


def occurrence(
    occurrence_id: str,
    interfaces: list[dict[str, object]],
    *,
    anchor: dict[str, object] | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "occurrence_id": occurrence_id,
        "component": component(f"component-{occurrence_id}", interfaces),
    }
    if anchor is not None:
        document["anchor_transform"] = anchor
    return document


def endpoint(occurrence_id: str, interface_id: str) -> dict[str, str]:
    return {"occurrence_id": occurrence_id, "interface_id": interface_id}


def alternative(
    alternative_id: str,
    rank: int,
    relative: dict[str, object],
) -> dict[str, object]:
    return {
        "alternative_id": alternative_id,
        "preference_rank": rank,
        "second_interface_in_first_interface": relative,
    }


def mate(
    mate_id: str,
    first: tuple[str, str],
    second: tuple[str, str],
    alternatives: list[dict[str, object]],
    *,
    property_keys: list[str] | None = None,
) -> dict[str, object]:
    return {
        "mate_id": mate_id,
        "first": endpoint(*first),
        "second": endpoint(*second),
        "property_keys": property_keys if property_keys is not None else ["size"],
        "alternatives": alternatives,
    }


def assembly(
    occurrences: list[dict[str, object]],
    mates: list[dict[str, object]],
    *,
    budget: int = 100,
) -> dict[str, object]:
    return {
        "schema_version": INTERFACE_ASSEMBLY_SCHEMA,
        "occurrences": occurrences,
        "mates": mates,
        "candidate_budget": budget,
    }


def cyclic_document(
    ab_alternatives: list[dict[str, object]],
    bc_alternatives: list[dict[str, object]],
    ac_alternatives: list[dict[str, object]],
    *,
    budget: int = 100,
) -> dict[str, object]:
    occurrences = [
        occurrence(
            "a",
            [interface("ab", "output"), interface("ac", "output")],
            anchor=transform(),
        ),
        occurrence("b", [interface("ba", "input"), interface("bc", "output")]),
        occurrence("c", [interface("cb", "input"), interface("ca", "input")]),
    ]
    mates = [
        mate("ab", ("a", "ab"), ("b", "ba"), ab_alternatives),
        mate("bc", ("b", "bc"), ("c", "cb"), bc_alternatives),
        mate("ac", ("a", "ac"), ("c", "ca"), ac_alternatives),
    ]
    return assembly(occurrences, mates, budget=budget)


class InterfaceAssemblyTests(unittest.TestCase):
    def test_public_api_exports_interface_solver(self) -> None:
        self.assertIs(contrainte.InterfaceAssembly, InterfaceAssembly)
        self.assertIs(contrainte.InterfaceAssemblyResult, InterfaceAssemblyResult)
        self.assertIs(contrainte.solve_interface_assembly, solve_interface_assembly)
        self.assertIs(
            contrainte.verify_interface_assembly_result,
            verify_interface_assembly_result,
        )

    def test_cli_solves_and_independently_verifies_result(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("shaft", "output")], anchor=transform()),
                occurrence("b", [interface("shaft", "input")]),
            ],
            [
                mate(
                    "shaft-mate",
                    ("a", "shaft"),
                    ("b", "shaft"),
                    [alternative("direct", 0, transform(5))],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "assembly.json"
            result_path = root / "result.json"
            input_path.write_text(
                dumps_pretty(document), encoding="utf-8", newline="\n"
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    cli_main(
                        [
                            "interface-assembly",
                            "solve",
                            str(input_path),
                            "--output",
                            str(result_path),
                        ]
                    ),
                    0,
                )
            self.assertEqual(loads_strict(stdout.getvalue())["status"], "solved")
            self.assertTrue(result_path.is_file())
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    cli_main(
                        [
                            "interface-assembly",
                            "verify",
                            str(input_path),
                            str(result_path),
                        ]
                    ),
                    0,
                )
            self.assertEqual(loads_strict(stdout.getvalue()), {"status": "verified"})

            tampered = loads_strict(result_path.read_bytes())
            tampered["occurrence_transforms"][1]["transform"]["translation"]["x"] = "6"
            result_path.write_text(
                dumps_pretty(tampered), encoding="utf-8", newline="\n"
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(
                    cli_main(
                        [
                            "interface-assembly",
                            "verify",
                            str(input_path),
                            str(result_path),
                        ]
                    ),
                    2,
                )
            self.assertIn("cannot be reproduced", stderr.getvalue())

    def test_two_occurrence_formula_is_exact(self) -> None:
        document = assembly(
            [
                occurrence(
                    "a",
                    [interface("out", "output", origin=("2", "0", "0"))],
                    anchor=transform(10),
                ),
                occurrence("b", [interface("in", "input", origin=("3", "0", "0"))]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("preferred", 0, transform(5))],
                )
            ],
        )

        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)

        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(
            result.occurrence_transforms[1].transform,
            ExactRigidTransform.from_dict(transform(14)),
        )
        self.assertTrue(verify_interface_assembly_solution(parsed, result))

    def test_interface_basis_uses_column_vector_semantics(self) -> None:
        quarter_turn = {
            "x_axis": {"x": "0", "y": "1", "z": "0"},
            "y_axis": {"x": "-1", "y": "0", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        }
        document = assembly(
            [
                occurrence(
                    "a",
                    [
                        interface(
                            "out",
                            "output",
                            origin=("1", "0", "0"),
                            basis=quarter_turn,
                        )
                    ],
                    anchor=transform(),
                ),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("only", 0, transform(2))],
                )
            ],
        )

        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)

        self.assertEqual(
            result.occurrence_transforms[1].transform,
            ExactRigidTransform.from_dict(transform(1, 2, basis=quarter_turn)),
        )

    def test_propagation_is_exact_when_the_second_occurrence_is_anchored(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("out", "output", origin=("2", "0", "0"))]),
                occurrence(
                    "b",
                    [interface("in", "input", origin=("3", "0", "0"))],
                    anchor=transform(10),
                ),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("only", 0, transform(5))],
                )
            ],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(
            result.occurrence_transforms[0].transform,
            ExactRigidTransform.from_dict(transform(6)),
        )

    def test_three_occurrence_chain_propagates_from_nonzero_anchor(self) -> None:
        occurrences = [
            occurrence("z", [interface("za", "input")]),
            occurrence("root", [interface("ra", "output")], anchor=transform(7, -2, 3)),
            occurrence(
                "middle",
                [interface("mr", "input"), interface("mz", "output")],
            ),
        ]
        mates = [
            mate(
                "second",
                ("middle", "mz"),
                ("z", "za"),
                [alternative("only", 0, transform(4, 5, 6))],
            ),
            mate(
                "first",
                ("root", "ra"),
                ("middle", "mr"),
                [alternative("only", 0, transform(1, 2, 3))],
            ),
        ]

        parsed = InterfaceAssembly.from_dict(assembly(occurrences, mates))
        result = solve_interface_assembly(parsed)

        self.assertEqual(
            [item.occurrence_id for item in result.occurrence_transforms],
            ["middle", "root", "z"],
        )
        self.assertEqual(
            result.occurrence_transforms[2].transform,
            ExactRigidTransform.from_dict(transform(12, 5, 12)),
        )

    def test_consistent_cycle_closes_exactly(self) -> None:
        document = cyclic_document(
            [alternative("only", 0, transform(1))],
            [alternative("only", 0, transform(2))],
            [alternative("only", 0, transform(3))],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(result.examined_candidates, 1)

    def test_contradictory_cycle_is_unsatisfiable_only_after_exhaustion(self) -> None:
        document = cyclic_document(
            [alternative("only", 0, transform(1))],
            [alternative("only", 0, transform(2))],
            [alternative("only", 0, transform(4))],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.UNSATISFIABLE)
        self.assertEqual(result.examined_candidates, 1)
        self.assertIsNone(result.inconclusive_reason)
        self.assertTrue(
            verify_interface_assembly_result(
                InterfaceAssembly.from_dict(document), result
            )
        )

    def test_lexicographic_preferences_are_deterministic(self) -> None:
        document = cyclic_document(
            [
                alternative("ab-one", 0, transform(1)),
                alternative("ab-two", 1, transform(2)),
            ],
            [
                alternative("bc-two", 0, transform(2)),
                alternative("bc-three", 1, transform(3)),
            ],
            [alternative("ac-four", 0, transform(4))],
        )
        document["mates"] = list(reversed(document["mates"]))  # type: ignore[index]
        document["occurrences"] = list(  # type: ignore[index]
            reversed(document["occurrences"])  # type: ignore[index]
        )

        parsed = InterfaceAssembly.from_dict(document)
        first = solve_interface_assembly(parsed)
        second = solve_interface_assembly(parsed)

        self.assertEqual(first, second)
        self.assertEqual(first.examined_candidates, 2)
        self.assertEqual(
            [
                (item.mate_id, item.alternative_id)
                for item in first.selected_alternatives
            ],
            [("ab", "ab-one"), ("ac", "ac-four"), ("bc", "bc-three")],
        )

    def test_budget_exhaustion_is_inconclusive_never_unsatisfiable(self) -> None:
        document = cyclic_document(
            [
                alternative("ab-one", 0, transform(1)),
                alternative("ab-two", 1, transform(2)),
            ],
            [alternative("bc-two", 0, transform(2))],
            [alternative("ac-four", 0, transform(4))],
            budget=1,
        )

        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)

        self.assertEqual(result.status, SolveStatus.INCONCLUSIVE)
        self.assertEqual(
            result.inconclusive_reason,
            InconclusiveReason.CANDIDATE_BUDGET_EXHAUSTED,
        )
        self.assertEqual(result.examined_candidates, 1)
        self.assertEqual(result.occurrence_transforms, ())
        self.assertTrue(verify_interface_assembly_result(parsed, result))
        self.assertFalse(
            verify_interface_assembly_result(
                parsed,
                replace(
                    result,
                    inconclusive_reason=InconclusiveReason.EXACT_SCALAR_LIMIT,
                ),
            )
        )

    def test_exact_scalar_exhaustion_is_inconclusive(self) -> None:
        parameter = 10**29
        denominator = parameter * parameter + 1
        cosine = Fraction(parameter * parameter - 1, denominator)
        sine = Fraction(2 * parameter, denominator)
        rational_rotation = {
            "x_axis": {
                "x": rational_text(cosine),
                "y": rational_text(sine),
                "z": "0",
            },
            "y_axis": {
                "x": rational_text(-sine),
                "y": rational_text(cosine),
                "z": "0",
            },
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        }
        relative = transform(basis=rational_rotation)
        document = assembly(
            [
                occurrence("a", [interface("ab", "output")], anchor=transform()),
                occurrence("b", [interface("ba", "input"), interface("bc", "output")]),
                occurrence("c", [interface("cb", "input")]),
            ],
            [
                mate(
                    "ab",
                    ("a", "ab"),
                    ("b", "ba"),
                    [
                        alternative("large", 0, relative),
                        alternative("fallback", 1, transform()),
                    ],
                ),
                mate(
                    "bc",
                    ("b", "bc"),
                    ("c", "cb"),
                    [alternative("only", 0, relative)],
                ),
            ],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.INCONCLUSIVE)
        self.assertEqual(
            result.inconclusive_reason, InconclusiveReason.EXACT_SCALAR_LIMIT
        )
        self.assertEqual(result.examined_candidates, 1)
        self.assertTrue(
            verify_interface_assembly_result(
                InterfaceAssembly.from_dict(document), result
            )
        )

    def test_reconstruction_verifier_rejects_transform_and_selection_tampering(
        self,
    ) -> None:
        document = cyclic_document(
            [alternative("only", 0, transform(1))],
            [alternative("only", 0, transform(2))],
            [alternative("only", 0, transform(3))],
        )
        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)
        transforms = list(result.occurrence_transforms)
        transforms[1] = SolvedOccurrence(
            "b", ExactRigidTransform.from_dict(transform(9))
        )
        tampered_transform = replace(result, occurrence_transforms=tuple(transforms))
        selected = list(result.selected_alternatives)
        selected[0] = SelectedMateAlternative("ab", "only", 99)
        tampered_selection = replace(result, selected_alternatives=tuple(selected))

        self.assertFalse(verify_interface_assembly_solution(parsed, tampered_transform))
        self.assertFalse(verify_interface_assembly_solution(parsed, tampered_selection))
        self.assertFalse(
            verify_interface_assembly_solution(
                parsed,
                replace(result, status=SolveStatus.UNSATISFIABLE),
            )
        )
        self.assertFalse(
            verify_interface_assembly_solution(
                parsed,
                replace(
                    result, schema_version="contrainte.interface-assembly-result/9.9"
                ),
            )
        )
        self.assertFalse(
            verify_interface_assembly_solution(
                parsed, replace(result, candidate_budget=result.candidate_budget + 1)
            )
        )

    def test_graph_must_be_connected(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("ab", "output")], anchor=transform()),
                occurrence("b", [interface("ba", "input")]),
                occurrence("c", [interface("unused", "bidirectional")]),
            ],
            [
                mate(
                    "ab",
                    ("a", "ab"),
                    ("b", "ba"),
                    [alternative("only", 0, transform())],
                )
            ],
        )

        with self.assertRaisesRegex(InputError, "disconnected.*c"):
            InterfaceAssembly.from_dict(document)

    def test_interface_endpoints_are_single_use(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("shared", "output")], anchor=transform()),
                occurrence("b", [interface("ba", "input")]),
                occurrence("c", [interface("ca", "input")]),
            ],
            [
                mate(
                    "ab",
                    ("a", "shared"),
                    ("b", "ba"),
                    [alternative("only", 0, transform())],
                ),
                mate(
                    "ac",
                    ("a", "shared"),
                    ("c", "ca"),
                    [alternative("only", 0, transform())],
                ),
            ],
        )

        with self.assertRaisesRegex(InputError, "used by more than one mate"):
            InterfaceAssembly.from_dict(document)

    def test_duplicate_component_interfaces_are_rejected(self) -> None:
        duplicate = interface("same", "bidirectional")
        document = assembly(
            [
                occurrence(
                    "a", [duplicate, copy.deepcopy(duplicate)], anchor=transform()
                )
            ],
            [],
        )

        with self.assertRaisesRegex(InputError, "interface identifiers must be unique"):
            InterfaceAssembly.from_dict(document)

    def test_mate_contract_rejects_incompatible_interfaces(self) -> None:
        cases = {
            "kinds": (
                interface("out", "output", kind="mechanical"),
                interface("in", "input", kind="electrical"),
                "kinds",
                ["size"],
            ),
            "media": (
                interface("out", "output", medium="dry"),
                interface("in", "input", medium="water"),
                "media",
                ["size"],
            ),
            "directions": (
                interface("out", "output"),
                interface("in", "output"),
                "directions",
                ["size"],
            ),
            "property": (
                interface("out", "output", properties={"size": "M8"}),
                interface("in", "input", properties={"size": "M10"}),
                "selected property",
                ["size"],
            ),
        }
        for name, (first, second, message, property_keys) in cases.items():
            with self.subTest(name=name):
                document = assembly(
                    [
                        occurrence("a", [first], anchor=transform()),
                        occurrence("b", [second]),
                    ],
                    [
                        mate(
                            "joint",
                            ("a", "out"),
                            ("b", "in"),
                            [alternative("only", 0, transform())],
                            property_keys=property_keys,
                        )
                    ],
                )
                with self.assertRaisesRegex(InputError, message):
                    InterfaceAssembly.from_dict(document)

    def test_only_explicitly_selected_properties_are_compared(self) -> None:
        document = assembly(
            [
                occurrence(
                    "a",
                    [
                        interface(
                            "out",
                            "output",
                            properties={"size": "M8", "finish": "rough"},
                        )
                    ],
                    anchor=transform(),
                ),
                occurrence(
                    "b",
                    [
                        interface(
                            "in",
                            "input",
                            properties={"size": "M8", "finish": "polished"},
                        )
                    ],
                ),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("only", 0, transform())],
                    property_keys=["size"],
                )
            ],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.SOLVED)

    def test_alternatives_must_be_sorted_and_unique(self) -> None:
        base_occurrences = [
            occurrence("a", [interface("out", "output")], anchor=transform()),
            occurrence("b", [interface("in", "input")]),
        ]
        cases = {
            "sorted": [
                alternative("later", 1, transform(1)),
                alternative("earlier", 0, transform(2)),
            ],
            "identifiers": [
                alternative("same", 0, transform(1)),
                alternative("same", 1, transform(2)),
            ],
            "transforms": [
                alternative("first", 0, transform(1)),
                alternative("second", 1, transform(1)),
            ],
        }
        for message, alternatives in cases.items():
            with self.subTest(message=message):
                document = assembly(
                    copy.deepcopy(base_occurrences),
                    [mate("joint", ("a", "out"), ("b", "in"), alternatives)],
                )
                with self.assertRaisesRegex(InputError, message):
                    InterfaceAssembly.from_dict(document)

    def test_exactly_one_anchor_is_required(self) -> None:
        for anchors in (0, 2):
            with self.subTest(anchors=anchors):
                occurrences = [
                    occurrence(
                        "a",
                        [interface("out", "output")],
                        anchor=transform() if anchors >= 1 else None,
                    ),
                    occurrence(
                        "b",
                        [interface("in", "input")],
                        anchor=transform() if anchors == 2 else None,
                    ),
                ]
                document = assembly(
                    occurrences,
                    [
                        mate(
                            "joint",
                            ("a", "out"),
                            ("b", "in"),
                            [alternative("only", 0, transform())],
                        )
                    ],
                )
                with self.assertRaisesRegex(InputError, "exactly one anchor"):
                    InterfaceAssembly.from_dict(document)

    def test_parser_rejects_hostile_schemas_types_and_caps(self) -> None:
        base = assembly(
            [occurrence("a", [interface("only", "bidirectional")], anchor=transform())],
            [],
        )
        mutations: list[tuple[str, object, str]] = [
            ("schema_version", "contrainte.interface-assembly/9.9", "schema_version"),
            ("candidate_budget", True, "candidate_budget"),
            ("candidate_budget", MAX_CANDIDATE_BUDGET + 1, "candidate_budget"),
        ]
        for key, value, message in mutations:
            with self.subTest(key=key, value=value):
                document = copy.deepcopy(base)
                document[key] = value
                with self.assertRaisesRegex(InputError, message):
                    InterfaceAssembly.from_dict(document)

        unknown = copy.deepcopy(base)
        unknown["authority"] = "claimed"
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            InterfaceAssembly.from_dict(unknown)

        hostile_type = copy.deepcopy(base)
        hostile_type["mates"] = ()
        with self.assertRaisesRegex(InputError, "supported JSON value"):
            InterfaceAssembly.from_dict(hostile_type)

        overlong = copy.deepcopy(base)
        overlong["occurrences"][0]["occurrence_id"] = "x" * 129  # type: ignore[index]
        with self.assertRaisesRegex(InputError, "at most 128"):
            InterfaceAssembly.from_dict(overlong)

        old_component = copy.deepcopy(base)
        old_component["occurrences"][0]["component"][  # type: ignore[index]
            "schema_version"
        ] = "contrainte.component-manifest/0.2"
        with self.assertRaisesRegex(InputError, "component schema"):
            InterfaceAssembly.from_dict(old_component)

        many_alternatives = [
            alternative(f"option-{index:03}", index, transform(index))
            for index in range(MAX_ALTERNATIVES_PER_MATE + 1)
        ]
        capped = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [mate("joint", ("a", "out"), ("b", "in"), many_alternatives)],
        )
        with self.assertRaisesRegex(InputError, "alternatives exceeds"):
            InterfaceAssembly.from_dict(capped)

    def test_direct_construction_cannot_bypass_canonical_contracts(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [
                        alternative("first", 0, transform()),
                        alternative("second", 1, transform(1)),
                    ],
                )
            ],
        )
        parsed = InterfaceAssembly.from_dict(document)

        class EqualitySpoof(str):
            def __eq__(self, other: object) -> bool:
                return True

            __hash__ = str.__hash__

        class HostileEndpoint(InterfaceEndpoint):
            pass

        mutable_occurrences = list(parsed.occurrences)
        malformed = (
            replace(parsed, schema_version="contrainte.interface-assembly/9.9"),
            replace(parsed, schema_version=EqualitySpoof(INTERFACE_ASSEMBLY_SCHEMA)),
            replace(parsed, candidate_budget=0),
            replace(parsed, occurrences=()),
            replace(parsed, occurrences=tuple(reversed(parsed.occurrences))),
            replace(
                parsed,
                mates=(
                    replace(
                        parsed.mates[0],
                        alternatives=tuple(reversed(parsed.mates[0].alternatives)),
                    ),
                ),
            ),
            replace(
                parsed,
                mates=(
                    replace(
                        parsed.mates[0],
                        first=HostileEndpoint("a", "out"),
                    ),
                ),
            ),
            replace(parsed, occurrences=mutable_occurrences),
        )
        mutable_occurrences.clear()
        for item in malformed:
            with self.subTest(item=item), self.assertRaises(InputError):
                solve_interface_assembly(item)

    def test_hostile_coordinate_keys_are_rejected_before_equality(self) -> None:
        document = assembly(
            [occurrence("a", [interface("only", "bidirectional")], anchor=transform())],
            [],
        )

        class EvilKey(str):
            def __eq__(self, other: object) -> bool:
                raise AssertionError("hostile key equality executed")

            __hash__ = str.__hash__

        evil_coordinates = MappingProxyType(
            {EvilKey("x"): Decimal(0), "y": Decimal(0), "z": Decimal(0)}
        )
        frame_assembly = InterfaceAssembly.from_dict(document)
        frame_record = frame_assembly.occurrences[0].component.interfaces[0].frame
        self.assertIsNotNone(frame_record)
        object.__setattr__(frame_record, "origin", evil_coordinates)

        evil_minimum = MappingProxyType(
            {EvilKey("x"): Decimal(-100), "y": Decimal(-100), "z": Decimal(-100)}
        )
        bounds_assembly = InterfaceAssembly.from_dict(document)
        bounds_record = bounds_assembly.occurrences[0].component.geometry_bounds
        self.assertIsNotNone(bounds_record)
        object.__setattr__(bounds_record, "minimum", evil_minimum)

        for malformed in (frame_assembly, bounds_assembly):
            with self.subTest(malformed=malformed), self.assertRaises(InputError):
                solve_interface_assembly(malformed)

    def test_oversized_direct_collections_fail_before_materialization(self) -> None:
        one_document = assembly(
            [occurrence("a", [interface("only", "bidirectional")], anchor=transform())],
            [],
        )
        one = InterfaceAssembly.from_dict(one_document)
        occurrence_record = one.occurrences[0]
        component_record = occurrence_record.component
        interface_record = component_record.interfaces[0]

        pair_document = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("only", 0, transform())],
                )
            ],
        )
        pair = InterfaceAssembly.from_dict(pair_document)
        mate_record = pair.mates[0]

        oversized_components = (
            replace(
                component_record,
                artifacts=component_record.artifacts
                * (MAX_ARTIFACTS_PER_COMPONENT + 1),
            ),
            replace(
                component_record,
                interfaces=component_record.interfaces
                * (MAX_INTERFACES_PER_COMPONENT + 1),
            ),
            replace(
                component_record,
                capabilities=tuple(
                    f"capability-{index}"
                    for index in range(MAX_CAPABILITIES_PER_COMPONENT + 1)
                ),
            ),
            replace(
                component_record,
                metadata=MappingProxyType(
                    {
                        f"key-{index}": "value"
                        for index in range(MAX_COMPONENT_METADATA_FIELDS + 1)
                    }
                ),
            ),
            replace(
                component_record,
                interfaces=(
                    replace(
                        interface_record,
                        properties=MappingProxyType(
                            {
                                f"key-{index}": "value"
                                for index in range(MAX_INTERFACE_PROPERTIES + 1)
                            }
                        ),
                    ),
                ),
            ),
        )
        malformed = [
            replace(
                one,
                occurrences=one.occurrences * (MAX_OCCURRENCES + 1),
            ),
            replace(pair, mates=pair.mates * (MAX_MATES + 1)),
            replace(
                pair,
                mates=(
                    replace(
                        mate_record,
                        property_keys=tuple(
                            f"key-{index}"
                            for index in range(MAX_PROPERTIES_PER_MATE + 1)
                        ),
                    ),
                ),
            ),
            replace(
                pair,
                mates=(
                    replace(
                        mate_record,
                        alternatives=mate_record.alternatives
                        * (MAX_ALTERNATIVES_PER_MATE + 1),
                    ),
                ),
            ),
            replace(
                one,
                occurrences=(
                    replace(
                        occurrence_record,
                        component=replace(
                            component_record,
                            artifacts=component_record.artifacts
                            * MAX_ARTIFACTS_PER_COMPONENT,
                        ),
                    ),
                )
                * MAX_OCCURRENCES,
            ),
        ]
        malformed.extend(
            replace(
                one,
                occurrences=(
                    replace(occurrence_record, component=oversized_component),
                ),
            )
            for oversized_component in oversized_components
        )

        for direct_object in malformed:
            with (
                self.subTest(direct_object=direct_object),
                self.assertRaises(InputError),
            ):
                solve_interface_assembly(direct_object)

        solved = solve_interface_assembly(one)
        oversized_result = replace(
            solved,
            occurrence_transforms=solved.occurrence_transforms * (MAX_OCCURRENCES + 1),
        )
        self.assertFalse(verify_interface_assembly_solution(one, oversized_result))

    def test_preferred_large_rational_rotation_is_not_reprocessed(self) -> None:
        parameter = 10**29
        denominator = parameter * parameter + 1
        cosine = Fraction(parameter * parameter - 1, denominator)
        sine = Fraction(2 * parameter, denominator)
        rational_rotation = {
            "x_axis": {
                "x": rational_text(cosine),
                "y": rational_text(sine),
                "z": "0",
            },
            "y_axis": {
                "x": rational_text(-sine),
                "y": rational_text(cosine),
                "z": "0",
            },
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        }
        document = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [
                        alternative("preferred", 0, transform(basis=rational_rotation)),
                        alternative("fallback", 1, transform()),
                    ],
                )
            ],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(result.examined_candidates, 1)
        self.assertEqual(result.selected_alternatives[0].alternative_id, "preferred")

    def test_reverse_anchor_uses_a_symmetric_exact_certificate(
        self,
    ) -> None:
        parameter = 10**29
        denominator = parameter * parameter + 1
        cosine = Fraction(parameter * parameter - 1, denominator)
        sine = Fraction(2 * parameter, denominator)
        rational_rotation = {
            "x_axis": {
                "x": rational_text(cosine),
                "y": rational_text(sine),
                "z": "0",
            },
            "y_axis": {
                "x": rational_text(-sine),
                "y": rational_text(cosine),
                "z": "0",
            },
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        }
        document = assembly(
            [
                occurrence("a", [interface("out", "output")]),
                occurrence("b", [interface("in", "input")], anchor=transform()),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("only", 0, transform(basis=rational_rotation))],
                )
            ],
        )

        result = solve_interface_assembly(InterfaceAssembly.from_dict(document))

        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(result.examined_candidates, 1)
        self.assertTrue(
            verify_interface_assembly_solution(
                InterfaceAssembly.from_dict(document), result
            )
        )

    def test_verifier_rejects_a_feasible_but_nonfirst_candidate(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [
                        alternative("first", 0, transform(1)),
                        alternative("second", 1, transform(2)),
                    ],
                )
            ],
        )
        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)
        forged_transforms = list(result.occurrence_transforms)
        forged_transforms[1] = SolvedOccurrence(
            "b", ExactRigidTransform.from_dict(transform(2))
        )
        forged = replace(
            result,
            examined_candidates=2,
            occurrence_transforms=tuple(forged_transforms),
            selected_alternatives=(SelectedMateAlternative("joint", "second", 1),),
        )

        self.assertFalse(verify_interface_assembly_solution(parsed, forged))

    def test_verifier_prior_candidate_oracle_is_independent_from_search(self) -> None:
        document = assembly(
            [
                occurrence("a", [interface("out", "output")], anchor=transform()),
                occurrence("b", [interface("in", "input")]),
            ],
            [
                mate(
                    "joint",
                    ("a", "out"),
                    ("b", "in"),
                    [alternative("first", 0, transform(1))],
                )
            ],
        )
        parsed = InterfaceAssembly.from_dict(document)
        result = solve_interface_assembly(parsed)

        with patch(
            "contrainte.interface_assembly._propagate_candidate", return_value=None
        ):
            self.assertTrue(verify_interface_assembly_solution(parsed, result))
            self.assertTrue(verify_interface_assembly_result(parsed, result))

    def test_result_parser_rejects_impossible_terminal_counts(self) -> None:
        base = {
            "schema_version": "contrainte.interface-assembly-result/0.1",
            "status": "unsatisfiable",
            "examined_candidates": 0,
            "candidate_budget": 2,
            "occurrence_transforms": [],
            "selected_alternatives": [],
        }
        impossible = [base]
        for reason, examined in (
            ("candidate_budget_exhausted", 0),
            ("candidate_budget_exhausted", 1),
            ("exact_scalar_limit", 0),
            ("work_budget_exhausted", 0),
        ):
            document = copy.deepcopy(base)
            document["status"] = "inconclusive"
            document["examined_candidates"] = examined
            document["inconclusive_reason"] = reason
            impossible.append(document)

        for document in impossible:
            with self.subTest(document=document), self.assertRaises(InputError):
                InterfaceAssemblyResult.from_dict(document)

    def test_adversarial_search_stops_at_the_exact_work_cap(self) -> None:
        occurrence_documents = []
        for index in range(18):
            occurrence_documents.append(
                occurrence(
                    f"n{index:02}",
                    [interface("in", "input"), interface("out", "output")],
                    anchor=transform() if index == 0 else None,
                )
            )
        mate_documents = []
        for index in range(17):
            mate_documents.append(
                mate(
                    f"edge-{index:02}",
                    (f"n{index:02}", "out"),
                    (f"n{index + 1:02}", "in"),
                    [
                        alternative("zero", 0, transform()),
                        alternative("one", 1, transform(1)),
                    ],
                )
            )
        mate_documents.append(
            mate(
                "zz-close",
                ("n17", "out"),
                ("n00", "in"),
                [alternative("impossible", 0, transform(1_000))],
            )
        )
        parsed = InterfaceAssembly.from_dict(
            assembly(
                occurrence_documents,
                mate_documents,
                budget=MAX_CANDIDATE_BUDGET,
            )
        )

        result = solve_interface_assembly(parsed)

        self.assertEqual(result.status, SolveStatus.INCONCLUSIVE)
        self.assertEqual(
            result.inconclusive_reason, InconclusiveReason.WORK_BUDGET_EXHAUSTED
        )
        self.assertEqual(
            result.examined_candidates,
            MAX_EXACT_MATE_EVALUATIONS // len(parsed.mates),
        )
        self.assertTrue(verify_interface_assembly_result(parsed, result))
        self.assertFalse(
            verify_interface_assembly_result(
                parsed,
                replace(result, examined_candidates=result.examined_candidates - 1),
            )
        )

    def test_occurrences_and_nested_contract_maps_are_immutable(self) -> None:
        document = assembly(
            [occurrence("a", [interface("only", "bidirectional")], anchor=transform())],
            [],
        )
        parsed = InterfaceAssembly.from_dict(document)

        with self.assertRaises(FrozenInstanceError):
            parsed.occurrences[0].occurrence_id = "changed"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            parsed.occurrences[0].component.metadata["new"] = "value"  # type: ignore[index]
        with self.assertRaises(TypeError):
            parsed.occurrences[0].component.interfaces[0].properties["size"] = "M10"  # type: ignore[index]
        with self.assertRaises(TypeError):
            parsed.occurrences[0].component.interfaces[0].frame.origin["x"] = "9"  # type: ignore[index,union-attr]

    def test_round_trip_preserves_canonical_exact_documents(self) -> None:
        document = cyclic_document(
            [alternative("only", 0, transform(Fraction(1, 3)))],
            [alternative("only", 0, transform(Fraction(2, 3)))],
            [alternative("only", 0, transform(1))],
        )

        parsed = InterfaceAssembly.from_dict(document)
        reparsed = InterfaceAssembly.from_dict(parsed.as_dict())
        result = solve_interface_assembly(reparsed)

        self.assertEqual(parsed, reparsed)
        self.assertEqual(result.status, SolveStatus.SOLVED)
        self.assertEqual(
            result.as_dict()["schema_version"],
            "contrainte.interface-assembly-result/0.1",
        )


if __name__ == "__main__":
    unittest.main()
