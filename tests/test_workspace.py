from __future__ import annotations

import tempfile
import unittest

from test_program import program_document

from contrainte.errors import InputError, IntegrityError
from contrainte.program import DesignProgram
from contrainte.workspace import DesignWorkspace


class WorkspaceTests(unittest.TestCase):
    def test_run_resumes_from_content_addressed_state(self) -> None:
        program = DesignProgram.from_dict(program_document())
        with tempfile.TemporaryDirectory() as directory:
            workspace = DesignWorkspace(directory)
            first = workspace.create_run(program, "demo")
            second = workspace.create_run(program, "demo")

            self.assertEqual(first, second)
            self.assertEqual(workspace.ready_tasks(program, "demo"), ("requirements",))
            workspace.start_task(program, "demo", "requirements")
            artifact = workspace.put_document({"requirements": ["guarding"]})
            workspace.finish_task(
                program, "demo", "requirements", {"requirements": artifact}
            )
            self.assertEqual(workspace.ready_tasks(program, "demo"), ("cad",))

    def test_required_outputs_cannot_be_omitted(self) -> None:
        program = DesignProgram.from_dict(program_document())
        with tempfile.TemporaryDirectory() as directory:
            workspace = DesignWorkspace(directory)
            workspace.create_run(program, "demo")
            workspace.start_task(program, "demo", "requirements")

            with self.assertRaisesRegex(InputError, "missing required"):
                workspace.finish_task(program, "demo", "requirements", {})

    def test_object_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = DesignWorkspace(directory)
            reference = workspace.put_bytes(b"original", "application/octet-stream")
            workspace.object_path(reference.digest).write_bytes(b"tampered")

            with self.assertRaisesRegex(IntegrityError, "mismatch"):
                workspace.read_object(reference)


if __name__ == "__main__":
    unittest.main()
