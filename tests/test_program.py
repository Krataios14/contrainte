from __future__ import annotations

import copy
import unittest

from contrainte.errors import InputError
from contrainte.program import DesignProgram


def program_document() -> dict:
    output = lambda product_id: {
        "product_id": product_id,
        "role": "engineering_record",
        "media_type": "application/json",
        "required": True,
    }
    return {
        "schema_version": "contrainte.design-program/0.1",
        "program_id": "machine.demo",
        "revision": "1",
        "goal": {
            "statement": "Design a guarded mechanism",
            "locale": "fr-FR",
            "intended_use": "Engineering exploration",
            "success_criteria": ["All requirements trace to verification evidence"],
            "constraints": ["No unresolved hard collisions"],
            "assumptions": [],
            "exclusions": ["Production release"],
        },
        "tasks": [
            {
                "task_id": "requirements",
                "title": "Requirements",
                "objective": "Formalize the brief",
                "kind": "requirements",
                "authority": "dual",
                "depends_on": [],
                "inputs": [],
                "outputs": [output("requirements")],
                "acceptance_criteria": ["Every ambiguity is explicit"],
                "human_gate": False,
                "instructions": [],
            },
            {
                "task_id": "cad",
                "title": "CAD",
                "objective": "Compile exact geometry",
                "kind": "cad",
                "authority": "deterministic",
                "depends_on": ["requirements"],
                "inputs": ["requirements"],
                "outputs": [output("exact-cad")],
                "acceptance_criteria": ["BREP is valid"],
                "human_gate": False,
                "instructions": [],
            },
        ],
        "metadata": {"profile": "machine"},
    }


class DesignProgramTests(unittest.TestCase):
    def test_program_orders_and_exposes_ready_tasks(self) -> None:
        program = DesignProgram.from_dict(program_document())

        self.assertEqual(program.topological_order(), ("requirements", "cad"))
        self.assertEqual(
            tuple(task.task_id for task in program.ready_tasks(set())), ("requirements",)
        )
        self.assertEqual(
            tuple(task.task_id for task in program.ready_tasks({"requirements"})), ("cad",)
        )

    def test_cycle_is_rejected(self) -> None:
        document = program_document()
        document["tasks"][0]["depends_on"] = ["cad"]

        with self.assertRaisesRegex(InputError, "dependency cycle"):
            DesignProgram.from_dict(document)

    def test_input_requires_direct_dependency_on_producer(self) -> None:
        document = program_document()
        document["tasks"][1]["depends_on"] = []

        with self.assertRaisesRegex(InputError, "does not depend on producer"):
            DesignProgram.from_dict(document)

    def test_unknown_task_field_is_rejected(self) -> None:
        document = copy.deepcopy(program_document())
        document["tasks"][0]["silent_default"] = True

        with self.assertRaisesRegex(InputError, "unsupported fields"):
            DesignProgram.from_dict(document)


if __name__ == "__main__":
    unittest.main()
