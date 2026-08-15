from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from contrainte.agents import (
    AgentRequest,
    ClaudeAdapter,
    CodexAdapter,
    ProcessResult,
)

SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
}


class AgentAdapterTests(unittest.TestCase):
    def request(self, directory: str) -> AgentRequest:
        return AgentRequest(
            task_id="requirements",
            prompt="Identify unresolved engineering requirements.",
            workspace=Path(directory),
            output_schema=SCHEMA,
        )

    def test_codex_uses_noninteractive_ephemeral_workspace_write_mode(self) -> None:
        captured = {}

        def runner(command, *, cwd, stdin, env):
            captured.update(command=tuple(command), cwd=cwd, stdin=stdin, env=env)
            result_path = Path(command[command.index("--output-last-message") + 1])
            result_path.write_text('{"status":"ok"}\n', encoding="utf-8")
            return ProcessResult(0, '{"type":"turn.completed"}\n', "")

        with tempfile.TemporaryDirectory() as directory:
            result = CodexAdapter(runner).run(self.request(directory))

        self.assertEqual(result.structured_output, {"status": "ok"})
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("workspace-write", captured["command"])
        self.assertEqual(captured["command"][-1], "-")
        self.assertIn("Do not run git", captured["stdin"])

    def test_claude_uses_stream_json_and_schema(self) -> None:
        captured = {}

        def runner(command, *, cwd, stdin, env):
            captured["command"] = tuple(command)
            event = {"type": "result", "structured_output": {"status": "ok"}}
            return ProcessResult(0, json.dumps(event) + "\n", "")

        with tempfile.TemporaryDirectory() as directory:
            result = ClaudeAdapter(runner).run(self.request(directory))

        self.assertEqual(result.structured_output, {"status": "ok"})
        self.assertIn("stream-json", captured["command"])
        self.assertIn("--json-schema", captured["command"])
        self.assertIn("--no-session-persistence", captured["command"])


if __name__ == "__main__":
    unittest.main()
