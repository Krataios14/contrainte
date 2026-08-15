from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from fractions import Fraction
from unittest.mock import patch

from contrainte.canonical import digest
from contrainte.component import InterfaceDirection, InterfaceKind
from contrainte.errors import InputError, IntegrityError
from contrainte.exact_transform import ExactRigidTransform, ExactVector3
from contrainte.reference_component import (
    DESIGN_AROUND_PROJECTION_SCHEMA,
    DESIGN_AROUND_REQUEST_SCHEMA,
    LEGAL_GATE_DISCLAIMER,
    MAX_EVIDENCE_RECORDS,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    REFERENCE_COMPONENT_SCHEMA,
    AllowedOperation,
    ClearanceRequirement,
    DesignAroundProjection,
    DesignAroundRequest,
    DesignDomain,
    EnvelopePurpose,
    EvidenceAuthority,
    EvidenceGate,
    EvidenceKind,
    EvidenceRecord,
    ExactBox,
    FrameRole,
    GateDisposition,
    GateName,
    KnownField,
    MassProperties,
    ReferenceComponentManifest,
    ReferenceFrame,
    SpatialEnvelope,
    UnknownField,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
    verify_design_around_projection,
)


def sha(character: str) -> str:
    return f"sha256:{character * 64}"


def vector(x: str, y: str, z: str) -> dict[str, str]:
    return {"x": x, "y": y, "z": z}


def identity_transform(x: str = "0", y: str = "0", z: str = "0") -> dict:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": vector(x, y, z),
        "basis": {
            "x_axis": vector("1", "0", "0"),
            "y_axis": vector("0", "1", "0"),
            "z_axis": vector("0", "0", "1"),
        },
    }


def base_payload() -> dict:
    return {
        "schema_version": REFERENCE_COMPONENT_SCHEMA,
        "component_id": "motor-001",
        "manufacturer": "Example Motors",
        "part_number": "EM-42",
        "revision": "C",
        "title": "Fixed traction motor",
        "source_model_digest": sha("a"),
        "unit": "mm",
        "evidence": [
            {
                "evidence_id": "drawing",
                "kind": "manufacturer_drawing",
                "artifact_digest": sha("a"),
                "authority": "documented_source",
                "locator": "vendor://EM-42/rev-C/drawing",
                "supports": [
                    "/envelopes/service-zone",
                    "/identity",
                    "/occupied_bounds",
                    "/reference_frames/mount",
                    "/revision",
                ],
            },
            {
                "evidence_id": "legal-review",
                "kind": "declaration",
                "artifact_digest": sha("b"),
                "authority": "informative",
                "locator": "project://review/2026-08-15",
                "supports": ["/evidence_gates"],
            },
            {
                "evidence_id": "mass-test",
                "kind": "test_report",
                "artifact_digest": sha("c"),
                "authority": "informative",
                "locator": "lab://mass/EM-42-C",
                "supports": ["/mass_properties"],
            },
        ],
        "reference_frames": [
            {
                "frame_id": "mount",
                "role": "interface",
                "transform": identity_transform("0", "0", "0"),
                "evidence_id": "drawing",
                "interface": {
                    "kind": "mechanical",
                    "direction": "bidirectional",
                    "medium": "bolted-flange",
                    "properties": {"bolt-pattern": "4xM8-PCD100"},
                },
            }
        ],
        "occupied_bounds": {
            "unit": "mm",
            "minimum": vector("-50", "-50", "-100"),
            "maximum": vector("50", "50", "100"),
        },
        "occupied_bounds_evidence_id": "drawing",
        "envelopes": [
            {
                "envelope_id": "service-zone",
                "purpose": "service",
                "bounds": {
                    "unit": "mm",
                    "minimum": vector("-75", "-75", "-125"),
                    "maximum": vector("75", "75", "150"),
                },
                "evidence_id": "drawing",
            }
        ],
        "mass_properties": {
            "mass_kg": "18",
            "center_of_mass": vector("0", "0", "5"),
            "inertia_kg_mm2": {
                "ixx": "1000",
                "iyy": "1000",
                "izz": "500",
                "ixy": "0",
                "ixz": "0",
                "iyz": "0",
            },
            "inertia_reference": "center_of_mass",
            "evidence_id": "mass-test",
        },
        "allowed_operations": [
            "attach_at_declared_interface",
            "rigid_placement",
        ],
        "known_fields": [{"field_path": "/revision", "evidence_id": "drawing"}],
        "unknown_fields": [
            {
                "field_path": "/performance/torque_curve",
                "consequence": "Do not release transmission or inverter sizing.",
                "required_evidence": "Authenticated torque-speed and derating map.",
            }
        ],
        "evidence_gates": [
            {
                "name": name,
                "disposition": "accepted_for_project",
                "evidence_ids": ["legal-review"],
                "rationale": "Recorded project review; not a legal conclusion.",
            }
            for name in (
                "authenticity",
                "rights_to_use",
                "rights_to_modify",
                "freedom_to_operate",
                "export_control",
            )
        ],
        "legal_gate_disclaimer": LEGAL_GATE_DISCLAIMER,
    }


