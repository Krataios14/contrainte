from __future__ import annotations

import argparse
from pathlib import Path

from contrainte.artifacts import file_digest
from contrainte.cad import compile_part, load_part
from contrainte.canonical import dumps_pretty, loads_strict
from contrainte.interface_assembly import InterfaceAssembly, solve_interface_assembly
from contrainte.reference_component import (
    DesignAroundRequest,
    ReferenceComponentManifest,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
)
from contrainte.reference_spatial_assembly import ReferenceSpatialAssembly
from contrainte.release import (
    ComponentReleaseRequest,
    derive_component_manifest,
    write_component_manifest,
)

ROOT = Path(__file__).resolve().parents[1]


def identity_transform() -> dict[str, object]:
    return {
        "schema_version": "contrainte.exact-rigid-transform/0.1",
        "unit": "mm",
        "translation": {"x": "0", "y": "0", "z": "0"},
        "basis": {
            "x_axis": {"x": "1", "y": "0", "z": "0"},
            "y_axis": {"x": "0", "y": "1", "z": "0"},
            "z_axis": {"x": "0", "y": "0", "z": "1"},
        },
    }


def write_document(path: Path, document: object) -> None:
    path.write_text(dumps_pretty(document), encoding="utf-8", newline="\n")


def build_example(output_directory: Path) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    component_directory = output_directory / "components"
    component_directory.mkdir(exist_ok=True)

    compile_part(
        load_part(ROOT / "examples" / "mounting-plate.json"), component_directory
    )
    source_bundle = component_directory / "plate.demo.cad-bundle.json"
    release_request = ComponentReleaseRequest.from_dict(
        loads_strict(
            (
                ROOT / "examples" / "reference-spatial-motor-bracket-release.json"
            ).read_bytes()
        )
    )
    bracket = derive_component_manifest(source_bundle, release_request)
    bracket_path = component_directory / "motor-bracket.component.json"
    write_component_manifest(bracket_path, bracket, bundle_path=source_bundle)

    reference_payload = loads_strict(
        (ROOT / "examples" / "reference-motor-payload.json").read_bytes()
    )
    reference_payload["reference_frames"][0]["transform"]["translation"]["x"] = "-50"
    reference_payload["envelopes"][0]["bounds"] = {
        "unit": "mm",
        "minimum": {"x": "-40", "y": "60", "z": "-20"},
        "maximum": {"x": "40", "y": "100", "z": "20"},
    }
    component = ReferenceComponentManifest.from_dict(
        seal_reference_component(reference_payload)
    )
    request_payload = loads_strict(
        (ROOT / "examples" / "reference-motor-design-around-payload.json").read_bytes()
    )
    request_payload["reference_component_digest"] = component.content_digest
    request = DesignAroundRequest.from_dict(seal_design_around_request(request_payload))
    projection = project_design_around(component, request)

    component_path = output_directory / "existing-motor.reference.json"
    request_path = output_directory / "existing-motor.request.json"
    projection_path = output_directory / "existing-motor.projection.json"
    write_document(component_path, component.as_dict())
    write_document(request_path, request.as_dict())
    write_document(projection_path, projection.as_dict())

    interface = InterfaceAssembly.from_dict(
        {
            "schema_version": "contrainte.interface-assembly/0.2",
            "occurrences": [
                {
                    "occurrence_id": "motor-bracket",
                    "participant": {
                        "kind": "released_component",
                        "component": bracket.as_dict(),
                    },
                },
                {
                    "occurrence_id": "traction-motor",
                    "participant": {
                        "kind": "protected_reference",
                        "reference_component": component.as_dict(),
                        "design_around_request": request.as_dict(),
                        "design_around_projection": projection.as_dict(),
                    },
                    "anchor_transform": identity_transform(),
                },
            ],
            "mates": [
                {
                    "mate_id": "existing-motor-mount",
                    "first": {
                        "occurrence_id": "traction-motor",
                        "interface_id": "mount",
                    },
                    "second": {
                        "occurrence_id": "motor-bracket",
                        "interface_id": "motor-mount",
                    },
                    "property_keys": ["bolt-pattern"],
                    "alternatives": [
                        {
                            "alternative_id": "declared-interface",
                            "preference_rank": 0,
                            "second_interface_in_first_interface": identity_transform(),
                        }
                    ],
                }
            ],
            "candidate_budget": 1,
        }
    )
    result = solve_interface_assembly(interface)
    interface_path = output_directory / "existing-motor.interface.json"
    result_path = output_directory / "existing-motor.interface-result.json"
    write_document(interface_path, interface.as_dict())
    write_document(result_path, result.as_dict())

    assembly = ReferenceSpatialAssembly.from_dict(
        {
            "schema_version": "contrainte.reference-spatial-assembly/0.1",
            "assembly_id": "existing-motor-bracket",
            "revision": "A",
            "title": "Released bracket around one existing protected traction motor",
            "interface_assembly": {
                "locator": interface_path.name,
                "file_digest": file_digest(interface_path),
            },
            "interface_result": {
                "locator": result_path.name,
                "file_digest": file_digest(result_path),
            },
            "protected_reference": {
                "occurrence_id": "traction-motor",
                "reference_component": {
                    "locator": component_path.name,
                    "file_digest": file_digest(component_path),
                },
                "reference_component_digest": component.content_digest,
                "design_around_request": {
                    "locator": request_path.name,
                    "file_digest": file_digest(request_path),
                },
                "design_around_request_digest": request.content_digest,
                "design_around_projection": {
                    "locator": projection_path.name,
                    "file_digest": file_digest(projection_path),
                },
                "design_around_projection_digest": projection.content_digest,
            },
            "released_components": [
                {
                    "occurrence_id": "motor-bracket",
                    "manifest_locator": "components/motor-bracket.component.json",
                    "manifest_file_digest": file_digest(bracket_path),
                    "manifest_digest": bracket.manifest_digest,
                }
            ],
            "minimum_occupied_clearance_mm": "0",
            "default_released_clearance_mm": "5",
            "released_pair_clearances": [],
        }
    )
    assembly_path = output_directory / "existing-motor-spatial-assembly.json"
    write_document(assembly_path, assembly.as_dict())
    return assembly_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the deterministic existing-motor spatial example sources."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(build_example(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
