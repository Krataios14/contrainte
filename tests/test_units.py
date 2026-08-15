import unittest
from decimal import Decimal

from contrainte.errors import DimensionalityError, InputError
from contrainte.units import Quantity


class QuantityTests(unittest.TestCase):
    def test_time_conversion_is_exact(self) -> None:
        duration = Quantity.from_dict({"value": "1.5", "unit": "min", "kind": "time"})

        self.assertEqual(duration.to("s").value, Decimal("90.0"))

    def test_unknown_quantity_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            Quantity.from_dict(
                {
                    "value": "1",
                    "unit": "m",
                    "kind": "length",
                    "precision": "assumed",
                }
            )

    def test_millimeters_convert_to_meters(self) -> None:
        quantity = Quantity(Decimal(500), "mm", "length")
        self.assertEqual(quantity.to("m").value, Decimal("0.500"))

    def test_megapascals_convert_to_pascals(self) -> None:
        quantity = Quantity(Decimal(250), "MPa", "pressure")
        self.assertEqual(quantity.si_value, Decimal(250000000))

    def test_incompatible_kind_is_rejected(self) -> None:
        with self.assertRaises(DimensionalityError):
            Quantity(Decimal(1), "N", "length")

    def test_incompatible_conversion_is_rejected(self) -> None:
        quantity = Quantity(Decimal(1), "m", "length")
        with self.assertRaises(DimensionalityError):
            quantity.to("Pa")

    def test_non_positive_input_is_rejected(self) -> None:
        quantity = Quantity(Decimal(0), "m", "length")
        with self.assertRaises(InputError):
            quantity.require_positive("length")


if __name__ == "__main__":
    unittest.main()
