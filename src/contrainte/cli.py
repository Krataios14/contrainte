from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from .agents import provider_inventory
from .cad import compile_part, load_part, verify_cad_bundle
from .canonical import dumps_pretty
from .errors import ContrainteError
from .pipeline import (
    compile_bundle,
    load_bundle,
    load_case,
    verify_bundle,
    write_bundle,
)
from .program import load_program
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
    workspace_init.add_argument("--root", "-r", required=True, help="workspace directory")
    workspace_init.add_argument("--run-id", help="stable run identifier")
    workspace_status = workspace_commands.add_parser(
        "status", help="show verified run state and ready tasks"
    )
    workspace_status.add_argument("program", help="path to the pinned program JSON file")
    workspace_status.add_argument("--root", "-r", required=True, help="workspace directory")
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
