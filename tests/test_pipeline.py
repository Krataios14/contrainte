import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from contrainte.axial import AxialCase, solve_axial_case
from contrainte.canonical import dumps_pretty, loads_strict
from contrainte.errors import InputError, IntegrityError
from contrainte.pipeline import compile_bundle, load_case, verify_bundle, write_bundle

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "axial-member.json"


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = load_case(EXAMPLE)

    def test_known_axial_solution(self) -> None:
        result = solve_axial_case(self.case)
        values = {
            claim.property_name: claim.quantity.si_value
            for claim in result.derived_claims
        }
        self.assertEqual(values["cross_sectional_area"], Decimal("0.000100"))
        self.assertEqual(values["axial_stress"], Decimal(100000000))
        self.assertEqual(values["axial_strain"], Decimal("0.0005"))
        self.assertEqual(values["axial_displacement"], Decimal("0.0002500"))
        self.assertEqual(values["yield_safety_factor"], Decimal("2.5"))

    def test_bundle_repeats_deterministically(self) -> None:
        first = compile_bundle(self.case)
        second = compile_bundle(self.case)
        self.assertEqual(first, second)
        self.assertEqual(verify_bundle(first)["status"], "verified")

    def test_tampered_result_is_rejected(self) -> None:
        bundle = compile_bundle(self.case)
        bundle["content"]["result"]["derived_claims"][0]["quantity"]["value"] = "999"
        with self.assertRaises(IntegrityError):
            verify_bundle(bundle)

    def test_rehashed_but_false_result_is_rejected(self) -> None:
        bundle = compile_bundle(self.case)
        bundle["content"]["result"]["derived_claims"][0]["quantity"]["value"] = "999"
        from contrainte.canonical import digest

        bundle["digest"] = digest(bundle["content"])
        with self.assertRaises(IntegrityError):
            verify_bundle(bundle)

    def test_missing_evidence_is_rejected(self) -> None:
        raw = loads_strict(EXAMPLE.read_bytes())
        raw["claims"]["length"]["evidence_ids"] = ["EVD-MISSING"]
        with self.assertRaises(InputError):
            AxialCase.from_dict(raw)

    def test_changed_input_changes_bundle_digest(self) -> None:
        raw = loads_strict(EXAMPLE.read_bytes())
        raw["claims"]["yield_strength"]["quantity"]["value"] = "251"
        changed = AxialCase.from_dict(raw)
        self.assertNotEqual(
            compile_bundle(self.case)["digest"], compile_bundle(changed)["digest"]
        )

    def test_input_key_order_does_not_change_bundle_digest(self) -> None:
        raw = loads_strict(EXAMPLE.read_bytes())
        reordered = {key: raw[key] for key in reversed(list(raw))}
        self.assertEqual(
            compile_bundle(self.case)["digest"],
            compile_bundle(AxialCase.from_dict(reordered))["digest"],
        )

    def test_write_and_reload_bundle(self) -> None:
        bundle = compile_bundle(self.case)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            write_bundle(path, bundle)
            loaded = loads_strict(path.read_bytes())
            self.assertEqual(verify_bundle(loaded)["bundle_digest"], bundle["digest"])

    def test_pretty_serialization_does_not_change_semantics(self) -> None:
        bundle = compile_bundle(self.case)
        self.assertEqual(loads_strict(dumps_pretty(bundle)), bundle)


if __name__ == "__main__":
    unittest.main()
