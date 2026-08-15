import unittest
from decimal import Decimal

from contrainte.canonical import canonical_bytes, digest, loads_strict
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


if __name__ == "__main__":
    unittest.main()
