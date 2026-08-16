from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .agents import provider_inventory
from .assembly import compile_assembly, load_assembly, verify_assembly_bundle
from .cad import compile_part, load_part, verify_cad_bundle
from .canonical import dumps_pretty, loads_strict
from .component_assembly import (
    compile_component_assembly,
    load_component_assembly,
    prepare_component_assembly,
    verify_component_assembly_bundle,
)
from .errors import ContrainteError, InputError, IntegrityError
from .interface_assembly import (
    InterfaceAssembly,
    InterfaceAssemblyResult,
    solve_interface_assembly,
    verify_interface_assembly_result,
)
from .pipeline import (
    compile_bundle,
    load_bundle,
    load_case,
    verify_bundle,
    write_bundle,
)
from .program import load_program
from .reference_component import (
    DesignAroundProjection,
    DesignAroundRequest,
    ReferenceComponentManifest,
    project_design_around,
    seal_design_around_request,
    seal_reference_component,
    verify_design_around_projection,
)
from .reference_spatial_assembly import (
    compile_reference_spatial_assembly_file,
    verify_reference_spatial_assembly_bundle,
)
from .release import (
    derive_component_manifest,
    load_release_request,
    verify_local_component_manifest,
    write_component_manifest,
)
from .sketch import (
    compile_sketch_extrusion,
    load_sketch_extrusion,
    verify_sketch_bundle,
)
from .solid import compile_solid_program, load_solid_program, verify_solid_bundle
from .workspace import DesignWorkspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contrainte",
        description="Compile and verify deterministic Contrainte evidence bundles.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    compile_parser = subcommands.add_parser(
        "compile", help="compile an axial design into an evidence bundle"
    )
    compile_parser.add_argument(
        "input", help="path to a contrainte.axial-case/0.1 JSON file"
    )
    compile_parser.add_argument("--output", "-o", help="write the bundle to this path")

    verify_parser = subcommands.add_parser(
        "verify", help="verify integrity and deterministic reproduction of a bundle"
    )
    verify_parser.add_argument("bundle", help="path to an evidence bundle")

    cad_parser = subcommands.add_parser(
        "cad", help="compile and verify constrained exact geometry"
    )
    cad_commands = cad_parser.add_subparsers(dest="cad_command", required=True)
    cad_compile = cad_commands.add_parser(
        "compile", help="compile a validated prismatic part to STEP, STL, and SVG"
    )
    cad_compile.add_argument("input", help="path to a prismatic-part JSON file")
    cad_compile.add_argument(
        "--output-dir", "-o", required=True, help="directory for generated artifacts"
    )
    cad_verify = cad_commands.add_parser(
        "verify", help="verify a CAD bundle and every referenced artifact"
    )
    cad_verify.add_argument("bundle", help="path to a CAD bundle JSON file")

    assembly_parser = subcommands.add_parser(
        "assembly", help="compile and verify exact multi-part assemblies"
    )
    assembly_commands = assembly_parser.add_subparsers(
        dest="assembly_command", required=True
    )
    assembly_compile = assembly_commands.add_parser(
        "compile", help="compile an assembly and reject interference or low clearance"
    )
    assembly_compile.add_argument("input", help="path to an assembly JSON file")
    assembly_compile.add_argument(
        "--output-dir", "-o", required=True, help="directory for generated artifacts"
    )
    assembly_verify = assembly_commands.add_parser(
        "verify", help="reproduce assembly analysis and verify exact artifacts"
    )
    assembly_verify.add_argument("bundle", help="path to an assembly bundle JSON file")

    component_assembly_parser = subcommands.add_parser(
        "component-assembly",
        help="compile exact interface solutions into verified component geometry",
    )
    component_assembly_commands = component_assembly_parser.add_subparsers(
        dest="component_assembly_command", required=True
    )
    component_assembly_prepare = component_assembly_commands.add_parser(
        "prepare",
        help="bind current local releases into canonical digest-pinned inputs",
    )
    component_assembly_prepare.add_argument(
        "interface_template",
        help="source-root-relative interface-assembly template locator",
    )
    component_assembly_prepare.add_argument(
        "assembly_template",
        help="source-root-relative component-assembly template locator",
    )
    component_assembly_prepare.add_argument(
        "--source-root",
        required=True,
        help="root containing templates and current local component releases",
    )
    component_assembly_prepare.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="directory beneath source-root for canonical prepared documents",
    )
    component_assembly_compile = component_assembly_commands.add_parser(
        "compile",
        help="replay local component releases and reject interference or low clearance",
    )
    component_assembly_compile.add_argument(
        "input", help="path to a component-assembly JSON file"
    )
    component_assembly_compile.add_argument(
        "--source-root",
        required=True,
        help="root containing every digest-bound input locator",
    )
    component_assembly_compile.add_argument(
        "--output-dir", "-o", required=True, help="directory for generated artifacts"
    )
    component_assembly_verify = component_assembly_commands.add_parser(
        "verify", help="independently replay a component-assembly bundle"
    )
    component_assembly_verify.add_argument(
        "bundle", help="path to a component-assembly bundle JSON file"
    )
    component_assembly_verify.add_argument(
        "--source-root",
        required=True,
        help="root containing every digest-bound input locator",
    )

    reference_spatial_parser = subcommands.add_parser(
        "reference-spatial-assembly",
        help="compile and replay conservative spatial evidence around a protected reference",
    )
    reference_spatial_commands = reference_spatial_parser.add_subparsers(
        dest="reference_spatial_assembly_command", required=True
    )
    reference_spatial_compile = reference_spatial_commands.add_parser(
        "compile",
        help="check released B-reps against protected conservative spatial regions",
    )
    reference_spatial_compile.add_argument(
        "input", help="path to a reference-spatial-assembly JSON file"
    )
    reference_spatial_compile.add_argument(
        "--source-root",
        required=True,
        help="root containing every digest-bound input locator",
    )
    reference_spatial_compile.add_argument(
        "--output-dir",
        "-o",
        required=True,
        help="directory for the JSON evidence bundle",
    )
    reference_spatial_verify = reference_spatial_commands.add_parser(
        "verify", help="independently replay a reference-spatial-assembly bundle"
    )
    reference_spatial_verify.add_argument(
        "bundle", help="path to a reference-spatial-assembly bundle JSON file"
    )
    reference_spatial_verify.add_argument(
        "--source-root",
        required=True,
        help="root containing every digest-bound input locator",
    )

    solid_parser = subcommands.add_parser(
        "solid", help="compile and verify general exact-solid feature programs"
    )
    solid_commands = solid_parser.add_subparsers(dest="solid_command", required=True)
    solid_compile = solid_commands.add_parser(
        "compile", help="compile a constrained boolean feature DAG to STEP and STL"
    )
    solid_compile.add_argument("input", help="path to a solid-program JSON file")
    solid_compile.add_argument(
        "--output-dir", "-o", required=True, help="directory for generated artifacts"
    )
    solid_verify = solid_commands.add_parser(
        "verify", help="rebuild solid analysis and verify every exact artifact"
    )
    solid_verify.add_argument("bundle", help="path to a solid bundle JSON file")

    sketch_parser = subcommands.add_parser(
        "sketch", help="compile and verify constrained sketch extrusions"
    )
    sketch_commands = sketch_parser.add_subparsers(dest="sketch_command", required=True)
    sketch_compile = sketch_commands.add_parser(
        "compile", help="solve a constrained polygon profile and extrude it"
    )
    sketch_compile.add_argument("input", help="path to a sketch-extrusion JSON file")
    sketch_compile.add_argument(
        "--output-dir", "-o", required=True, help="directory for generated artifacts"
    )
    sketch_verify = sketch_commands.add_parser(
        "verify", help="reproduce sketch analysis and verify every artifact"
    )
    sketch_verify.add_argument("bundle", help="path to a sketch bundle JSON file")

    component_parser = subcommands.add_parser(
        "component", help="derive and verify local component releases"
    )
    component_commands = component_parser.add_subparsers(
        dest="component_command", required=True
    )
    component_derive = component_commands.add_parser(
        "derive",
        help="derive an unqualified component from verified exact-geometry evidence",
    )
    component_derive.add_argument(
        "bundle", help="verified CAD, solid, assembly, or sketch evidence bundle"
    )
    component_derive.add_argument("request", help="component release request JSON")
    component_derive.add_argument("--output", "-o", required=True)
    component_verify = component_commands.add_parser(
        "verify", help="verify local component artifacts and source CAD evidence"
    )
    component_verify.add_argument("manifest", help="component manifest JSON")

    interface_parser = subcommands.add_parser(
        "interface-assembly",
        help="solve and independently verify exact component-interface assemblies",
    )
    interface_commands = interface_parser.add_subparsers(
        dest="interface_assembly_command", required=True
    )
    interface_solve = interface_commands.add_parser(
        "solve", help="search ranked interface mates with exact rigid transforms"
    )
    interface_solve.add_argument(
        "input", help="path to an interface-assembly JSON file"
    )
    interface_solve.add_argument("--output", "-o", required=True)
    interface_verify = interface_commands.add_parser(
        "verify", help="independently replay an interface-assembly result"
    )
    interface_verify.add_argument(
        "input", help="path to the original interface-assembly JSON file"
    )
    interface_verify.add_argument("result", help="path to the result JSON file")

    reference_parser = subcommands.add_parser(
        "reference-component",
        help="seal protected components and project design-around constraints",
    )
    reference_commands = reference_parser.add_subparsers(
        dest="reference_component_command", required=True
    )
    reference_seal = reference_commands.add_parser(
        "seal", help="validate and digest-seal a reference-component payload"
    )
    reference_seal.add_argument("input", help="unsealed reference-component JSON")
    reference_seal.add_argument("--output", "-o", required=True)
    request_seal = reference_commands.add_parser(
        "seal-request", help="validate and digest-seal a design-around request"
    )
    request_seal.add_argument("input", help="unsealed design-around request JSON")
    request_seal.add_argument("--output", "-o", required=True)
    reference_project = reference_commands.add_parser(
        "project", help="project protected and flexible design constraints"
    )
    reference_project.add_argument("component", help="sealed reference component")
    reference_project.add_argument("request", help="sealed design-around request")
    reference_project.add_argument("--output", "-o", required=True)
    reference_verify = reference_commands.add_parser(
        "verify", help="independently replay a design-around projection"
    )
    reference_verify.add_argument("component", help="sealed reference component")
    reference_verify.add_argument("request", help="sealed design-around request")
    reference_verify.add_argument("projection", help="design-around projection")

    program_parser = subcommands.add_parser(
        "program", help="inspect deterministic design-program graphs"
    )
    program_commands = program_parser.add_subparsers(
        dest="program_command", required=True
    )
    program_validate = program_commands.add_parser(
        "validate", help="validate a design program and print its execution order"
    )
    program_validate.add_argument("input", help="path to a design-program JSON file")
    program_ready = program_commands.add_parser(
        "ready", help="list tasks ready after a supplied completed set"
    )
    program_ready.add_argument("input", help="path to a design-program JSON file")
    program_ready.add_argument(
        "--completed",
        action="append",
        default=[],
        help="completed task identifier; repeat for multiple tasks",
    )

    workspace_parser = subcommands.add_parser(
        "workspace", help="create and inspect durable design runs"
    )
    workspace_commands = workspace_parser.add_subparsers(
        dest="workspace_command", required=True
    )
    workspace_init = workspace_commands.add_parser(
        "init", help="pin a design program and create or resume a run"
    )
    workspace_init.add_argument("program", help="path to a design-program JSON file")
    workspace_init.add_argument(
        "--root", "-r", required=True, help="workspace directory"
    )
    workspace_init.add_argument("--run-id", help="stable run identifier")
    workspace_status = workspace_commands.add_parser(
        "status", help="show verified run state and ready tasks"
    )
    workspace_status.add_argument(
        "program", help="path to the pinned program JSON file"
    )
    workspace_status.add_argument(
        "--root", "-r", required=True, help="workspace directory"
    )
    workspace_status.add_argument("--run-id", required=True, help="run identifier")

    agents_parser = subcommands.add_parser(
        "agents", help="inspect optional subscription-CLI providers"
    )
    agents_commands = agents_parser.add_subparsers(dest="agents_command", required=True)
    agents_commands.add_parser(
        "doctor", help="report local Codex and Claude CLI availability"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            case = load_case(args.input)
            bundle = compile_bundle(case)
            if args.output:
                write_bundle(args.output, bundle)
                print(bundle["digest"])
            else:
                sys.stdout.write(dumps_pretty(bundle))
            return 0
        if args.command == "verify":
            report = verify_bundle(load_bundle(args.bundle))
            print(json.dumps(report, sort_keys=True))
            return 0
        if args.command == "cad":
            if args.cad_command == "compile":
                bundle = compile_part(load_part(args.input), args.output_dir)
                print(bundle["digest"])
                return 0
            if args.cad_command == "verify":
                print(json.dumps(verify_cad_bundle(args.bundle), sort_keys=True))
                return 0
        if args.command == "assembly":
            if args.assembly_command == "compile":
                bundle = compile_assembly(load_assembly(args.input), args.output_dir)
                print(bundle["digest"])
                return 0
            if args.assembly_command == "verify":
                print(json.dumps(verify_assembly_bundle(args.bundle), sort_keys=True))
                return 0
        if args.command == "component-assembly":
            if args.component_assembly_command == "prepare":
                print(
                    json.dumps(
                        prepare_component_assembly(
                            args.interface_template,
                            args.assembly_template,
                            args.source_root,
                            args.output_dir,
                        ),
                        sort_keys=True,
                    )
                )
                return 0
            if args.component_assembly_command == "compile":
                bundle = compile_component_assembly(
                    load_component_assembly(args.input),
                    args.source_root,
                    args.output_dir,
                )
                print(bundle["digest"])
                return 0
            if args.component_assembly_command == "verify":
                print(
                    json.dumps(
                        verify_component_assembly_bundle(args.bundle, args.source_root),
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "reference-spatial-assembly":
            if args.reference_spatial_assembly_command == "compile":
                bundle = compile_reference_spatial_assembly_file(
                    args.input,
                    args.source_root,
                    args.output_dir,
                )
                print(bundle["digest"])
                return 0
            if args.reference_spatial_assembly_command == "verify":
                print(
                    json.dumps(
                        verify_reference_spatial_assembly_bundle(
                            args.bundle, args.source_root
                        ),
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "solid":
            if args.solid_command == "compile":
                bundle = compile_solid_program(
                    load_solid_program(args.input), args.output_dir
                )
                print(bundle["digest"])
                return 0
            if args.solid_command == "verify":
                print(json.dumps(verify_solid_bundle(args.bundle), sort_keys=True))
                return 0
        if args.command == "sketch":
            if args.sketch_command == "compile":
                bundle = compile_sketch_extrusion(
                    load_sketch_extrusion(args.input), args.output_dir
                )
                print(bundle["digest"])
                return 0
            if args.sketch_command == "verify":
                print(json.dumps(verify_sketch_bundle(args.bundle), sort_keys=True))
                return 0
        if args.command == "component":
            if args.component_command == "derive":
                manifest = derive_component_manifest(
                    args.bundle, load_release_request(args.request)
                )
                write_component_manifest(args.output, manifest, bundle_path=args.bundle)
                print(manifest.manifest_digest)
                return 0
            if args.component_command == "verify":
                print(
                    json.dumps(
                        verify_local_component_manifest(args.manifest), sort_keys=True
                    )
                )
                return 0
        if args.command == "interface-assembly":
            assembly = InterfaceAssembly.from_dict(
                _read_json(args.input, label="interface assembly")
            )
            if args.interface_assembly_command == "solve":
                result = solve_interface_assembly(assembly)
                output = Path(args.output)
                try:
                    output.write_text(
                        dumps_pretty(result.as_dict()), encoding="utf-8", newline="\n"
                    )
                except OSError as exc:
                    raise InputError(
                        f"cannot write interface assembly result {output}: {exc}"
                    ) from exc
                print(
                    json.dumps(
                        {
                            "status": result.status.value,
                            "examined_candidates": result.examined_candidates,
                            **(
                                {
                                    "assembly_digest": result.assembly_digest,
                                    "participant_evidence": [
                                        item.as_dict()
                                        for item in result.participant_evidence
                                    ],
                                    "release_eligible": result.release_eligible,
                                }
                                if result.release_eligible is not None
                                else {}
                            ),
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if args.interface_assembly_command == "verify":
                result = InterfaceAssemblyResult.from_dict(
                    _read_json(args.result, label="interface assembly result")
                )
                if not verify_interface_assembly_result(assembly, result):
                    raise IntegrityError(
                        "interface assembly result cannot be reproduced"
                    )
                print(
                    json.dumps(
                        {
                            "status": "verified",
                            **(
                                {
                                    "assembly_digest": result.assembly_digest,
                                    "participant_evidence": [
                                        item.as_dict()
                                        for item in result.participant_evidence
                                    ],
                                    "release_eligible": result.release_eligible,
                                }
                                if result.release_eligible is not None
                                else {}
                            ),
                        },
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "reference-component":
            if args.reference_component_command == "seal":
                document = seal_reference_component(
                    _read_json(args.input, label="reference component payload")
                )
                _write_json(args.output, document, label="reference component")
                print(document["content_digest"])
                return 0
            if args.reference_component_command == "seal-request":
                document = seal_design_around_request(
                    _read_json(args.input, label="design-around request payload")
                )
                _write_json(args.output, document, label="design-around request")
                print(document["content_digest"])
                return 0
            component = ReferenceComponentManifest.from_dict(
                _read_json(args.component, label="reference component")
            )
            request = DesignAroundRequest.from_dict(
                _read_json(args.request, label="design-around request")
            )
            if args.reference_component_command == "project":
                projection = project_design_around(component, request)
                _write_json(
                    args.output,
                    projection.as_dict(),
                    label="design-around projection",
                )
                print(
                    json.dumps(
                        {
                            "content_digest": projection.content_digest,
                            "evidence_blockers": len(projection.evidence_blockers),
                            "status": "projected",
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if args.reference_component_command == "verify":
                projection = DesignAroundProjection.from_dict(
                    _read_json(args.projection, label="design-around projection")
                )
                if not verify_design_around_projection(component, request, projection):
                    raise IntegrityError(
                        "design-around projection cannot be reproduced"
                    )
                print(
                    json.dumps(
                        {
                            "evidence_blockers": len(projection.evidence_blockers),
                            "status": "verified",
                        },
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "program":
            program = load_program(args.input)
            if args.program_command == "validate":
                print(
                    json.dumps(
                        {
                            "status": "valid",
                            "program_digest": program.program_digest,
                            "order": list(program.topological_order()),
                        },
                        sort_keys=True,
                    )
                )
                return 0
            if args.program_command == "ready":
                print(
                    json.dumps(
                        {
                            "program_digest": program.program_digest,
                            "ready": [
                                task.task_id
                                for task in program.ready_tasks(args.completed)
                            ],
                        },
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "workspace":
            program = load_program(args.program)
            workspace = DesignWorkspace(args.root)
            if args.workspace_command == "init":
                state = workspace.create_run(program, args.run_id)
                print(json.dumps(state, sort_keys=True))
                return 0
            if args.workspace_command == "status":
                state = workspace.load_state(args.run_id)
                print(
                    json.dumps(
                        {
                            "state": state,
                            "ready": list(workspace.ready_tasks(program, args.run_id)),
                        },
                        sort_keys=True,
                    )
                )
                return 0
        if args.command == "agents" and args.agents_command == "doctor":
            print(json.dumps(provider_inventory(), sort_keys=True))
            return 0
    except ContrainteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unsupported command: {args.command}")
    return 2


def _read_json(path: str, *, label: str) -> object:
    source = Path(path)
    try:
        return loads_strict(source.read_bytes())
    except OSError as exc:
        raise InputError(f"cannot read {label} {source}: {exc}") from exc


def _write_json(path: str, document: object, *, label: str) -> None:
    destination = Path(path)
    try:
        destination.write_text(dumps_pretty(document), encoding="utf-8", newline="\n")
    except OSError as exc:
        raise InputError(f"cannot write {label} {destination}: {exc}") from exc
