from __future__ import annotations

import itertools
import unittest
from dataclasses import FrozenInstanceError
from fractions import Fraction

import contrainte
from contrainte.errors import InputError
from contrainte.exact_transform import (
    EXACT_TRANSFORM_SCHEMA,
    ExactRigidTransform,
    ExactRotation3,
    ExactVector3,
)


def vector(x: int | Fraction, y: int | Fraction, z: int | Fraction) -> ExactVector3:
    return ExactVector3(Fraction(x), Fraction(y), Fraction(z))


def rotation_z_90() -> ExactRotation3:
    return ExactRotation3(vector(0, 1, 0), vector(-1, 0, 0), vector(0, 0, 1))


def rational_rotation_z() -> ExactRotation3:
    return ExactRotation3(
        vector(Fraction(3, 5), Fraction(4, 5), 0),
        vector(Fraction(-4, 5), Fraction(3, 5), 0),
        vector(0, 0, 1),
    )


def determinant(entries: tuple[tuple[int, int, int], ...]) -> int:
    return (
        entries[0][0] * (entries[1][1] * entries[2][2] - entries[1][2] * entries[2][1])
        - entries[0][1]
        * (entries[1][0] * entries[2][2] - entries[1][2] * entries[2][0])
        + entries[0][2]
        * (entries[1][0] * entries[2][1] - entries[1][1] * entries[2][0])
    )


def proper_signed_permutations() -> tuple[ExactRotation3, ...]:
    rotations: list[ExactRotation3] = []
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            rows = tuple(
                tuple(
                    signs[column] if permutation[column] == row else 0
                    for column in range(3)
                )
                for row in range(3)
            )
            if determinant(rows) != 1:
                continue
            columns = tuple(
                vector(*(rows[row][column] for row in range(3))) for column in range(3)
            )
            rotations.append(ExactRotation3(*columns))
    return tuple(rotations)


