from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
from pathlib import Path

from contrainte.canonical import canonical_bytes, digest, digest_bytes, loads_strict
from contrainte.errors import DimensionalityError, InputError, IntegrityError
from contrainte.physics import (
    CLAIM_BOUNDARY,
    FORMS,
    MODEL_FORMS,
    REGISTRY_VERSION,
    ModelForm,
    StalePinError,
    evaluate_documents,
    parse_intent,
    parse_rule_set,
    registry_digest,
    verify_bundle,
    verify_report,
    write_bundle,
)
from contrainte.physics.__main__ import main
from contrainte.physics.dimensional import (
    KINDS,
    DimensionalQuantity,
    parse_exact,
    terminating_decimal,
)
from contrainte.physics.evaluate import INTENT_FILE, REPORT_FILE
from contrainte.physics.groups import compute_group
from contrainte.physics.registry import registry_description
from contrainte.physics.schema import SCHEMAS, schema_text
from contrainte.units import Quantity

try:
    from jsonschema import Draft202012Validator
except ImportError:  # The runtime and base test environment are dependency-free.
    Draft202012Validator = None  # type: ignore[assignment,misc]

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
RULES_PATH = EXAMPLES / "physics-rules-illustrative.json"
DUCT_PATH = EXAMPLES / "physics-intent-duct-flow.json"
BRACKET_PATH = EXAMPLES / "physics-intent-bracket-beam.json"
STRUCTURAL_BLOCKERS = {
    "RULE_SET_NOT_APPROVED",
    "NO_IDENTITY_BACKED_APPROVAL",
    "NO_QUALIFIED_SOLVER_CAPSULE",
}


def _load(path: Path) -> dict:
    return loads_strict(path.read_bytes())


def _q(value: str, unit: str, kind: str) -> DimensionalQuantity:
    return DimensionalQuantity.from_dict(
        {"value": value, "unit": unit, "kind": kind}, field="q"
    )


def _band(lower, lower_inclusive, upper, upper_inclusive) -> dict:
    return {
        "lower": None
        if lower is None
        else {"value": lower, "inclusive": lower_inclusive},
        "upper": None
        if upper is None
        else {"value": upper, "inclusive": upper_inclusive},
    }


def _rule(rules: dict, rule_id: str) -> dict:
    return next(item for item in rules["rules"] if item["rule_id"] == rule_id)


def _scale(intent: dict, scale_id: str) -> dict:
    return next(item for item in intent["scales"] if item["scale_id"] == scale_id)


def _repin(intent: dict, rules: dict) -> dict:
    intent["rule_set_pin"] = parse_rule_set(rules).pin()
    return intent


def _outcome(report: dict, rule_id: str) -> dict:
    return next(item for item in report["rule_outcomes"] if item["rule_id"] == rule_id)


def _codes(blockers: list[dict]) -> set[str]:
    return {item["code"] for item in blockers}


def _mach_report(flow_speed: str, rules: dict) -> dict:
    intent = _load(DUCT_PATH)
    _scale(intent, "SCL-FLOW-SPEED")["quantity"] = {
        "value": flow_speed,
        "unit": "m/s",
        "kind": "velocity",
    }
    return evaluate_documents(_repin(intent, rules), rules)


def _qualified_clean() -> tuple[dict, dict]:
    """Duct intent in qualified mode with every selected rule valid and non-synthetic citations."""

    rules = _load(RULES_PATH)
    rules["citations"][0]["kind"] = "engineering_rationale"
    intent = _load(DUCT_PATH)
    intent["requested_mode"] = "qualified"
    intent["candidate_model_forms"] = ["continuum_flow"]
    intent["acceptance"] = {
        "kind": "criteria",
        "criteria": [
            {
                "criterion_id": "ACC-PRESSURE-DROP",
                "output_id": "QOI-PRESSURE-DROP",
                "comparator": "le",
                "limit": {"value": "500", "unit": "Pa", "kind": "stress"},
                "rationale": "Fan margin.",
            }
        ],
    }
    return _repin(intent, rules), rules


def _qualified_supported() -> tuple[dict, dict]:
    """``_qualified_clean`` with the inputs' cited evidence recorded as a real measurement record."""

    intent, rules = _qualified_clean()
    intent["evidence"][0]["kind"] = "measurement_record"
    return intent, rules


class DimensionalQuantityTests(unittest.TestCase):
    def test_exact_unit_conversion_retains_rationals(self) -> None:
        self.assertEqual(_q("379.44", "km/h", "velocity").si_value, Fraction("105.4"))
        self.assertEqual(
            _q("0.0181", "mPa.s", "dynamic_viscosity").si_value, Fraction("0.0000181")
        )
        self.assertEqual(_q("1", "h", "time").si_value, 3600)
        self.assertEqual(_q("68", "nm", "length").si_value, Fraction(68, 10**9))

    def test_incompatible_units_are_rejected(self) -> None:
        for value, unit, kind in (
            ("1", "m", "velocity"),
            ("1", "Pa", "dynamic_viscosity"),
            ("1", "W/(m2.K)", "thermal_conductivity"),
            ("1", "K", "heat_transfer_coefficient"),
            ("1", "s", "frequency"),
        ):
            with (
                self.subTest(unit=unit, kind=kind),
                self.assertRaises(DimensionalityError),
            ):
                _q(value, unit, kind)

    def test_same_dimension_kinds_remain_distinct(self) -> None:
        self.assertEqual(KINDS["absolute_pressure"], KINDS["gauge_pressure"])
        self.assertEqual(
            KINDS["thermodynamic_temperature"], KINDS["temperature_difference"]
        )
        speed = _q("1", "m/s", "velocity")
        form = FORMS["mach.speed_ratio"]
        with self.assertRaises(DimensionalityError):
            compute_group(
                form,
                {"flow_speed": speed, "speed_of_sound": _q("1", "1", "strain")},
                "g",
            )

    def test_unsupported_units_kinds_and_fields(self) -> None:
        for raw in (
            {"value": "20", "unit": "degC", "kind": "thermodynamic_temperature"},
            {"value": "1", "unit": "m", "kind": "distance"},
            {"value": "1", "unit": "m", "kind": "length", "uncertainty": "0.1"},
            {"value": "1", "unit": "m"},
        ):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                DimensionalQuantity.from_dict(raw, field="q")

    def test_exact_numeric_strings_are_required(self) -> None:
        for raw in (
            1,
            True,
            None,
            "NaN",
            "Infinity",
            "-Infinity",
            "1e100",
            "-0",
            "-0.0",
            "01",
            "1.",
            ".5",
            " 1",
            "1,5",
            "0x10",
            "1" * 41,
        ):
            with self.subTest(raw=raw), self.assertRaises(InputError):
                parse_exact(raw, "v")
        self.assertEqual(parse_exact("1.5e-3", "v"), Fraction(3, 2000))
        self.assertEqual(parse_exact("1" * 40, "v"), int("1" * 40))

    def test_strict_json_rejects_floats_duplicates_and_constants(self) -> None:
        for text in (
            '{"value": 1.5}',
            '{"a": "1", "a": "2"}',
            '{"value": NaN}',
            '{"value": Infinity}',
        ):
            with self.subTest(text=text), self.assertRaises(InputError):
                loads_strict(text)

    def test_terminating_decimal_is_exact_or_absent(self) -> None:
        self.assertIsNone(terminating_decimal(Fraction(1, 3)))
        self.assertIsNone(terminating_decimal(Fraction(126480000, 181)))
        self.assertEqual(terminating_decimal(Fraction(31, 100)), "0.31")
        self.assertEqual(terminating_decimal(Fraction(-1, 8)), "-0.125")
        self.assertEqual(terminating_decimal(Fraction(17, 25000000)), "0.00000068")
        self.assertEqual(terminating_decimal(Fraction(5)), "5")
        self.assertEqual(terminating_decimal(Fraction(0)), "0")

    def test_legacy_scalar_quantity_semantics_are_unchanged(self) -> None:
        with self.assertRaises(InputError):
            Quantity.from_dict({"value": "1", "unit": "m/s", "kind": "velocity"})
        legacy = Quantity.from_dict({"value": "2.50", "unit": "mm", "kind": "length"})
        self.assertEqual(
            legacy.as_dict(), {"value": "2.5", "unit": "mm", "kind": "length"}
        )