def parsed_manifest(payload: dict | None = None) -> ReferenceComponentManifest:
    return ReferenceComponentManifest.from_dict(
        seal_reference_component(base_payload() if payload is None else payload)
    )


def request_payload(component_digest: str) -> dict:
    return {
        "schema_version": DESIGN_AROUND_REQUEST_SCHEMA,
        "request_id": "motor-installation",
        "reference_component_digest": component_digest,
        "occurrence_id": "traction-motor",
        "flexible_domains": ["cooling", "mounting", "transmission"],
        "required_interface_ids": ["mount"],
        "clearances": [{"envelope_id": "service-zone", "clearance_mm": "5"}],
    }


def parsed_request(manifest: ReferenceComponentManifest) -> DesignAroundRequest:
    return DesignAroundRequest.from_dict(
        seal_design_around_request(request_payload(manifest.content_digest))
    )


class ReferenceComponentTests(unittest.TestCase):
    def test_manifest_round_trip_and_digest(self) -> None:
        document = seal_reference_component(base_payload())
        manifest = ReferenceComponentManifest.from_dict(document)

        self.assertEqual(manifest.as_dict(), document)
        self.assertEqual(manifest.content_digest, digest(manifest.payload_dict()))
        self.assertEqual(manifest.unit, "mm")
        self.assertIs(type(manifest.occupied_bounds.minimum), ExactVector3)
        self.assertIs(type(manifest.reference_frames[0].transform), ExactRigidTransform)

    def test_projection_binds_fixed_component_and_flexible_domains(self) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)

        projection = project_design_around(manifest, request)

        self.assertEqual(projection.schema_version, DESIGN_AROUND_PROJECTION_SCHEMA)
        self.assertEqual(projection.reference_component_digest, manifest.content_digest)
        self.assertEqual(projection.request_digest, request.content_digest)
        self.assertEqual(
            tuple(item.domain.value for item in projection.flexible_bindings),
            ("cooling", "mounting", "transmission"),
        )
        identifiers = {item.constraint_id for item in projection.protected_constraints}
        self.assertTrue(
            {
                "identity",
                "source-model",
                "occupied-bounds",
                "frame:mount",
                "envelope:service-zone",
                "mass-properties",
                "allowed-operations",
                "clearance:service-zone",
                "gate:freedom_to_operate",
            }
            <= identifiers
        )
        self.assertIn("unknown:/performance/torque_curve", projection.evidence_blockers)
        self.assertTrue(verify_design_around_projection(manifest, request, projection))

    def test_projection_serialized_round_trip_and_tamper_rejection(self) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)
        projection = project_design_around(manifest, request)
        document = projection.as_dict()

        self.assertEqual(DesignAroundProjection.from_dict(document), projection)
        document["occurrence_id"] = "attacker-selected"
        with self.assertRaisesRegex(IntegrityError, "digest mismatch"):
            DesignAroundProjection.from_dict(document)

        corrupted = copy.deepcopy(projection)
        object.__setattr__(corrupted, "occurrence_id", "attacker-selected")
        self.assertFalse(verify_design_around_projection(manifest, request, corrupted))

    def test_projector_reparses_stale_digest_objects_at_every_boundary(self) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)
        projection = project_design_around(manifest, request)

        changed_manifest = copy.deepcopy(manifest)
        object.__setattr__(changed_manifest, "revision", "attacker-revision")
        with self.assertRaisesRegex(IntegrityError, "content digest mismatch"):
            project_design_around(changed_manifest, request)
        self.assertFalse(
            verify_design_around_projection(changed_manifest, request, projection)
        )

        changed_request = copy.deepcopy(request)
        object.__setattr__(changed_request, "occurrence_id", "attacker-occurrence")
        with self.assertRaisesRegex(IntegrityError, "content digest mismatch"):
            project_design_around(manifest, changed_request)
        self.assertFalse(
            verify_design_around_projection(manifest, changed_request, projection)
        )

        nested_request = copy.deepcopy(request)
        object.__setattr__(nested_request.clearances[0], "clearance_mm", Fraction(99))
        with self.assertRaisesRegex(IntegrityError, "content digest mismatch"):
            project_design_around(manifest, nested_request)
        self.assertFalse(
            verify_design_around_projection(manifest, nested_request, projection)
        )

    def test_verifier_rejects_malformed_nested_projection_and_is_independent(
        self,
    ) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)
        projection = project_design_around(manifest, request)

        with patch(
            "contrainte.reference_component.project_design_around",
            side_effect=AssertionError("common-mode replay used"),
        ):
            self.assertTrue(
                verify_design_around_projection(manifest, request, projection)
            )

        malformed = copy.deepcopy(projection)
        object.__setattr__(
            malformed.protected_constraints[0], "evidence_ids", ["drawing"]
        )
        self.assertFalse(verify_design_around_projection(manifest, request, malformed))

        malformed_kind = copy.deepcopy(projection)
        object.__setattr__(malformed_kind.protected_constraints[0], "kind", object())
        self.assertFalse(
            verify_design_around_projection(manifest, request, malformed_kind)
        )

    def test_verifier_oracle_does_not_share_projector_semantic_helpers(self) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)

        with patch(
            "contrainte.reference_component._needs_independent_resolution",
            return_value=False,
        ):
            bad_ceiling = project_design_around(manifest, request)
        self.assertFalse(
            verify_design_around_projection(manifest, request, bad_ceiling)
        )

        with patch(
            "contrainte.reference_component._resolve_pointer",
            return_value="WRONG-VALUE",
        ):
            bad_known_value = project_design_around(manifest, request)
        self.assertFalse(
            verify_design_around_projection(manifest, request, bad_known_value)
        )

        with patch(
            "contrainte.reference_component._supports_path",
            return_value=True,
        ):
            bad_identity_evidence = project_design_around(manifest, request)
        self.assertFalse(
            verify_design_around_projection(manifest, request, bad_identity_evidence)
        )

    def test_manifest_and_request_tampering_are_rejected(self) -> None:
        document = seal_reference_component(base_payload())
        document["revision"] = "D"
        with self.assertRaisesRegex(IntegrityError, "digest mismatch"):
            ReferenceComponentManifest.from_dict(document)

        manifest = parsed_manifest()
        request_document = seal_design_around_request(
            request_payload(manifest.content_digest)
        )
        request_document["clearances"][0]["clearance_mm"] = "6"
        with self.assertRaisesRegex(IntegrityError, "digest mismatch"):
            DesignAroundRequest.from_dict(request_document)

    def test_request_rejects_wrong_component_unknown_interface_and_envelope(
        self,
    ) -> None:
        manifest = parsed_manifest()
        request = parsed_request(manifest)
        wrong = replace(
            request,
            reference_component_digest=sha("f"),
            content_digest=digest(
                {
                    **request.payload_dict(),
                    "reference_component_digest": sha("f"),
                }
            ),
        )
        with self.assertRaisesRegex(IntegrityError, "different reference"):
            project_design_around(manifest, wrong)

        for name, value, pattern in (
            ("required_interface_ids", ["missing"], "unknown interface"),
            (
                "clearances",
                [{"envelope_id": "missing", "clearance_mm": "0"}],
                "unknown envelopes",
            ),
        ):
            payload = request_payload(manifest.content_digest)
            payload[name] = value
            parsed = DesignAroundRequest.from_dict(seal_design_around_request(payload))
            with self.assertRaisesRegex(InputError, pattern):
                project_design_around(manifest, parsed)

    def test_scan_and_gaussian_splat_are_observations_not_authority(self) -> None:
        for kind in ("scan", "gaussian_splat"):
            payload = base_payload()
            payload["evidence"][0]["kind"] = kind
            payload["evidence"][0]["authority"] = "documented_source"
            with (
                self.subTest(kind=kind),
                self.assertRaisesRegex(InputError, "observational"),
            ):
                parsed_manifest(payload)

        payload = base_payload()
        payload["evidence"][0]["kind"] = "gaussian_splat"
        payload["evidence"][0]["authority"] = "observation"
        manifest = parsed_manifest(payload)
        projection = project_design_around(manifest, parsed_request(manifest))
        self.assertIn(
            "evidence-resolution:/occupied_bounds", projection.evidence_blockers
        )
        self.assertIn(
            "evidence-resolution:/reference_frames/mount",
            projection.evidence_blockers,
        )
        occupied = next(
            item
            for item in projection.protected_constraints
            if item.constraint_id == "occupied-bounds"
        )
        self.assertIs(occupied.authority, EvidenceAuthority.OBSERVATION)
        self.assertTrue(occupied.resolution_required)

    def test_known_fields_are_projected_with_values_and_evidence_ceilings(self) -> None:
        payload = base_payload()
        payload["known_fields"] = [
            {
                "field_path": "/mass_properties/mass_kg",
                "evidence_id": "mass-test",
            },
            {"field_path": "/revision", "evidence_id": "drawing"},
        ]
        manifest = parsed_manifest(payload)
        projection = project_design_around(manifest, parsed_request(manifest))
        known = {
            item.source_path: item
            for item in projection.protected_constraints
            if item.kind.value == "known_field"
        }

        self.assertEqual(known["/revision"].value_digest, digest("C"))
        self.assertIs(known["/revision"].authority, EvidenceAuthority.DOCUMENTED_SOURCE)
        self.assertFalse(known["/revision"].resolution_required)
        self.assertEqual(known["/mass_properties/mass_kg"].value_digest, digest("18"))
        self.assertTrue(known["/mass_properties/mass_kg"].resolution_required)
        self.assertIn(
            "evidence-resolution:/mass_properties/mass_kg",
            projection.evidence_blockers,
        )

    def test_clearance_cannot_outrank_its_envelope_evidence(self) -> None:
        payload = base_payload()
        payload["evidence"].append(
            {
                "evidence_id": "nominal-service",
                "kind": "supplier_model",
                "artifact_digest": sha("d"),
                "authority": "nominal_source",
                "locator": "supplier://EM-42/service-envelope",
                "supports": ["/envelopes/service-zone"],
            }
        )
        payload["evidence"].sort(key=lambda item: item["evidence_id"])
        payload["envelopes"][0]["evidence_id"] = "nominal-service"
        manifest = parsed_manifest(payload)
        projection = project_design_around(manifest, parsed_request(manifest))

        clearance = next(
            item
            for item in projection.protected_constraints
            if item.constraint_id == "clearance:service-zone"
        )
        self.assertIs(clearance.authority, EvidenceAuthority.NOMINAL_SOURCE)
        self.assertTrue(clearance.resolution_required)
        self.assertIn(
            "evidence-resolution:/request/clearances/service-zone",
            projection.evidence_blockers,
        )

    def test_supplier_models_cannot_be_promoted_to_documented_authority(self) -> None:
        payload = base_payload()
        payload["evidence"][0]["kind"] = "supplier_model"
        with self.assertRaisesRegex(InputError, "manufacturer documentation"):
            parsed_manifest(payload)

    def test_verified_measurement_requires_calibrated_metrology(self) -> None:
        payload = base_payload()
        payload["evidence"][0]["authority"] = "verified_measurement"
        with self.assertRaisesRegex(InputError, "calibrated metrology"):
            parsed_manifest(payload)

    def test_gate_dispositions_are_workflow_evidence_not_legal_claims(self) -> None:
        payload = base_payload()
        payload["evidence_gates"][3] = {
            "name": "freedom_to_operate",
            "disposition": "unreviewed",
            "evidence_ids": [],
            "rationale": "Counsel review has not been obtained.",
        }
        manifest = parsed_manifest(payload)
        projection = project_design_around(manifest, parsed_request(manifest))

        self.assertEqual(
            manifest.as_dict()["legal_gate_disclaimer"], LEGAL_GATE_DISCLAIMER
        )
        self.assertIn(
            "gate:freedom_to_operate:unreviewed", projection.evidence_blockers
        )

        payload["evidence_gates"][3]["disposition"] = "accepted_for_project"
        with self.assertRaisesRegex(InputError, "supporting evidence"):
            parsed_manifest(payload)

    def test_all_gate_names_are_required_once_and_in_schema_order(self) -> None:
        payload = base_payload()
        payload["evidence_gates"] = payload["evidence_gates"][:-1]
        with self.assertRaisesRegex(InputError, "every gate once"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["evidence_gates"][0], payload["evidence_gates"][1] = (
            payload["evidence_gates"][1],
            payload["evidence_gates"][0],
        )
        with self.assertRaisesRegex(InputError, "schema order"):
            parsed_manifest(payload)

    def test_referenced_evidence_and_source_digest_must_exist(self) -> None:
        payload = base_payload()
        payload["occupied_bounds_evidence_id"] = "missing"
        with self.assertRaisesRegex(InputError, "unknown evidence"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["source_model_digest"] = sha("f")
        with self.assertRaisesRegex(InputError, "declared evidence artifact"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["evidence"][0]["supports"].remove("/occupied_bounds")
        with self.assertRaisesRegex(InputError, "declare support for /occupied_bounds"):
            parsed_manifest(payload)

        payload = base_payload()
        supports = payload["evidence"][0]["supports"]
        supports[supports.index("/occupied_bounds")] = "/occupied_bounds/maximum"
        supports.sort()
        with self.assertRaisesRegex(InputError, "declare support for /occupied_bounds"):
            parsed_manifest(payload)

        payload = base_payload()
        supports = payload["evidence"][0]["supports"]
        supports[supports.index("/revision")] = "/revision/character"
        supports.sort()
        with self.assertRaisesRegex(InputError, "declare support for /revision"):
            parsed_manifest(payload)

    def test_known_and_unknown_fields_are_disjoint_canonical_and_unique(self) -> None:
        payload = base_payload()
        payload["unknown_fields"][0]["field_path"] = "/revision/detail"
        with self.assertRaisesRegex(InputError, "ancestor/descendant"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["known_fields"] = [
            {"field_path": "/z", "evidence_id": "drawing"},
            {"field_path": "/a", "evidence_id": "drawing"},
        ]
        with self.assertRaisesRegex(InputError, "canonical order"):
            parsed_manifest(payload)

    def test_frames_envelopes_operations_and_evidence_are_canonical(self) -> None:
        payload = base_payload()
        payload["allowed_operations"].reverse()
        with self.assertRaisesRegex(InputError, "canonical order"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["evidence"].reverse()
        with self.assertRaisesRegex(InputError, "canonical order"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["evidence"].append(copy.deepcopy(payload["evidence"][0]))
        payload["evidence"].sort(key=lambda item: item["evidence_id"])
        with self.assertRaisesRegex(InputError, "identifiers.*unique"):
            parsed_manifest(payload)

    def test_mass_properties_require_positive_mass_psd_inertia_and_bounded_com(
        self,
    ) -> None:
        cases = (
            ("mass_kg", "0", "positive"),
            ("center_of_mass", vector("1000", "0", "0"), "within occupied"),
        )
        for field, value, pattern in cases:
            payload = base_payload()
            payload["mass_properties"][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(InputError, pattern):
                parsed_manifest(payload)

        payload = base_payload()
        payload["mass_properties"]["inertia_kg_mm2"].update(
            {"ixx": "1", "iyy": "1", "izz": "1", "ixy": "2"}
        )
        with self.assertRaisesRegex(InputError, "positive semidefinite"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["mass_properties"]["inertia_kg_mm2"].update(
            {"ixx": "10", "iyy": "1", "izz": "1"}
        )
        with self.assertRaisesRegex(InputError, "triangle inequalities"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["mass_properties"]["inertia_kg_mm2"].update(
            {
                "ixx": "2",
                "iyy": "2",
                "izz": "2",
                "ixy": "3/2",
                "ixz": "3/2",
                "iyz": "3/2",
            }
        )
        with self.assertRaisesRegex(InputError, "principal triangle inequalities"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["mass_properties"]["inertia_kg_mm2"].update(
            {"ixx": "300000", "iyy": "300000", "izz": "300000"}
        )
        with self.assertRaisesRegex(InputError, "occupied-bounds limits"):
            parsed_manifest(payload)

    def test_exact_box_and_mass_direct_constructors_reject_invalid_values(self) -> None:
        with self.assertRaisesRegex(InputError, "greater than"):
            ExactBox(
                ExactVector3(Fraction(0), Fraction(0), Fraction(0)),
                ExactVector3(Fraction(0), Fraction(1), Fraction(1)),
            )
        with self.assertRaisesRegex(InputError, "positive exact"):
            MassProperties(
                Fraction(0),
                ExactVector3.zero(),
                (
                    Fraction(1),
                    Fraction(1),
                    Fraction(1),
                    Fraction(0),
                    Fraction(0),
                    Fraction(0),
                ),
                "mass-test",
            )

    def test_direct_constructors_reject_mutable_or_spoofed_collections(self) -> None:
        manifest = parsed_manifest()
        with self.assertRaisesRegex(InputError, "bounded tuple"):
            replace(manifest, evidence=list(manifest.evidence))
        with self.assertRaisesRegex(InputError, "exact values"):
            replace(manifest, reference_frames=(object(),))

        class EqualitySpoof(str):
            def __eq__(self, other: object) -> bool:
                return True

        with self.assertRaisesRegex(InputError, "schema_version"):
            replace(manifest, schema_version=EqualitySpoof(REFERENCE_COMPONENT_SCHEMA))

        with self.assertRaisesRegex(TypeError, "may not be subclassed"):

            class ManifestSubclass(ReferenceComponentManifest):
                pass

    def test_duplicate_operations_and_flexible_domains_are_rejected(self) -> None:
        payload = base_payload()
        payload["allowed_operations"] = [
            "rigid_placement",
            "rigid_placement",
        ]
        with self.assertRaisesRegex(InputError, "allowed_operations.*unique"):
            parsed_manifest(payload)

        manifest = parsed_manifest()
        payload = request_payload(manifest.content_digest)
        payload["flexible_domains"] = ["cooling", "cooling"]
        with self.assertRaisesRegex(InputError, "flexible_domains.*unique"):
            DesignAroundRequest.from_dict(seal_design_around_request(payload))

    def test_semantic_operations_require_declared_physical_referents(self) -> None:
        payload = base_payload()
        payload["reference_frames"][0]["role"] = "datum"
        payload["reference_frames"][0]["interface"] = None
        with self.assertRaisesRegex(
            InputError, "requires at least one physical interface"
        ):
            parsed_manifest(payload)

        payload = base_payload()
        payload["allowed_operations"].append("route_within_declared_access")
        payload["allowed_operations"].sort()
        with self.assertRaisesRegex(
            InputError, "requires at least one access envelope"
        ):
            parsed_manifest(payload)

        payload = base_payload()
        payload["envelopes"][0]["purpose"] = "keepout"
        payload["allowed_operations"].append("remove_for_service")
        payload["allowed_operations"].sort()
        with self.assertRaisesRegex(
            InputError, "requires at least one service envelope"
        ):
            parsed_manifest(payload)

        manifest = parsed_manifest()
        projection = project_design_around(manifest, parsed_request(manifest))
        operation_constraint = next(
            item
            for item in projection.protected_constraints
            if item.constraint_id == "allowed-operations"
        )
        self.assertFalse(operation_constraint.resolution_required)

    def test_frame_roles_and_interface_semantics_are_strict(self) -> None:
        payload = base_payload()
        payload["reference_frames"][0]["role"] = "datum"
        with self.assertRaisesRegex(InputError, "must be null"):
            parsed_manifest(payload)

        transform = ExactRigidTransform.identity()
        with self.assertRaisesRegex(InputError, "cannot declare interface"):
            ReferenceFrame(
                "datum",
                FrameRole.DATUM,
                transform,
                "drawing",
                InterfaceKind.MECHANICAL,
                InterfaceDirection.BIDIRECTIONAL,
                "bolted",
            )

        payload = base_payload()
        payload["reference_frames"][0]["transform"] = identity_transform("1000")
        with self.assertRaisesRegex(InputError, "physical interface frame"):
            parsed_manifest(payload)

        payload["reference_frames"][0]["role"] = "datum"
        payload["reference_frames"][0]["interface"] = None
        payload["allowed_operations"] = ["rigid_placement"]
        self.assertEqual(
            parsed_manifest(payload).reference_frames[0].role, FrameRole.DATUM
        )

    def test_resource_caps_apply_before_deep_record_walk(self) -> None:
        payload = base_payload()
        payload["evidence"] = [None] * (MAX_EVIDENCE_RECORDS + 1)
        with self.assertRaisesRegex(InputError, "128-item limit"):
            parsed_manifest(payload)

        too_many_nodes = {"schema_version": REFERENCE_COMPONENT_SCHEMA}
        too_many_nodes["bomb"] = [None] * MAX_JSON_NODES
        with self.assertRaisesRegex(InputError, "node input limit"):
            ReferenceComponentManifest.from_dict(too_many_nodes)

        oversized_bad_keys = {index: None for index in range(MAX_JSON_NODES)}
        with self.assertRaisesRegex(InputError, "node input limit"):
            ReferenceComponentManifest.from_dict(oversized_bad_keys)

    def test_tree_depth_float_and_mapping_subclasses_are_rejected(self) -> None:
        nested: object = None
        for _ in range(MAX_JSON_DEPTH + 1):
            nested = [nested]
        with self.assertRaisesRegex(InputError, "depth limit"):
            ReferenceComponentManifest.from_dict(nested)

        payload = base_payload()
        payload["occupied_bounds"]["minimum"]["x"] = 0.0
        with self.assertRaisesRegex(InputError, "unsupported value type float"):
            parsed_manifest(payload)

        class DictSubclass(dict):
            pass

        with self.assertRaisesRegex(InputError, "unsupported value type DictSubclass"):
            ReferenceComponentManifest.from_dict(DictSubclass())

        payload = base_payload()
        payload["title"] = 1 << 100
        with self.assertRaisesRegex(InputError, "64-bit limit"):
            seal_reference_component(payload)

    def test_field_paths_use_canonical_segment_aware_rfc6901_rules(self) -> None:
        for invalid in (
            "/trailing/",
            "/dot/./child",
            "/dot/../child",
            "/bad/~2escape",
            "/empty//segment",
        ):
            payload = base_payload()
            payload["unknown_fields"][0]["field_path"] = invalid
            with (
                self.subTest(path=invalid),
                self.assertRaisesRegex(InputError, "path|segment|RFC 6901"),
            ):
                parsed_manifest(payload)

    def test_noncanonical_rationals_and_negative_clearance_are_rejected(self) -> None:
        payload = base_payload()
        payload["occupied_bounds"]["minimum"]["x"] = "2/4"
        with self.assertRaisesRegex(InputError, "reduced and canonical"):
            parsed_manifest(payload)

        manifest = parsed_manifest()
        payload = request_payload(manifest.content_digest)
        payload["clearances"][0]["clearance_mm"] = "-1"
        with self.assertRaisesRegex(InputError, "non-negative"):
            DesignAroundRequest.from_dict(seal_design_around_request(payload))

    def test_schema_unknown_fields_and_disclaimer_tampering_are_rejected(self) -> None:
        payload = base_payload()
        payload["surprise"] = True
        with self.assertRaisesRegex(InputError, "unsupported fields"):
            parsed_manifest(payload)

        payload = base_payload()
        payload["legal_gate_disclaimer"] = "This is legal approval."
        with self.assertRaisesRegex(InputError, "schema-defined nonclaim"):
            parsed_manifest(payload)

    def test_projection_constraint_value_digests_change_with_protected_values(
        self,
    ) -> None:
        first = parsed_manifest()
        first_projection = project_design_around(first, parsed_request(first))
        payload = base_payload()
        payload["occupied_bounds"]["maximum"]["x"] = "51"
        second = parsed_manifest(payload)
        second_projection = project_design_around(second, parsed_request(second))

        def constraint_value(
            projection: DesignAroundProjection, identifier: str
        ) -> str:
            return next(
                item.value_digest
                for item in projection.protected_constraints
                if item.constraint_id == identifier
            )

        self.assertNotEqual(first.content_digest, second.content_digest)
        self.assertNotEqual(
            constraint_value(first_projection, "occupied-bounds"),
            constraint_value(second_projection, "occupied-bounds"),
        )

    def test_nested_types_are_frozen_and_canonical(self) -> None:
        manifest = parsed_manifest()
        with self.assertRaisesRegex(Exception, "cannot assign"):
            manifest.reference_frames[0].frame_id = "changed"  # type: ignore[misc]

        record = EvidenceRecord(
            "scan",
            EvidenceKind.SCAN,
            sha("d"),
            EvidenceAuthority.OBSERVATION,
            "scan://part",
            ("/occupied_bounds",),
        )
        self.assertEqual(record.as_dict()["authority"], "observation")
        envelope = SpatialEnvelope(
            "keepout",
            EnvelopePurpose.KEEP_OUT,
            ExactBox(
                ExactVector3(Fraction(-1), Fraction(-1), Fraction(-1)),
                ExactVector3(Fraction(1), Fraction(1), Fraction(1)),
            ),
            "scan",
        )
        self.assertEqual(envelope.bounds.unit, "mm")
        self.assertIs(
            AllowedOperation.RIGID_PLACEMENT,
            AllowedOperation("rigid_placement"),
        )
        self.assertIs(DesignDomain.ELECTRONICS, DesignDomain("electronics"))
        self.assertIs(GateName.EXPORT_CONTROL, GateName("export_control"))
        self.assertIs(GateDisposition.NOT_APPLICABLE, GateDisposition("not_applicable"))
        self.assertEqual(
            ClearanceRequirement("keepout", Fraction(0)).as_dict()["clearance_mm"],
            "0",
        )
        self.assertEqual(
            KnownField("/a", "scan").as_dict(),
            {"field_path": "/a", "evidence_id": "scan"},
        )
        self.assertEqual(
            UnknownField("/b", "risk", "test").as_dict()["required_evidence"],
            "test",
        )
        gate = EvidenceGate(
            GateName.AUTHENTICITY,
            GateDisposition.UNREVIEWED,
            (),
            "Review pending.",
        )
        self.assertEqual(gate.as_dict()["disposition"], "unreviewed")


if __name__ == "__main__":
    unittest.main()