class ExactRigidTransformTests(unittest.TestCase):
    def test_exact_transform_types_are_public(self) -> None:
        self.assertIs(contrainte.ExactVector3, ExactVector3)
        self.assertIs(contrainte.ExactRotation3, ExactRotation3)
        self.assertIs(contrainte.ExactRigidTransform, ExactRigidTransform)

    def test_hand_calculated_point_application(self) -> None:
        transform = ExactRigidTransform(vector(10, 20, 30), rotation_z_90())

        self.assertEqual(transform.apply_point(vector(2, 3, 4)), vector(7, 22, 34))

    def test_composition_applies_right_operand_first(self) -> None:
        first = ExactRigidTransform(vector(10, 0, 0), rotation_z_90())
        second = ExactRigidTransform(vector(1, 2, 3), rational_rotation_z())
        point = vector(Fraction(7, 3), Fraction(-2, 5), Fraction(11, 7))

        composed = first.compose(second)

        self.assertEqual(
            composed.apply_point(point), first.apply_point(second.apply_point(point))
        )

    def test_inverse_and_relative_transform_are_exact(self) -> None:
        parent = ExactRigidTransform(vector(10, -3, 2), rational_rotation_z())
        child_in_parent = ExactRigidTransform(vector(4, 5, 6), rotation_z_90())
        child_in_world = parent.compose(child_in_parent)

        self.assertEqual(child_in_world.relative_to(parent), child_in_parent)
        self.assertEqual(
            child_in_world.inverse().compose(child_in_world),
            ExactRigidTransform.identity(),
        )
        self.assertEqual(
            child_in_world.compose(child_in_world.inverse()),
            ExactRigidTransform.identity(),
        )

    def test_schema_round_trip_is_canonical(self) -> None:
        document = {
            "schema_version": EXACT_TRANSFORM_SCHEMA,
            "unit": "mm",
            "translation": {"x": "-7/3", "y": "0", "z": "11"},
            "basis": {
                "x_axis": {"x": "3/5", "y": "4/5", "z": "0"},
                "y_axis": {"x": "-4/5", "y": "3/5", "z": "0"},
                "z_axis": {"x": "0", "y": "0", "z": "1"},
            },
        }

        parsed = ExactRigidTransform.from_dict(document)

        self.assertEqual(parsed.as_dict(), document)
        self.assertEqual(ExactRigidTransform.from_dict(parsed.as_dict()), parsed)

    def test_schema_rejects_aliases_unknown_fields_and_wrong_units(self) -> None:
        base = ExactRigidTransform.identity().as_dict()
        mutations = (
            ("schema_version", "contrainte.exact-rigid-transform/0.2"),
            ("unit", "m"),
        )
        for key, value in mutations:
            with self.subTest(key=key):
                document = dict(base)
                document[key] = value
                with self.assertRaises(InputError):
                    ExactRigidTransform.from_dict(document)

        document = dict(base)
        document["authority"] = "claimed"
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            ExactRigidTransform.from_dict(document)

    def test_schema_rejects_non_string_keys_and_string_subclasses(self) -> None:
        document = ExactRigidTransform.identity().as_dict()
        document[1] = "hostile"  # type: ignore[index]
        with self.assertRaisesRegex(InputError, "field names must be strings"):
            ExactRigidTransform.from_dict(document)

        class SpoofString(str):
            def __eq__(self, other: object) -> bool:
                return True

        for field in ("schema_version", "unit"):
            with self.subTest(field=field):
                document = ExactRigidTransform.identity().as_dict()
                document[field] = SpoofString("hostile")
                with self.assertRaises(InputError):
                    ExactRigidTransform.from_dict(document)

        with self.assertRaisesRegex(InputError, "unit must be 'mm'"):
            ExactRigidTransform(
                ExactVector3.zero(),
                ExactRotation3.identity(),
                unit=SpoofString("mm"),
            )

    def test_hostile_rational_spellings_and_lengths_are_rejected(self) -> None:
        for value in ("2/4", "0/7", "-0", "+1", "01", "1/01", "1.0", "1" * 129):
            with self.subTest(value=value):
                document = ExactRigidTransform.identity().as_dict()
                document["translation"] = dict(document["translation"])
                document["translation"]["x"] = value
                with self.assertRaisesRegex(InputError, "canonical|reduced"):
                    ExactRigidTransform.from_dict(document)

    def test_direct_construction_enforces_scalar_cap(self) -> None:
        hostile = Fraction(10**128 + 1, 10**128)

        with self.assertRaisesRegex(InputError, "scalar limit"):
            ExactVector3(hostile, Fraction(0), Fraction(0))

    def test_primitives_are_strictly_typed_and_immutable(self) -> None:
        point = vector(1, 2, 3)

        with self.assertRaisesRegex(InputError, "exact Fraction"):
            ExactVector3(1, Fraction(2), Fraction(3))  # type: ignore[arg-type]
        with self.assertRaises(FrozenInstanceError):
            point.x = Fraction(4)  # type: ignore[misc]
        self.assertFalse(hasattr(point, "__dict__"))

    def test_subclasses_cannot_spoof_exact_invariants(self) -> None:
        class SpoofFraction(Fraction):
            def __eq__(self, other: object) -> bool:
                return True

        with self.assertRaisesRegex(InputError, "exact Fraction"):
            ExactVector3(SpoofFraction(7, 3), Fraction(0), Fraction(0))

        for primitive in (ExactVector3, ExactRotation3, ExactRigidTransform):
            with (
                self.subTest(primitive=primitive.__name__),
                self.assertRaisesRegex(TypeError, "may not be subclassed"),
            ):
                type(f"Spoof{primitive.__name__}", (primitive,), {})

    def test_dot_product_enforces_output_scalar_cap(self) -> None:
        first = vector(Fraction(1, 10**120 + 7), 0, 0)
        second = vector(Fraction(1, 10**120 + 9), 0, 0)

        with self.assertRaisesRegex(InputError, "dot product result.*scalar limit"):
            first.dot(second)

    def test_operations_enforce_output_scalar_cap(self) -> None:
        first = Fraction(1, 10**120 + 7)
        second = Fraction(1, 10**120 + 9)
        left = ExactRigidTransform(vector(first, 0, 0), ExactRotation3.identity())
        right = ExactRigidTransform(vector(second, 0, 0), ExactRotation3.identity())

        with self.assertRaisesRegex(InputError, "scalar limit"):
            left.compose(right)

    def test_rotation_rejects_non_unit_nonorthogonal_and_reflected_bases(self) -> None:
        with self.assertRaisesRegex(InputError, "unit vectors"):
            ExactRotation3(vector(1, 1, 0), vector(0, 1, 0), vector(0, 0, 1))
        with self.assertRaisesRegex(InputError, "orthogonal"):
            ExactRotation3(vector(1, 0, 0), vector(1, 0, 0), vector(0, 0, 1))
        with self.assertRaisesRegex(InputError, "right-handed"):
            ExactRotation3(vector(1, 0, 0), vector(0, 1, 0), vector(0, 0, -1))

    def test_generated_rotation_matrix_preserves_exact_group_identities(self) -> None:
        signed_permutations = proper_signed_permutations()
        self.assertEqual(len(signed_permutations), 24)
        rational_bases = (
            ExactRotation3.identity(),
            rational_rotation_z(),
            ExactRotation3(
                vector(1, 0, 0),
                vector(0, Fraction(3, 5), Fraction(4, 5)),
                vector(0, Fraction(-4, 5), Fraction(3, 5)),
            ),
            ExactRotation3(
                vector(Fraction(3, 5), 0, Fraction(-4, 5)),
                vector(0, 1, 0),
                vector(Fraction(4, 5), 0, Fraction(3, 5)),
            ),
        )
        points = (
            vector(0, 0, 0),
            vector(1, -2, 3),
            vector(Fraction(7, 11), Fraction(-13, 17), Fraction(19, 23)),
        )

        for permutation, rational in itertools.product(
            signed_permutations, rational_bases
        ):
            rotation = permutation.compose(rational)
            transform = ExactRigidTransform(vector(7, -11, 13), rotation)
            with self.subTest(rotation=rotation.as_dict()):
                self.assertEqual(
                    rotation.inverse().compose(rotation), ExactRotation3.identity()
                )
                self.assertEqual(
                    transform.inverse().compose(transform),
                    ExactRigidTransform.identity(),
                )
                for point in points:
                    self.assertEqual(
                        transform.inverse().apply_point(transform.apply_point(point)),
                        point,
                    )


if __name__ == "__main__":
    unittest.main()