class GroupRegistryTests(unittest.TestCase):
    def test_registry_is_dimensionless_and_pinned_by_example(self) -> None:
        self.assertEqual(registry_digest(), registry_digest())
        self.assertEqual(_load(RULES_PATH)["registry"]["digest"], registry_digest())
        self.assertEqual(
            {form.group_id for form in FORMS.values()},
            {
                "mach",
                "reynolds",
                "knudsen",
                "beam_slenderness",
                "biot",
                "time_scale_ratio",
                "shell_thickness_ratio",
                "density_variation",
            },
        )

    def test_each_group_is_computed_exactly(self) -> None:
        cases = {
            "mach.speed_ratio": (
                {
                    "flow_speed": _q("105.4", "m/s", "velocity"),
                    "speed_of_sound": _q("340", "m/s", "velocity"),
                },
                Fraction(31, 100),
            ),
            "reynolds.dynamic_viscosity": (
                {
                    "density": _q("1000", "kg/m3", "density"),
                    "flow_speed": _q("0.1", "m/s", "velocity"),
                    "characteristic_length": _q("20", "mm", "length"),
                    "dynamic_viscosity": _q("1", "mPa.s", "dynamic_viscosity"),
                },
                Fraction(2000),
            ),
            "reynolds.kinematic_viscosity": (
                {
                    "flow_speed": _q("0.1", "m/s", "velocity"),
                    "characteristic_length": _q("20", "mm", "length"),
                    "kinematic_viscosity": _q("1", "mm2/s", "kinematic_viscosity"),
                },
                Fraction(2000),
            ),
            "knudsen.mean_free_path": (
                {
                    "mean_free_path": _q("68", "nm", "length"),
                    "characteristic_length": _q("1", "um", "length"),
                },
                Fraction(17, 250),
            ),
            "beam_slenderness.span_to_depth": (
                {
                    "span_length": _q("600", "mm", "length"),
                    "section_depth": _q("4", "cm", "length"),
                },
                Fraction(15),
            ),
            "beam_slenderness.effective_squared": (
                {
                    "effective_length_factor": _q("2", "1", "dimensionless"),
                    "unbraced_length": _q("1", "m", "length"),
                    "section_area": _q("100", "mm2", "area"),
                    "second_moment_of_area": _q("1", "cm4", "second_moment_of_area"),
                },
                Fraction(40000),
            ),
            "biot.lumped": (
                {
                    "heat_transfer_coefficient": _q(
                        "25", "W/(m2.K)", "heat_transfer_coefficient"
                    ),
                    "characteristic_length": _q("5", "mm", "length"),
                    "thermal_conductivity": _q("50", "W/(m.K)", "thermal_conductivity"),
                },
                Fraction(1, 400),
            ),
            "time_scale_ratio.response_to_process": (
                {
                    "response_time": _q("2", "s", "time"),
                    "process_time": _q("1", "h", "time"),
                },
                Fraction(1, 1800),
            ),
            "shell_thickness_ratio.thickness_to_radius": (
                {
                    "shell_thickness": _q("3", "mm", "length"),
                    "radius_of_curvature": _q("0.1", "m", "length"),
                },
                Fraction(3, 100),
            ),
            "density_variation.relative": (
                {
                    "density_change": _q("0.05", "kg/m3", "density"),
                    "reference_density": _q("1.2", "kg/m3", "density"),
                },
                Fraction(1, 24),
            ),
        }
        self.assertEqual(set(cases), set(FORMS))
        for form_id, (quantities, expected) in cases.items():
            with self.subTest(form=form_id):
                self.assertEqual(
                    compute_group(FORMS[form_id], quantities, form_id), expected
                )

    def test_dimensional_perturbation_preserves_exact_values(self) -> None:
        form = FORMS["reynolds.dynamic_viscosity"]
        base = compute_group(
            form,
            {
                "density": _q("1.2", "kg/m3", "density"),
                "flow_speed": _q("105.4", "m/s", "velocity"),
                "characteristic_length": _q("0.1", "m", "length"),
                "dynamic_viscosity": _q("0.0000181", "Pa.s", "dynamic_viscosity"),
            },
            "re",
        )
        scaled = compute_group(
            form,
            {
                "density": _q("0.0012", "g/cm3", "density"),
                "flow_speed": _q("379.44", "km/h", "velocity"),
                "characteristic_length": _q("100", "mm", "length"),
                "dynamic_viscosity": _q("0.0181", "mPa.s", "dynamic_viscosity"),
            },
            "re",
        )
        self.assertEqual(base, scaled)
        self.assertEqual(base, Fraction(126480000, 181))
        doubled = compute_group(
            form,
            {
                "density": _q("1.2", "kg/m3", "density"),
                "flow_speed": _q("210.8", "m/s", "velocity"),
                "characteristic_length": _q("0.1", "m", "length"),
                "dynamic_viscosity": _q("0.0000181", "Pa.s", "dynamic_viscosity"),
            },
            "re",
        )
        self.assertEqual(doubled, 2 * base)

    def test_invalid_role_inputs_are_rejected(self) -> None:
        form = FORMS["mach.speed_ratio"]
        speed = _q("10", "m/s", "velocity")
        with self.assertRaisesRegex(InputError, "greater than zero"):
            compute_group(
                form,
                {"flow_speed": speed, "speed_of_sound": _q("0", "m/s", "velocity")},
                "g",
            )
        with self.assertRaisesRegex(InputError, "negative"):
            compute_group(
                form,
                {"flow_speed": _q("-1", "m/s", "velocity"), "speed_of_sound": speed},
                "g",
            )
        with self.assertRaisesRegex(InputError, "missing inputs"):
            compute_group(form, {"flow_speed": speed}, "g")
        with self.assertRaisesRegex(InputError, "unknown roles"):
            compute_group(
                form,
                {"flow_speed": speed, "speed_of_sound": speed, "extra": speed},
                "g",
            )
        with self.assertRaises(DimensionalityError):
            compute_group(
                form,
                {"flow_speed": _q("1", "m", "length"), "speed_of_sound": speed},
                "g",
            )


class RuleSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = _load(RULES_PATH)

    def _rejects(self, error: type[Exception] = InputError, pattern: str = "") -> None:
        with self.assertRaisesRegex(error, pattern):
            parse_rule_set(self.rules)

    def test_example_parses_with_stable_digest(self) -> None:
        rule_set = parse_rule_set(self.rules)
        self.assertEqual(len(rule_set.rules), 9)
        self.assertEqual(rule_set.digest, parse_rule_set(_load(RULES_PATH)).digest)
        self.assertEqual(_load(DUCT_PATH)["rule_set_pin"], rule_set.pin())

    def test_ma_031_marginal_or_violated_per_declared_bands(self) -> None:
        report = _mach_report("105.4", self.rules)
        outcome = _outcome(report, "RULE-MACH-INCOMPRESSIBLE")
        self.assertEqual(outcome["value"], {"rational": "31/100", "decimal": "0.31"})
        self.assertEqual(outcome["outcome"], "marginal")
        strict = copy.deepcopy(self.rules)
        _rule(strict, "RULE-MACH-INCOMPRESSIBLE")["bands"]["marginal"] = []
        report = _mach_report("105.4", strict)
        self.assertEqual(
            _outcome(report, "RULE-MACH-INCOMPRESSIBLE")["outcome"], "violated"
        )
        self.assertEqual(report["applicability_state"], "rules_violated")

    def test_boundary_equalities_follow_declared_inclusivity(self) -> None:
        # 102 / 340 = 0.3 exactly: the valid upper bound is exclusive, the marginal lower bound inclusive.
        self.assertEqual(
            _outcome(_mach_report("102", self.rules), "RULE-MACH-INCOMPRESSIBLE")[
                "outcome"
            ],
            "marginal",
        )
        self.assertEqual(
            _outcome(
                _mach_report("101.99999999", self.rules), "RULE-MACH-INCOMPRESSIBLE"
            )["outcome"],
            "valid",
        )
        # 136 / 340 = 0.4 exactly: the marginal upper bound is exclusive.
        self.assertEqual(
            _outcome(_mach_report("136", self.rules), "RULE-MACH-INCOMPRESSIBLE")[
                "outcome"
            ],
            "violated",
        )
        flipped = copy.deepcopy(self.rules)
        bands = _rule(flipped, "RULE-MACH-INCOMPRESSIBLE")["bands"]
        bands["valid"] = [_band("0", True, "0.3", True)]
        bands["marginal"] = [_band("0.3", False, "0.4", True)]
        self.assertEqual(
            _outcome(_mach_report("102", flipped), "RULE-MACH-INCOMPRESSIBLE")[
                "outcome"
            ],
            "valid",
        )
        self.assertEqual(
            _outcome(_mach_report("136", flipped), "RULE-MACH-INCOMPRESSIBLE")[
                "outcome"
            ],
            "marginal",
        )

    def test_overlapping_reversed_and_empty_bands_are_rejected(self) -> None:
        cases = {
            "touching inclusive": (
                [_band("0", True, "0.3", True)],
                [_band("0.3", True, "0.4", False)],
                "overlap",
            ),
            "nested": (
                [_band("0", True, "0.5", False)],
                [_band("0.3", True, "0.4", False)],
                "overlap",
            ),
            "valid pair": (
                [_band("0", True, "0.3", False), _band("0.2", True, "0.25", False)],
                [],
                "overlap",
            ),
            "unbounded": (
                [_band(None, False, "0.3", False)],
                [_band(None, False, "0.1", False)],
                "overlap",
            ),
            "reversed": ([_band("0.4", True, "0.3", False)], [], "reversed"),
            "empty": ([_band("0.3", True, "0.3", True)], [], "reversed"),
            "no valid band": ([], [_band("0", True, "1", False)], "at least 1"),
        }
        for name, (valid, marginal, pattern) in cases.items():
            with self.subTest(name):
                self.rules = _load(RULES_PATH)
                _rule(self.rules, "RULE-MACH-INCOMPRESSIBLE")["bands"] = {
                    "valid": valid,
                    "marginal": marginal,
                }
                self._rejects(InputError, pattern)
        self.rules = _load(RULES_PATH)
        _rule(self.rules, "RULE-MACH-INCOMPRESSIBLE")["bands"] = {
            "valid": [_band(None, False, "0.3", False)],
            "marginal": [_band("0.3", True, None, False)],
        }
        parse_rule_set(self.rules)

    def test_integral_float_version_is_rejected_by_strict_input_path(self) -> None:
        # JSON Schema 2020-12 treats 1.0 as an integer; the strict loader and parser are the enforcing layer.
        text = RULES_PATH.read_text(encoding="utf-8")
        self.assertEqual(text.count('"rule_version": 1,'), 9)
        with self.assertRaisesRegex(InputError, "floating-point"):
            loads_strict(text.replace('"rule_version": 1,', '"rule_version": 1.0,', 1))
        with self.assertRaisesRegex(InputError, "floating-point"):
            loads_strict(text.replace('"rule_version": 1,', '"rule_version": 1e0,', 1))
        for value in (1.0, 2.0):
            with self.subTest(value=value):
                self.rules = _load(RULES_PATH)
                self.rules["rules"][0]["rule_version"] = value
                self._rejects(InputError, "positive integer")

    def test_stale_registry_pin_is_rejected(self) -> None:
        self.rules["registry"]["digest"] = "sha256:" + "0" * 64
        self._rejects(StalePinError, "registry")
        self.rules = _load(RULES_PATH)
        self.rules["registry"]["version"] = "contrainte.applicability-registry/0.1"
        self._rejects(StalePinError)

    def test_citation_excerpt_tamper_is_integrity_failure(self) -> None:
        self.rules["citations"][0]["excerpt"] += " Edited."
        self._rejects(IntegrityError, "excerpt digest")

    def test_malformed_rule_sets_are_rejected(self) -> None:
        mutations = {
            "approved status": lambda r: r["authoring"].update(status="approved"),
            "unknown top field": lambda r: r.update(extra="x"),
            "unknown rule field": lambda r: r["rules"][0].update(threshold="0.3"),
            "bool version": lambda r: r["rules"][0].update(rule_version=True),
            "string version": lambda r: r["rules"][0].update(rule_version="1"),
            "zero version": lambda r: r["rules"][0].update(rule_version=0),
            "bad rule id": lambda r: r["rules"][0].update(rule_id="rule-mach"),
            "bad set id": lambda r: r.update(rule_set_id="RULESET_X"),
            "duplicate rule id": lambda r: r["rules"][1].update(
                rule_id=r["rules"][0]["rule_id"]
            ),
            "unknown citation": lambda r: r["rules"][0].update(
                citation_ids=["EVD-MISSING"]
            ),
            "no citation": lambda r: r["rules"][0].update(citation_ids=[]),
            "unknown form": lambda r: r["rules"][0]["group"].update(
                form_id="mach.sqrt_gamma_rt"
            ),
            "form group mismatch": lambda r: r["rules"][0]["group"].update(
                group_id="reynolds"
            ),
            "numeric bound": lambda r: r["rules"][0]["bands"]["valid"][0][
                "upper"
            ].update(value=1),
            "bool inclusive": lambda r: r["rules"][0]["bands"]["valid"][0][
                "upper"
            ].update(inclusive="false"),
            "nan bound": lambda r: r["rules"][0]["bands"]["valid"][0]["upper"].update(
                value="NaN"
            ),
            "unknown model form": lambda r: r["rules"][0].update(
                model_form="lattice_boltzmann"
            ),
            "padded text": lambda r: r["rules"][0].update(rationale=" padded"),
            "naive timestamp": lambda r: r["citations"][0].update(
                retrieved_at="2026-10-06T00:00:00"
            ),
            "old schema": lambda r: r.update(
                schema_version="contrainte.applicability-rules/0.0"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name):
                self.rules = _load(RULES_PATH)
                mutate(self.rules)
                self._rejects()


class PhysicsIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = _load(DUCT_PATH)

    def test_examples_parse(self) -> None:
        duct = parse_intent(self.intent)
        self.assertEqual(duct.intent_id, "PHY-DUCT-FLOW-SCREEN")
        self.assertEqual(len(duct.declarations), 4)
        self.assertEqual(parse_intent(_load(BRACKET_PATH)).mode.value, "controlled")

    def test_invalid_intents_are_rejected(self) -> None:
        def bind(intent: dict, role: str, scale_id: str) -> None:
            intent["group_declarations"][0]["bindings"][role] = scale_id

        mutations = {
            "unknown field": (InputError, lambda i: i.update(solver="any")),
            "missing field": (InputError, lambda i: i.pop("failure_modes")),
            "malformed intent id": (
                InputError,
                lambda i: i.update(intent_id="PHY_DUCT"),
            ),
            "output unit mismatch": (
                DimensionalityError,
                lambda i: i["target_outputs"][0].update(unit="m"),
            ),
            "acceptance kind mismatch": (
                DimensionalityError,
                lambda i: i.update(
                    acceptance={
                        "kind": "criteria",
                        "criteria": [
                            {
                                "criterion_id": "ACC-X",
                                "output_id": "QOI-PRESSURE-DROP",
                                "comparator": "le",
                                "rationale": "x",
                                "limit": {
                                    "value": "1",
                                    "unit": "Pa",
                                    "kind": "absolute_pressure",
                                },
                            }
                        ],
                    }
                ),
            ),
            "missing role": (
                InputError,
                lambda i: i["group_declarations"][0]["bindings"].pop("speed_of_sound"),
            ),
            "unknown scale": (
                InputError,
                lambda i: bind(i, "speed_of_sound", "SCL-MISSING"),
            ),
            "role kind mismatch": (
                DimensionalityError,
                lambda i: bind(i, "speed_of_sound", "SCL-DUCT-DIAMETER"),
            ),
            "pressure for stress": (
                DimensionalityError,
                lambda i: i["target_outputs"][0].update(kind="velocity"),
            ),
            "uncited scale": (
                InputError,
                lambda i: i["scales"][0].update(evidence_ids=[], assumption_ids=[]),
            ),
            "assumed without assumption": (
                InputError,
                lambda i: i["scales"][0].update(assumption_ids=[]),
            ),
            "unknown evidence": (
                InputError,
                lambda i: i["scales"][0].update(evidence_ids=["EVD-NOPE"]),
            ),
            "critical without alternatives": (
                InputError,
                lambda i: i.update(criticality="critical", model_form_alternatives=[]),
            ),
            "none_expected combined": (
                InputError,
                lambda i: i["nonlinearities"].append(
                    {"kind": "geometric", "description": "x"}
                ),
            ),
            "specified without conditions": (
                InputError,
                lambda i: i["initial_conditions"].update(relevance="specified"),
            ),
            "unresolved geometry": (
                InputError,
                lambda i: i["boundary_conditions"][0].update(
                    applies_to="FEA-ELSEWHERE"
                ),
            ),
            "modeled and excluded": (
                InputError,
                lambda i: i["geometry"]["excluded"].append(
                    {"ref_id": "FEA-DUCT-FLUID", "reason": "x"}
                ),
            ),
            "bool assumption flag": (
                InputError,
                lambda i: i["assumptions"][0].update(critical="false"),
            ),
            "numeric scale value": (
                InputError,
                lambda i: i["scales"][0]["quantity"].update(value=105),
            ),
            "bool scale value": (
                InputError,
                lambda i: i["scales"][0]["quantity"].update(value=True),
            ),
            "infinite scale value": (
                InputError,
                lambda i: i["scales"][0]["quantity"].update(value="Infinity"),
            ),
            "duplicate scale": (
                InputError,
                lambda i: i["scales"].append(copy.deepcopy(i["scales"][0])),
            ),
            "duplicate domain": (
                InputError,
                lambda i: i["domains"].append(i["domains"][0]),
            ),
            "unknown domain": (
                InputError,
                lambda i: i["domains"].append("plasma_physics"),
            ),
            "available without evidence": (
                InputError,
                lambda i: i["validation_evidence"][0].update(status="available"),
            ),
            "bad pin digest": (
                InputError,
                lambda i: i["rule_set_pin"].update(digest="sha256:ABC"),
            ),
            "no candidate forms": (
                InputError,
                lambda i: i.update(candidate_model_forms=[]),
            ),
            "negative duration": (
                InputError,
                lambda i: i["time"].update(
                    duration={"value": "-1", "unit": "s", "kind": "time"}
                ),
            ),
        }
        for name, (error, mutate) in mutations.items():
            with self.subTest(name):
                intent = _load(DUCT_PATH)
                mutate(intent)
                with self.assertRaises(error):
                    parse_intent(intent)

    def test_duplicate_keys_in_intent_bytes_are_rejected(self) -> None:
        text = DUCT_PATH.read_text(encoding="utf-8").replace(
            '"revision": "A",', '"revision": "A",\n  "revision": "B",', 1
        )
        with self.assertRaisesRegex(InputError, "duplicate"):
            loads_strict(text)


class EvaluationTests(unittest.TestCase):
    def test_duct_example_marginal_creates_warning_and_review_task(self) -> None:
        report = evaluate_documents(_load(DUCT_PATH), _load(RULES_PATH))
        self.assertEqual(report["applicability_state"], "marginal_review_required")
        self.assertEqual(report["output_label"], "exploratory")
        self.assertEqual(
            report["review_tasks"],
            [
                {
                    "task_id": "RVW-1",
                    "kind": "marginal_applicability_review",
                    "rule_id": "RULE-MACH-INCOMPRESSIBLE",
                    "declaration_id": "GRP-MACH",
                    "review_role": "independent_physics_reviewer",
                    "status": "open",
                }
            ],
        )
        self.assertIn("RULE_MARGINAL", _codes(report["warnings"]))
        self.assertIn(
            "MARGINAL_REVIEW_PENDING", _codes(report["qualified_execution"]["blockers"])
        )
        groups = {item["declaration_id"]: item["value"] for item in report["groups"]}
        self.assertEqual(
            groups["GRP-DENSITY-VARIATION"], {"rational": "1/24", "decimal": None}
        )
        self.assertEqual(
            groups["GRP-REYNOLDS"], {"rational": "126480000/181", "decimal": None}
        )
        self.assertEqual(
            _outcome(report, "RULE-REYNOLDS-LAMINAR")["outcome"], "not_selected"
        )
        self.assertEqual(report["claim_boundary"], CLAIM_BOUNDARY)

    def test_authority_is_never_granted(self) -> None:
        for report in (
            evaluate_documents(_load(DUCT_PATH), _load(RULES_PATH)),
            evaluate_documents(*_qualified_clean()),
        ):
            self.assertEqual(
                report["authority"],
                {
                    "release_authority": False,
                    "approval_authority": False,
                    "write_authority": False,
                    "control_authority": False,
                    "human_review_required": True,
                },
            )
            self.assertFalse(report["authority_promotion_permitted"])
            self.assertFalse(report["qualified_execution"]["permitted"])
            self.assertEqual(report["qualification_level"], "none")
            self.assertEqual(report["unsupported"]["execution_available_domains"], [])

    def test_bracket_violation_blocks_controlled_and_lists_escalation(self) -> None:
        report = evaluate_documents(_load(BRACKET_PATH), _load(RULES_PATH))
        self.assertEqual(report["applicability_state"], "rules_violated")
        violated = _outcome(report, "RULE-BEAM-SPAN-DEPTH")
        self.assertEqual(
            (violated["outcome"], violated["value"]["rational"]), ("violated", "15/2")
        )
        self.assertEqual(
            violated["escalation_model_forms"], ["timoshenko_beam", "continuum_solid"]
        )
        self.assertEqual(
            _outcome(report, "RULE-COLUMN-SLENDERNESS")["reason"], "group_not_declared"
        )
        self.assertEqual(report["controlled_review_readiness"]["state"], "blocked")
        self.assertIn(
            "RULE_VIOLATED", _codes(report["controlled_review_readiness"]["blockers"])
        )

    def test_exploration_keeps_violations_visible_without_promotion(self) -> None:
        intent = _load(BRACKET_PATH)
        intent["requested_mode"] = "exploration"
        report = evaluate_documents(intent, _load(RULES_PATH))
        self.assertEqual(report["output_label"], "exploratory")
        self.assertEqual(report["applicability_state"], "rules_violated")
        self.assertIn("RULE_VIOLATED", _codes(report["warnings"]))
        self.assertIn(
            "RULE_VIOLATED", _codes(report["qualified_execution"]["blockers"])
        )
        self.assertFalse(report["authority_promotion_permitted"])

    def test_qualified_mode_clean_rules_with_synthetic_inputs_is_not_ready(
        self,
    ) -> None:
        # Review finding B2/F2a: every bound input cites only synthetic evidence and an open assumption.
        report = evaluate_documents(*_qualified_clean())
        self.assertEqual(report["applicability_state"], "rules_satisfied")
        # Every scale bound in any group declaration feeds a computed group and is gated.
        bound = {
            "SCL-FLOW-SPEED",
            "SCL-SPEED-OF-SOUND",
            "SCL-DENSITY-CHANGE",
            "SCL-AIR-DENSITY",
            "SCL-DUCT-DIAMETER",
            "SCL-AIR-VISCOSITY",
            "SCL-MEAN-FREE-PATH",
        }
        for gate in (
            report["qualified_execution"]["blockers"],
            report["controlled_review_readiness"]["blockers"],
        ):
            subjects = [
                item["subject"]
                for item in gate
                if item["code"] == "INPUT_SUPPORT_NOT_QUALIFYING"
            ]
            self.assertEqual(sorted(subjects), sorted(bound))
        # The unbound environment scale (inlet pressure) is reported but not gated.
        self.assertNotIn(
            "SCL-INLET-PRESSURE",
            {
                item["subject"]
                for item in report["controlled_review_readiness"]["blockers"]
            },
        )
        self.assertEqual(report["controlled_review_readiness"]["state"], "blocked")
        self.assertIn("SYNTHETIC_INPUT_EVIDENCE", _codes(report["warnings"]))
        self.assertEqual(report["output_label"], "non_release")

    def test_qualified_mode_clean_rules_supported_inputs_has_structural_blockers_only(
        self,
    ) -> None:
        report = evaluate_documents(*_qualified_supported())
        self.assertEqual(report["applicability_state"], "rules_satisfied")
        self.assertEqual(
            _codes(report["qualified_execution"]["blockers"]), STRUCTURAL_BLOCKERS
        )
        self.assertEqual(
            report["controlled_review_readiness"],
            {"state": "ready_for_independent_review", "blockers": []},
        )
        self.assertEqual(report["warnings"], [])

    def _knudsen_report(self, mean_free_path_mm: str) -> dict:
        # Duct diameter is 100 mm, so Kn = mean_free_path_mm / 100 against valid [0, 0.01), marginal [0.01, 0.1).
        intent, rules = _qualified_supported()
        _scale(intent, "SCL-MEAN-FREE-PATH")["quantity"] = {
            "value": mean_free_path_mm,
            "unit": "mm",
            "kind": "length",
        }
        return evaluate_documents(intent, rules)

    def test_qualified_mode_violation_blocks_execution(self) -> None:
        report = self._knudsen_report("20")
        self.assertEqual(
            _outcome(report, "RULE-KNUDSEN-CONTINUUM")["value"],
            {"rational": "1/5", "decimal": "0.2"},
        )
        self.assertEqual(report["applicability_state"], "rules_violated")
        self.assertIn(
            {"code": "RULE_VIOLATED", "subject": "RULE-KNUDSEN-CONTINUUM/GRP-KNUDSEN"},
            report["qualified_execution"]["blockers"],
        )
        self.assertIn(
            "RULE_VIOLATED", _codes(report["controlled_review_readiness"]["blockers"])
        )
        self.assertEqual(report["review_tasks"], [])

    def test_qualified_mode_knudsen_band_neighbours(self) -> None:
        cases = (
            ("0.99999", "valid", "rules_satisfied"),
            (
                "1",
                "marginal",
                "marginal_review_required",
            ),  # Kn = 0.01, inclusive marginal lower bound
            (
                "2",
                "marginal",
                "marginal_review_required",
            ),  # Kn = 0.02, inside the marginal band
            ("9.99999", "marginal", "marginal_review_required"),
            (
                "10",
                "violated",
                "rules_violated",
            ),  # Kn = 0.1, exclusive marginal upper bound
        )
        for value, outcome, state in cases:
            with self.subTest(mean_free_path_mm=value):
                report = self._knudsen_report(value)
                self.assertEqual(
                    _outcome(report, "RULE-KNUDSEN-CONTINUUM")["outcome"], outcome
                )
                self.assertEqual(report["applicability_state"], state)
                qualified = _codes(report["qualified_execution"]["blockers"])
                controlled = report["controlled_review_readiness"]
                self.assertFalse(report["qualified_execution"]["permitted"])
                if outcome == "marginal":
                    self.assertEqual(len(report["review_tasks"]), 1)
                    self.assertIn("MARGINAL_REVIEW_PENDING", qualified)
                    self.assertNotIn("RULE_VIOLATED", qualified)
                    self.assertEqual(
                        controlled["state"], "ready_for_independent_review"
                    )
                elif outcome == "violated":
                    self.assertIn("RULE_VIOLATED", qualified)
                    self.assertEqual(controlled["state"], "blocked")
                else:
                    self.assertEqual(qualified, STRUCTURAL_BLOCKERS)

    def test_gate_inputs_create_blockers(self) -> None:
        intent, rules = _qualified_supported()
        intent["candidate_model_forms"].append("turbulent_flow")
        _scale(intent, "SCL-MEAN-FREE-PATH")["basis"] = "ai_proposed"
        intent["assumptions"][0]["critical"] = True
        report = evaluate_documents(intent, rules)
        self.assertEqual(report["applicability_state"], "indeterminate")
        self.assertEqual(
            report["model_form_outcomes"][-1],
            {
                "model_form": "turbulent_flow",
                "state": "no_rule",
                "rule_ids": [],
                "required_groups": ["reynolds"],
                "missing_required_groups": ["reynolds"],
                "unevaluated_considerations": [
                    "wall_treatment",
                    "separation",
                    "target_quantity_sensitivity",
                ],
            },
        )
        controlled = _codes(report["controlled_review_readiness"]["blockers"])
        self.assertEqual(
            controlled,
            {
                "MODEL_FORM_WITHOUT_RULE",
                "REQUIRED_GROUP_NOT_COVERED",
                "CONSIDERATION_NOT_EVALUATED",
                "AI_PROPOSED_INPUT",
                "OPEN_CRITICAL_ASSUMPTION",
            },
        )

    def test_stale_rule_set_pin_is_rejected(self) -> None:
        intent, rules = _load(DUCT_PATH), _load(RULES_PATH)
        _rule(rules, "RULE-MACH-INCOMPRESSIBLE")["bands"]["marginal"] = []
        with self.assertRaises(StalePinError):
            evaluate_documents(intent, rules)
        intent = _load(DUCT_PATH)
        intent["rule_set_pin"]["revision"] = "2"
        with self.assertRaises(StalePinError):
            evaluate_documents(intent, _load(RULES_PATH))

    def test_evaluation_is_deterministic_and_order_independent_for_keys(self) -> None:
        first = evaluate_documents(_load(DUCT_PATH), _load(RULES_PATH))
        reordered = dict(reversed(list(_load(DUCT_PATH).items())))
        second = evaluate_documents(reordered, _load(RULES_PATH))
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        body = {key: value for key, value in first.items() if key != "report_digest"}
        self.assertEqual(first["report_digest"], digest(body))


class VerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phys-test-")
        self.directory = Path(self.temp.name) / "bundle"
        self.intent, self.rules = _load(DUCT_PATH), _load(RULES_PATH)
        self.report = evaluate_documents(self.intent, self.rules)
        write_bundle(self.directory, self.intent, self.rules, self.report)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_retained_bundle_verifies(self) -> None:
        self.assertEqual(verify_bundle(self.directory), self.report)
        self.assertEqual(
            verify_report(self.report, self.intent, self.rules), self.report
        )

    def test_tamper_without_rehash_fails_digest(self) -> None:
        tampered = copy.deepcopy(self.report)
        tampered["applicability_state"] = "rules_satisfied"
        with self.assertRaisesRegex(IntegrityError, "digest"):
            verify_report(tampered, self.intent, self.rules)

    def test_tamper_with_rehash_fails_recomputation(self) -> None:
        for mutate in (
            lambda r: r.update(applicability_state="rules_satisfied"),
            lambda r: r.update(review_tasks=[]),
            lambda r: r["groups"][0]["value"].update(rational="3/10", decimal="0.3"),
            lambda r: r["authority"].update(release_authority=True),
        ):
            tampered = copy.deepcopy(self.report)
            mutate(tampered)
            tampered["report_digest"] = digest(
                {k: v for k, v in tampered.items() if k != "report_digest"}
            )
            with (
                self.subTest(),
                self.assertRaisesRegex(IntegrityError, "recomputation"),
            ):
                verify_report(tampered, self.intent, self.rules)

    def test_report_bound_to_other_inputs_fails(self) -> None:
        other = copy.deepcopy(self.intent)
        other["title"] = "A different intent"
        with self.assertRaisesRegex(IntegrityError, "bound to different"):
            verify_report(self.report, other, self.rules)

    def test_tampered_retained_input_fails(self) -> None:
        path = self.directory / INTENT_FILE
        intent = loads_strict(path.read_bytes())
        _scale(intent, "SCL-FLOW-SPEED")["quantity"]["value"] = "360"
        path.write_bytes(canonical_bytes(intent))
        with self.assertRaises(IntegrityError):
            verify_bundle(self.directory)

    def test_non_canonical_retained_file_fails(self) -> None:
        path = self.directory / REPORT_FILE
        path.write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(IntegrityError, "not canonical"):
            verify_bundle(self.directory)


class SchemaTests(unittest.TestCase):
    def test_exported_schema_files_match_generator(self) -> None:
        for name, (filename, _) in SCHEMAS.items():
            with self.subTest(name):
                self.assertEqual(
                    (ROOT / "schemas" / filename).read_text(encoding="utf-8"),
                    schema_text(name),
                )

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_documents_validate_and_invalid_documents_fail(self) -> None:
        validators = {
            name: Draft202012Validator(json.loads(schema_text(name)))
            for name in SCHEMAS
        }
        for validator in validators.values():
            Draft202012Validator.check_schema(validator.schema)
        intent, rules = _load(DUCT_PATH), _load(RULES_PATH)
        validators["intent"].validate(intent)
        validators["intent"].validate(_load(BRACKET_PATH))
        validators["rules"].validate(rules)
        for document in (
            evaluate_documents(intent, rules),
            evaluate_documents(_load(BRACKET_PATH), rules),
            evaluate_documents(*_qualified_clean()),
            evaluate_documents(*_qualified_supported()),
            evaluate_documents(*_turbulent_case()),
        ):
            validators["report"].validate(document)
        for form, entry in MODEL_FORMS.items():
            with self.subTest(form=form.value):
                validators["report"].validate(
                    _evaluate_form(form, entry.required_groups)
                )
                validators["report"].validate(
                    _evaluate_form(form, entry.required_groups[1:])
                )
        bad_intents = [
            lambda i: i.update(extra="x"),
            lambda i: i["scales"][0]["quantity"].update(value=105),
            lambda i: i["scales"][0]["quantity"].update(value="NaN"),
            lambda i: i.update(intent_id="phy-1"),
            lambda i: i["assumptions"][0].update(critical="no"),
        ]
        for mutate in bad_intents:
            document = _load(DUCT_PATH)
            mutate(document)
            with self.subTest():
                self.assertFalse(validators["intent"].is_valid(document))
        bad_rule_mutations = [
            lambda r: r["rules"][0].update(rule_version=True),
            lambda r: r["rules"][0].update(rule_version="1"),
            lambda r: r["rules"][0].update(rule_version=0),
            lambda r: r["rules"][0].update(rule_version=1.5),
            lambda r: r["authoring"].update(status="approved"),
            lambda r: r["rules"][0]["bands"]["valid"][0]["upper"].update(value=0.3),
            lambda r: r["rules"][0]["bands"].update(valid=[]),
            lambda r: r["rules"][0].update(rule_id="rule-mach"),
            lambda r: r.update(extra="x"),
        ]
        for mutate in bad_rule_mutations:
            document = copy.deepcopy(rules)
            mutate(document)
            with self.subTest():
                self.assertFalse(validators["rules"].is_valid(document))
        bad_report = evaluate_documents(intent, rules)
        bad_report["authority"]["release_authority"] = True
        self.assertFalse(validators["report"].is_valid(bad_report))


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phys-cli-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def _write(self, name: str, document: dict) -> str:
        path = self.root / name
        path.write_bytes(canonical_bytes(document))
        return str(path)

    def test_evaluate_exit_statuses_reflect_state(self) -> None:
        intent, rules = _qualified_clean()
        cases = (
            (
                self._write("clean.json", intent),
                self._write("clean-rules.json", rules),
                0,
            ),
            (str(DUCT_PATH), str(RULES_PATH), 10),
            (str(BRACKET_PATH), str(RULES_PATH), 12),
        )
        for index, (intent_path, rules_path, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                out_dir = self.root / f"out-{index}"
                code, out, _ = self._run(
                    "evaluate", intent_path, rules_path, "-o", str(out_dir)
                )
                self.assertEqual(code, expected)
                self.assertTrue(json.loads(out)["verified"])
                self.assertEqual(self._run("verify", str(out_dir))[0], 0)
                code, _, _ = self._run(
                    "verify",
                    str(out_dir / REPORT_FILE),
                    "--intent",
                    intent_path,
                    "--rules",
                    rules_path,
                )
                self.assertEqual(code, 0)

    def test_indeterminate_exit_status(self) -> None:
        intent = _load(DUCT_PATH)
        intent["candidate_model_forms"] = ["continuum_flow", "turbulent_flow"]
        code, _, _ = self._run(
            "evaluate",
            self._write("i.json", intent),
            str(RULES_PATH),
            "-o",
            str(self.root / "o"),
        )
        self.assertEqual(code, 11)

    def test_rejections_use_documented_exit_statuses(self) -> None:
        bad = _load(DUCT_PATH)
        bad["scales"][0]["quantity"]["unit"] = "m"
        code, _, err = self._run(
            "evaluate",
            self._write("bad.json", bad),
            str(RULES_PATH),
            "-o",
            str(self.root / "x"),
        )
        self.assertEqual((code, err.startswith("input rejected")), (3, True))
        self.assertFalse((self.root / "x").exists())
        float_path = self.root / "float.json"
        float_path.write_text(
            DUCT_PATH.read_text(encoding="utf-8").replace('"379.44"', "379.44"),
            encoding="utf-8",
        )
        self.assertEqual(
            self._run(
                "evaluate", str(float_path), str(RULES_PATH), "-o", str(self.root / "y")
            )[0],
            3,
        )
        stale = _load(DUCT_PATH)
        stale["rule_set_pin"]["digest"] = "sha256:" + "a" * 64
        code, _, err = self._run(
            "evaluate",
            self._write("stale.json", stale),
            str(RULES_PATH),
            "-o",
            str(self.root / "z"),
        )
        self.assertEqual((code, err.startswith("stale pin")), (4, True))
        out_dir = self.root / "good"
        self._run("evaluate", str(DUCT_PATH), str(RULES_PATH), "-o", str(out_dir))
        report = loads_strict((out_dir / REPORT_FILE).read_bytes())
        report["review_tasks"] = []
        (out_dir / REPORT_FILE).write_bytes(canonical_bytes(report))
        self.assertEqual(self._run("verify", str(out_dir))[0], 5)
        self.assertEqual(
            self._run("verify", str(out_dir / REPORT_FILE), "--intent", str(DUCT_PATH))[
                0
            ],
            2,
        )
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            main(["evaluate"])
        self.assertEqual(raised.exception.code, 2)

    def test_auxiliary_commands(self) -> None:
        code, out, _ = self._run("rules-pin", str(RULES_PATH))
        self.assertEqual((code, json.loads(out)), (0, _load(DUCT_PATH)["rule_set_pin"]))
        code, out, _ = self._run("groups")
        self.assertEqual(code, 0)
        self.assertEqual(digest(json.loads(out)), registry_digest())
        target = self.root / "intent.schema.json"
        self.assertEqual(self._run("schema", "intent", "--output", str(target))[0], 0)
        self.assertEqual(target.read_text(encoding="utf-8"), schema_text("intent"))
        self.assertEqual(
            digest_bytes(target.read_bytes()),
            digest_bytes(schema_text("intent").encode("utf-8")),
        )


_SI_UNIT = {
    "velocity": "m/s",
    "density": "kg/m3",
    "length": "m",
    "dynamic_viscosity": "Pa.s",
    "kinematic_viscosity": "m2/s",
    "dimensionless": "1",
    "area": "m2",
    "second_moment_of_area": "m4",
    "heat_transfer_coefficient": "W/(m2.K)",
    "thermal_conductivity": "W/(m.K)",
    "time": "s",
}
_WHOLE_LINE = {"valid": [_band(None, False, None, False)], "marginal": []}


def _token(text: str) -> str:
    return text.upper().replace("_", "-")


def _all_groups_intent() -> dict:
    """Duct intent (real evidence) declaring one form of every group with dedicated scales."""

    intent, _ = _qualified_supported()
    intent["requested_mode"] = "controlled"
    intent["scales"] = []
    intent["group_declarations"] = []
    intent["environment"]["conditions"] = []
    for group_id in sorted({form.group_id for form in FORMS.values()}):
        form = next(item for item in FORMS.values() if item.group_id == group_id)
        bindings = {}
        for role in form.roles:
            scale_id = f"SCL-{_token(group_id)}-{_token(role.role)}"
            intent["scales"].append(
                {
                    "scale_id": scale_id,
                    "description": f"{group_id} {role.role}",
                    "quantity": {
                        "value": "1",
                        "unit": _SI_UNIT[role.kind],
                        "kind": role.kind,
                    },
                    "basis": "measured",
                    "evidence_ids": ["EVD-EXAMPLE-INPUTS"],
                    "assumption_ids": [],
                }
            )
            bindings[role.role] = scale_id
        intent["group_declarations"].append(
            {
                "declaration_id": f"GRP-{_token(group_id)}",
                "group_id": group_id,
                "form_id": form.form_id,
                "bindings": bindings,
            }
        )
    return intent


def _form_rules(model_form: ModelForm, groups: tuple[str, ...]) -> dict:
    rules = _load(RULES_PATH)
    rules["citations"][0]["kind"] = "engineering_rationale"
    template = rules["rules"][0]
    rules["rules"] = []
    for group_id in groups:
        form = next(item for item in FORMS.values() if item.group_id == group_id)
        rule = copy.deepcopy(template)
        rule.pop("escalation_model_forms", None)
        rule.update(
            rule_id=f"RULE-{_token(model_form.value)}-{_token(group_id)}",
            model_form=model_form.value,
            group={"group_id": group_id, "form_id": form.form_id},
            bands=copy.deepcopy(_WHOLE_LINE),
        )
        rules["rules"].append(rule)
    return rules


def _evaluate_form(model_form: ModelForm, groups: tuple[str, ...]) -> dict:
    intent = _all_groups_intent()
    intent["candidate_model_forms"] = [model_form.value]
    intent["model_form_alternatives"] = []
    rules = _form_rules(model_form, groups)
    if not rules["rules"]:
        # A rule set needs one rule; use an admissible rule for a different, non-candidate form.
        other = (
            ModelForm.CONTINUUM_FLOW
            if model_form is not ModelForm.CONTINUUM_FLOW
            else ModelForm.RAREFIED_FLOW
        )
        rules = _form_rules(other, ("knudsen",))
    return evaluate_documents(_repin(intent, rules), rules)


def _turbulent_case() -> tuple[dict, dict]:
    """Review probe F1c: turbulent flow gated only by a Reynolds rule."""

    intent, rules = _qualified_supported()
    rule = copy.deepcopy(_rule(rules, "RULE-REYNOLDS-LAMINAR"))
    rule.update(
        rule_id="RULE-TURBULENT",
        model_form="turbulent_flow",
        title="Turbulent by Reynolds",
    )
    rule["bands"] = {"valid": [_band("4000", True, None, False)], "marginal": []}
    rules["rules"].append(rule)
    intent["requested_mode"] = "controlled"
    intent["candidate_model_forms"] = ["turbulent_flow"]
    return _repin(intent, rules), rules


def _considerations(form: ModelForm) -> list[str]:
    return [item.consideration_id for item in MODEL_FORMS[form].unevaluated]


class ModelFormCoverageTests(unittest.TestCase):
    def test_table_covers_every_model_form_and_is_bound_into_registry_digest(
        self,
    ) -> None:
        self.assertEqual(set(MODEL_FORMS), set(ModelForm))
        group_ids = {form.group_id for form in FORMS.values()}
        described = {
            item["model_form"]: item for item in registry_description()["model_forms"]
        }
        self.assertEqual(set(described), {form.value for form in ModelForm})
        self.assertEqual(registry_description()["version"], REGISTRY_VERSION)
        self.assertEqual(digest(registry_description()), registry_digest())
        for form, entry in MODEL_FORMS.items():
            with self.subTest(form=form.value):
                self.assertLessEqual(
                    set(entry.required_groups), set(entry.admissible_groups)
                )
                self.assertLessEqual(set(entry.admissible_groups), group_ids)
                self.assertTrue(entry.required_groups or entry.unevaluated)
                self.assertEqual(described[form.value], entry.as_dict())
        # Section 13.3 considerations are encoded, not silently dropped.
        self.assertEqual(
            MODEL_FORMS[ModelForm.INCOMPRESSIBLE_FLOW].required_groups,
            ("mach", "density_variation"),
        )
        self.assertEqual(
            _considerations(ModelForm.TURBULENT_FLOW),
            ["wall_treatment", "separation", "target_quantity_sensitivity"],
        )
        self.assertEqual(
            _considerations(ModelForm.LINEAR_ELASTIC),
            ["strain_magnitude", "material_behavior", "contact", "geometric_change"],
        )
        self.assertEqual(
            _considerations(ModelForm.EULER_BERNOULLI_BEAM), ["local_stress_needs"]
        )
        self.assertEqual(
            _considerations(ModelForm.THIN_SHELL), ["through_thickness_effects"]
        )

    def test_every_model_form_with_full_required_coverage(self) -> None:
        for form, entry in MODEL_FORMS.items():
            with self.subTest(form=form.value):
                report = _evaluate_form(form, entry.required_groups)
                outcome = report["model_form_outcomes"][0]
                considerations = _considerations(form)
                self.assertEqual(
                    outcome["required_groups"], list(entry.required_groups)
                )
                self.assertEqual(outcome["missing_required_groups"], [])
                self.assertEqual(outcome["unevaluated_considerations"], considerations)
                controlled = _codes(report["controlled_review_readiness"]["blockers"])
                if not entry.required_groups:
                    self.assertEqual(outcome["state"], "no_rule")
                    self.assertEqual(report["applicability_state"], "indeterminate")
                    self.assertIn("MODEL_FORM_WITHOUT_RULE", controlled)
                elif considerations:
                    self.assertEqual(outcome["state"], "considerations_unevaluated")
                    self.assertEqual(
                        report["applicability_state"], "considerations_review_required"
                    )
                else:
                    self.assertEqual(outcome["state"], "applicable")
                    self.assertEqual(report["applicability_state"], "rules_satisfied")
                    self.assertEqual(
                        report["controlled_review_readiness"],
                        {"state": "ready_for_independent_review", "blockers": []},
                    )
                if considerations:
                    subjects = {
                        item["subject"]
                        for item in report["warnings"]
                        if item["code"] == "CONSIDERATION_NOT_EVALUATED"
                    }
                    self.assertEqual(
                        subjects, {f"{form.value}/{item}" for item in considerations}
                    )
                    self.assertIn("CONSIDERATION_NOT_EVALUATED", controlled)
                    self.assertEqual(
                        report["controlled_review_readiness"]["state"], "blocked"
                    )

    def test_every_missing_required_group_is_indeterminate(self) -> None:
        for form, entry in MODEL_FORMS.items():
            for missing in entry.required_groups:
                remaining = tuple(
                    item for item in entry.required_groups if item != missing
                )
                with self.subTest(form=form.value, missing=missing):
                    report = _evaluate_form(form, remaining)
                    outcome = report["model_form_outcomes"][0]
                    self.assertEqual(outcome["missing_required_groups"], [missing])
                    self.assertEqual(
                        outcome["state"], "indeterminate" if remaining else "no_rule"
                    )
                    self.assertEqual(report["applicability_state"], "indeterminate")
                    self.assertIn(
                        {
                            "code": "REQUIRED_GROUP_NOT_COVERED",
                            "subject": f"{form.value}/{missing}",
                        },
                        report["controlled_review_readiness"]["blockers"],
                    )
                    self.assertEqual(
                        report["controlled_review_readiness"]["state"], "blocked"
                    )

    def test_every_inadmissible_group_is_rejected_for_every_model_form(self) -> None:
        group_ids = sorted({form.group_id for form in FORMS.values()})
        for form, entry in MODEL_FORMS.items():
            for group_id in group_ids:
                rules = _form_rules(form, (group_id,))
                with self.subTest(form=form.value, group=group_id):
                    if group_id in entry.admissible_groups:
                        parse_rule_set(rules)
                    else:
                        with self.assertRaisesRegex(InputError, "not admissible"):
                            parse_rule_set(rules)

    def test_review_probe_f1a_incompressible_mach_only_is_indeterminate(self) -> None:
        intent, rules = _qualified_supported()
        rules["rules"] = [
            item
            for item in rules["rules"]
            if item["rule_id"] != "RULE-DENSITY-VARIATION-INCOMPRESSIBLE"
        ]
        intent["requested_mode"] = "controlled"
        intent["candidate_model_forms"] = ["incompressible_flow"]
        intent["group_declarations"] = [
            item
            for item in intent["group_declarations"]
            if item["group_id"] != "density_variation"
        ]
        _scale(intent, "SCL-FLOW-SPEED")["quantity"] = {
            "value": "50",
            "unit": "m/s",
            "kind": "velocity",
        }
        report = evaluate_documents(_repin(intent, rules), rules)
        self.assertEqual(
            _outcome(report, "RULE-MACH-INCOMPRESSIBLE")["outcome"], "valid"
        )
        self.assertEqual(report["model_form_outcomes"][0]["state"], "indeterminate")
        self.assertEqual(
            report["model_form_outcomes"][0]["missing_required_groups"],
            ["density_variation"],
        )
        self.assertEqual(report["applicability_state"], "indeterminate")
        self.assertEqual(
            report["controlled_review_readiness"],
            {
                "state": "blocked",
                "blockers": [
                    {
                        "code": "REQUIRED_GROUP_NOT_COVERED",
                        "subject": "incompressible_flow/density_variation",
                    }
                ],
            },
        )

    def test_review_probe_f1b_linear_elastic_on_knudsen_is_rejected(self) -> None:
        rules = _load(RULES_PATH)
        rule = copy.deepcopy(_rule(rules, "RULE-KNUDSEN-CONTINUUM"))
        rule.update(rule_id="RULE-LINEAR-ELASTIC", model_form="linear_elastic")
        rules["rules"].append(rule)
        with self.assertRaisesRegex(
            InputError, "'knudsen' is not admissible for model form 'linear_elastic'"
        ):
            parse_rule_set(rules)

    def test_review_probe_f1c_turbulent_reynolds_only_requires_consideration_review(
        self,
    ) -> None:
        report = evaluate_documents(*_turbulent_case())
        self.assertEqual(_outcome(report, "RULE-TURBULENT")["outcome"], "valid")
        self.assertEqual(
            report["model_form_outcomes"][0]["state"], "considerations_unevaluated"
        )
        self.assertEqual(
            report["applicability_state"], "considerations_review_required"
        )
        expected = [
            {"code": "CONSIDERATION_NOT_EVALUATED", "subject": f"turbulent_flow/{item}"}
            for item in ("wall_treatment", "separation", "target_quantity_sensitivity")
        ]
        self.assertEqual(
            report["controlled_review_readiness"],
            {"state": "blocked", "blockers": expected},
        )
        for item in expected:
            self.assertIn(item, report["qualified_execution"]["blockers"])

    def test_violation_and_marginal_outrank_considerations(self) -> None:
        intent, rules = _turbulent_case()
        _rule(rules, "RULE-TURBULENT")["bands"] = {
            "valid": [_band("1000000", True, None, False)],
            "marginal": [_band("500000", True, "1000000", False)],
        }
        # Re = 126480000/181 (about 698785) with the duct inputs: marginal.
        report = evaluate_documents(_repin(intent, rules), rules)
        self.assertEqual(report["applicability_state"], "marginal_review_required")
        self.assertIn(
            "CONSIDERATION_NOT_EVALUATED",
            _codes(report["controlled_review_readiness"]["blockers"]),
        )
        _rule(rules, "RULE-TURBULENT")["bands"]["marginal"] = []
        report = evaluate_documents(_repin(intent, rules), rules)
        self.assertEqual(report["applicability_state"], "rules_violated")
        self.assertEqual(report["model_form_outcomes"][0]["state"], "violated")


class InputSupportTests(unittest.TestCase):
    def _report(
        self,
        evidence: list[str],
        assumption_status: str | None,
        *,
        basis: str = "measured",
    ) -> dict:
        """Evaluate with SCL-MEAN-FREE-PATH supported by the given evidence kinds and assumption status."""

        intent, rules = _qualified_supported()
        intent["requested_mode"] = "controlled"
        intent["evidence"] = [
            {
                "evidence_id": f"EVD-SUPPORT-{index}",
                "kind": kind,
                "title": f"support {index}",
                "locator": "test",
                "content_digest": "sha256:" + "1" * 64,
            }
            for index, kind in enumerate(["measurement_record", *evidence])
        ]
        intent["assumptions"][0]["status"] = assumption_status or "open"
        for item in intent["scales"]:
            item["evidence_ids"] = ["EVD-SUPPORT-0"]
            item["assumption_ids"] = []
            item["basis"] = "measured"
        target = _scale(intent, "SCL-MEAN-FREE-PATH")
        target["basis"] = basis
        target["evidence_ids"] = [
            f"EVD-SUPPORT-{index + 1}" for index in range(len(evidence))
        ]
        target["assumption_ids"] = (
            [] if assumption_status is None else ["ASM-EXAMPLE-VALUES"]
        )
        return evaluate_documents(_repin(intent, rules), rules)

    def test_support_combinations(self) -> None:
        cases = (
            (["synthetic_illustration"], None, False),
            (["synthetic_illustration"], "open", False),
            ([], "open", False),
            (["synthetic_illustration", "synthetic_illustration"], None, False),
            (["synthetic_illustration"], "accepted", True),
            ([], "accepted", True),
            (["measurement_record"], None, True),
            (["synthetic_illustration", "test_record"], None, True),
            (["human_rationale"], "open", True),
            (["standard"], None, True),
        )
        gate = {"code": "INPUT_SUPPORT_NOT_QUALIFYING", "subject": "SCL-MEAN-FREE-PATH"}
        for evidence, assumption, qualifies in cases:
            with self.subTest(evidence=evidence, assumption=assumption):
                report = self._report(evidence, assumption)
                if qualifies:
                    self.assertNotIn(gate, report["qualified_execution"]["blockers"])
                    self.assertEqual(
                        report["controlled_review_readiness"],
                        {"state": "ready_for_independent_review", "blockers": []},
                    )
                else:
                    self.assertIn(gate, report["qualified_execution"]["blockers"])
                    self.assertEqual(
                        report["controlled_review_readiness"],
                        {"state": "blocked", "blockers": [gate]},
                    )
                synthetic_warning = {
                    item["subject"]
                    for item in report["warnings"]
                    if item["code"] == "SYNTHETIC_INPUT_EVIDENCE"
                }
                self.assertEqual(
                    synthetic_warning,
                    {"SCL-MEAN-FREE-PATH"}
                    if "synthetic_illustration" in evidence
                    else set(),
                )

    def test_review_probe_f2a_measured_basis_with_synthetic_evidence_is_blocked(
        self,
    ) -> None:
        report = self._report(["synthetic_illustration"], None, basis="measured")
        self.assertEqual(report["applicability_state"], "rules_satisfied")
        self.assertEqual(
            report["controlled_review_readiness"],
            {
                "state": "blocked",
                "blockers": [
                    {
                        "code": "INPUT_SUPPORT_NOT_QUALIFYING",
                        "subject": "SCL-MEAN-FREE-PATH",
                    }
                ],
            },
        )

    def test_unbound_scales_do_not_gate(self) -> None:
        intent, rules = _qualified_supported()
        intent["evidence"].append(
            {
                "evidence_id": "EVD-SYNTHETIC-CONTEXT",
                "kind": "synthetic_illustration",
                "title": "context",
                "locator": "test",
                "content_digest": "sha256:" + "2" * 64,
            }
        )
        context = _scale(intent, "SCL-INLET-PRESSURE")
        context["evidence_ids"] = ["EVD-SYNTHETIC-CONTEXT"]
        context["assumption_ids"] = []
        context["basis"] = "measured"
        report = evaluate_documents(_repin(intent, rules), rules)
        self.assertEqual(
            report["controlled_review_readiness"]["state"],
            "ready_for_independent_review",
        )

    def test_review_probe_f2b_retired_assumptions_cannot_support_live_inputs(
        self,
    ) -> None:
        for critical in (True, False):
            for with_evidence in (True, False):
                with self.subTest(critical=critical, with_evidence=with_evidence):
                    intent, _ = _qualified_supported()
                    intent["assumptions"][0].update(status="retired", critical=critical)
                    if not with_evidence:
                        for item in intent["scales"]:
                            item["evidence_ids"] = []
                    with self.assertRaisesRegex(InputError, "retired assumptions"):
                        parse_intent(intent)
        intent, _ = _qualified_supported()
        intent["assumptions"][0]["status"] = "retired"
        for item in intent["scales"]:
            item["assumption_ids"] = []
            item["basis"] = "measured"
        parse_intent(intent)  # An unreferenced retired assumption remains recordable.

    def test_scale_bound_to_two_roles_and_rejected_candidates_are_rejected(
        self,
    ) -> None:
        intent = _load(DUCT_PATH)
        knudsen = next(
            item
            for item in intent["group_declarations"]
            if item["group_id"] == "knudsen"
        )
        knudsen["bindings"]["mean_free_path"] = "SCL-DUCT-DIAMETER"
        with self.assertRaisesRegex(InputError, "at most one role"):
            parse_intent(intent)
        intent = _load(DUCT_PATH)
        intent["model_form_alternatives"].append(
            {
                "model_form": "continuum_flow",
                "disposition": "rejected",
                "rationale": "x",
            }
        )
        with self.assertRaisesRegex(InputError, "rejected in model_form_alternatives"):
            parse_intent(intent)


class VersioningTests(unittest.TestCase):
    def test_superseded_unpublished_drafts_are_rejected(self) -> None:
        intent = _load(DUCT_PATH)
        intent["schema_version"] = "contrainte.physics-intent/0.1"
        with self.assertRaisesRegex(InputError, "superseded"):
            parse_intent(intent)
        rules = _load(RULES_PATH)
        rules["schema_version"] = "contrainte.applicability-rules/0.1"
        with self.assertRaisesRegex(InputError, "superseded"):
            parse_rule_set(rules)
        report = evaluate_documents(_load(DUCT_PATH), _load(RULES_PATH))
        report["schema_version"] = "contrainte.physics-applicability-report/0.1"
        with self.assertRaisesRegex(IntegrityError, "superseded"):
            verify_report(report, _load(DUCT_PATH), _load(RULES_PATH))
        legacy_rules = _load(RULES_PATH)
        legacy_rules["group_registry"] = legacy_rules.pop("registry")
        with self.assertRaisesRegex(InputError, "group_registry"):
            parse_rule_set(legacy_rules)


class CliRobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phys-robust-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(
                list(argv)
            )  # Any escaping exception fails the test: no traceback path.
        return code, out.getvalue(), err.getvalue()

    def _evaluate_bytes(self, name: str, content: bytes) -> tuple[int, str, Path]:
        path = self.root / name
        path.write_bytes(content)
        output = self.root / f"{name}.out"
        code, _, err = self._run(
            "evaluate", str(path), str(RULES_PATH), "-o", str(output)
        )
        return code, err, output

    def test_malformed_input_bytes_exit_3_without_report(self) -> None:
        duct = DUCT_PATH.read_text(encoding="utf-8")
        cases = {
            "invalid-utf8": (b'{"a": "\xff"}', "not valid UTF-8"),
            "lone-surrogate-value": (
                duct.replace('"title": "', '"title": "\\ud800', 1).encode("utf-8"),
                "lone surrogate",
            ),
            "lone-surrogate-key": (b'{"\\udfff": "x"}', "lone surrogate"),
            "huge-int": (b'{"x": 1' + b"0" * 5000 + b"}", "cannot be decoded"),
            "deep-nesting": (b"[" * 100000 + b"]" * 100000, "nested too deeply"),
            "truncated": (duct[:-20].encode("utf-8"), "invalid JSON"),
            "utf16": (duct.encode("utf-16"), "not valid UTF-8"),
        }
        for name, (content, message) in cases.items():
            with self.subTest(name):
                code, err, output = self._evaluate_bytes(name, content)
                self.assertEqual(code, 3, err)
                self.assertTrue(err.startswith("input rejected"), err)
                self.assertIn(message, err)
                self.assertNotIn("Traceback", err)
                self.assertFalse(output.exists())

    def test_utf8_bom_is_ignored(self) -> None:
        content = b"\xef\xbb\xbf" + DUCT_PATH.read_bytes()
        code, err, output = self._evaluate_bytes("bom.json", content)
        self.assertEqual((code, err), (10, ""))
        self.assertTrue((output / REPORT_FILE).exists())

    def test_surrogate_in_rule_set_exits_3(self) -> None:
        rules = RULES_PATH.read_text(encoding="utf-8").replace(
            '"title": "', '"title": "\\udc80', 1
        )
        path = self.root / "rules.json"
        path.write_text(rules, encoding="utf-8")
        code, _, err = self._run(
            "evaluate", str(DUCT_PATH), str(path), "-o", str(self.root / "o")
        )
        self.assertEqual((code, "lone surrogate" in err), (3, True))
        self.assertFalse((self.root / "o").exists())
        self.assertEqual(self._run("rules-pin", str(path))[0], 3)

    def test_output_failures_exit_6(self) -> None:
        blocker = self.root / "a-file"
        blocker.write_bytes(b"x")
        code, _, err = self._run(
            "evaluate", str(DUCT_PATH), str(RULES_PATH), "-o", str(blocker)
        )
        self.assertEqual((code, err.startswith("output failure")), (6, True))
        code, _, err = self._run(
            "evaluate", str(DUCT_PATH), str(RULES_PATH), "-o", str(blocker / "child")
        )
        self.assertEqual((code, err.startswith("output failure")), (6, True))
        code, _, err = self._run("schema", "intent", "--output", str(self.root))
        self.assertEqual((code, err.startswith("output failure")), (6, True))
        self.assertEqual(blocker.read_bytes(), b"x")

    def test_corrupt_retained_bundle_exits_5(self) -> None:
        corruptions = (
            b"\xff\xfe",
            b"[" * 100000,
            b'{"x": 1' + b"0" * 5000 + b"}",
            b'{"\\ud800": 1}',
        )
        for name in (REPORT_FILE, INTENT_FILE):
            for index, content in enumerate(corruptions):
                with self.subTest(name=name, corruption=index):
                    bundle = self.root / f"bundle-{name}-{index}"
                    self._run(
                        "evaluate", str(DUCT_PATH), str(RULES_PATH), "-o", str(bundle)
                    )
                    (bundle / name).write_bytes(content)
                    code, _, err = self._run("verify", str(bundle))
                    self.assertEqual(
                        (code, err.startswith("integrity failure")), (5, True), err
                    )

    def test_retained_input_altered_to_invalid_exits_5_explicit_files_exit_3(
        self,
    ) -> None:
        bundle = self.root / "bundle"
        self._run("evaluate", str(DUCT_PATH), str(RULES_PATH), "-o", str(bundle))
        intent = loads_strict((bundle / INTENT_FILE).read_bytes())
        intent["scales"][0]["quantity"]["unit"] = "m"
        (bundle / INTENT_FILE).write_bytes(canonical_bytes(intent))
        self.assertEqual(self._run("verify", str(bundle))[0], 5)
        code = self._run(
            "verify",
            str(bundle / REPORT_FILE),
            "--intent",
            str(bundle / INTENT_FILE),
            "--rules",
            str(RULES_PATH),
        )[0]
        self.assertEqual(code, 3)

    def test_considerations_exit_status_13(self) -> None:
        intent, rules = _turbulent_case()
        paths = []
        for name, document in (("i.json", intent), ("r.json", rules)):
            path = self.root / name
            path.write_bytes(canonical_bytes(document))
            paths.append(str(path))
        code, out, _ = self._run("evaluate", *paths, "-o", str(self.root / "o"))
        self.assertEqual(code, 13)
        self.assertEqual(
            json.loads(out)["applicability_state"], "considerations_review_required"
        )
        self.assertEqual(self._run("verify", str(self.root / "o"))[0], 0)


if __name__ == "__main__":
    unittest.main()
