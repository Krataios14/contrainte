import contextlib
import io
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from contrainte.canonical import canonical_bytes, digest, loads_strict
from contrainte.cli import main as cli_main
from contrainte.errors import CanonicalizationError, InputError


class CanonicalTests(unittest.TestCase):
    def test_object_key_order_does_not_change_digest(self) -> None:
        left = {"z": [Decimal("1.2300")], "a": {"b": True}}
        right = {"a": {"b": True}, "z": [Decimal("1.23")]}
        self.assertEqual(digest(left), digest(right))

    def test_decimal_is_non_exponent_string(self) -> None:
        self.assertEqual(
            canonical_bytes({"value": Decimal("1E+6")}), b'{"value":"1000000"}'
        )

    def test_binary_float_is_forbidden(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_bytes({"value": 0.1})

    def test_json_float_literal_is_forbidden(self) -> None:
        with self.assertRaises(InputError):
            loads_strict('{"value": 0.1}')

    def test_duplicate_object_keys_are_rejected_at_every_level(self) -> None:
        cases = (
            '{"a": 1, "a": 1}',
            '{"a": 1, "a": 2}',
            '{"outer": {"b": "x", "b": "y"}}',
            '[{"ok": 1}, {"c": [{"d": 1, "d": 1}]}]',
            '{"a": 1, "\\u0061": 2}',
            '{"\\u00e9": 1, "é": 2}',
        )
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaisesRegex(InputError, "duplicate JSON object key"):
                    loads_strict(text)
                with self.assertRaisesRegex(InputError, "duplicate JSON object key"):
                    loads_strict(text.encode("utf-8"))

    def test_distinct_keys_still_parse_order_independently(self) -> None:
        left = loads_strict('{"z": {"y": 1, "x": [true, null]}, "a": "1.5"}')
        right = loads_strict('{"a": "1.5", "z": {"x": [true, null], "y": 1}}')
        self.assertEqual(left, right)
        self.assertEqual(canonical_bytes(left), canonical_bytes(right))
        self.assertEqual(digest(left), digest(right))
        # Same key text in sibling or nested objects is not a duplicate.
        self.assertEqual(
            loads_strict('{"a": {"a": 1}, "b": [{"a": 2}, {"a": 3}]}'),
            {"a": {"a": 1}, "b": [{"a": 2}, {"a": 3}]},
        )
        # Distinct code points are distinct keys; no Unicode normalization.
        self.assertEqual(
            len(loads_strict('{"\\u00e9": 1, "e\\u0301": 2}')), 2
        )

    def test_non_finite_constants_are_rejected(self) -> None:
        for text in ("NaN", "Infinity", "-Infinity", '{"v": [NaN]}'):
            with self.subTest(text=text):
                with self.assertRaisesRegex(InputError, "non-finite JSON constant"):
                    loads_strict(text)

    def test_cli_reports_duplicate_key_as_input_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "program.json"
            path.write_text('{"schema": 1, "schema": 2}', encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                status = cli_main(["program", "validate", str(path)])
        self.assertEqual(status, 2)
        self.assertEqual(
            stderr.getvalue(),
            "error: duplicate JSON object key is forbidden: 'schema'\n",
        )

    def test_malformed_json_reports_position(self) -> None:
        with self.assertRaisesRegex(InputError, r"invalid JSON: .* at line 1, column"):
            loads_strict('{"a": }')


if __name__ == "__main__":
    unittest.main()
