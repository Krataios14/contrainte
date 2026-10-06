"""Command line: ``python -m contrainte.physics``.

Exit statuses: 0 success (evaluate: rules_satisfied), 2 usage, 3 input rejected,
4 stale pin, 5 verification/integrity failure, 6 output could not be written,
10 marginal_review_required, 11 indeterminate, 12 rules_violated,
13 considerations_review_required. Exit 10-13 still write and verify the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ..canonical import dumps_pretty
from ..errors import ContrainteError, IntegrityError
from ._parse import StalePinError
from .evaluate import (
    EXIT_BY_STATE,
    OutputError,
    evaluate_documents,
    load_json,
    verify_bundle,
    verify_report,
    write_bundle,
)
from .intent import INTENT_SCHEMA
from .registry import registry_description
from .rules import RULES_SCHEMA, parse_rule_set
from .schema import SCHEMAS, schema_text

EXIT_INPUT = 3
EXIT_STALE_PIN = 4
EXIT_INTEGRITY = 5
EXIT_OUTPUT = 6


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m contrainte.physics",
        description="Evaluate physics intent against pinned applicability rules (applicability only; no solver).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    evaluate = commands.add_parser(
        "evaluate", help="evaluate an intent and write a verified report bundle"
    )
    evaluate.add_argument("intent", help=f"{INTENT_SCHEMA} JSON file")
    evaluate.add_argument("rules", help=f"{RULES_SCHEMA} JSON file")
    evaluate.add_argument(
        "--output-dir", "-o", required=True, help="directory for the retained bundle"
    )

    verify = commands.add_parser(
        "verify", help="verify a report bundle directory or an explicit report"
    )
    verify.add_argument(
        "target", help="bundle directory, or report JSON file with --intent and --rules"
    )
    verify.add_argument(
        "--intent", help="intent JSON file when TARGET is a report file"
    )
    verify.add_argument(
        "--rules", help="rule-set JSON file when TARGET is a report file"
    )

    pin = commands.add_parser("rules-pin", help="print the pin object for a rule set")
    pin.add_argument("rules", help=f"{RULES_SCHEMA} JSON file")

    commands.add_parser(
        "groups",
        help="print the applicability registry (units, group forms, model-form table)",
    )

    schema = commands.add_parser("schema", help="print or write a JSON Schema")
    schema.add_argument("name", choices=sorted(SCHEMAS))
    schema.add_argument("--output", help="write the schema to this path")
    return parser


def _summary(report: dict) -> dict:
    return {
        "applicability_state": report["applicability_state"],
        "requested_mode": report["requested_mode"],
        "output_label": report["output_label"],
        "review_tasks": [item["task_id"] for item in report["review_tasks"]],
        "qualified_execution_permitted": report["qualified_execution"]["permitted"],
        "controlled_review_readiness": report["controlled_review_readiness"]["state"],
        "report_digest": report["report_digest"],
    }


def _write_text(path: str, text: str) -> None:
    try:
        Path(path).write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise OutputError(f"cannot write {path}: {exc.strerror or exc}") from exc


def _run(args: argparse.Namespace) -> int:
    if args.command == "evaluate":
        intent_raw, rules_raw = load_json(args.intent), load_json(args.rules)
        report = evaluate_documents(intent_raw, rules_raw)
        path = write_bundle(args.output_dir, intent_raw, rules_raw, report)
        verify_bundle(args.output_dir)
        print(
            json.dumps(
                _summary(report) | {"report": str(path), "verified": True}, indent=2
            )
        )
        return EXIT_BY_STATE[report["applicability_state"]]
    if args.command == "verify":
        target = Path(args.target)
        if args.intent is None and args.rules is None:
            report = verify_bundle(target)
        elif args.intent is not None and args.rules is not None:
            report = verify_report(
                load_json(target), load_json(args.intent), load_json(args.rules)
            )
        else:
            print("error: --intent and --rules must be given together", file=sys.stderr)
            return 2
        print(json.dumps(_summary(report) | {"verified": True}, indent=2))
        return 0
    if args.command == "rules-pin":
        print(json.dumps(parse_rule_set(load_json(args.rules)).pin(), indent=2))
        return 0
    if args.command == "groups":
        sys.stdout.write(dumps_pretty(registry_description()))
        return 0
    if args.command == "schema":
        text = schema_text(args.name)
        if args.output:
            _write_text(args.output, text)
        else:
            sys.stdout.write(text)
        return 0
    raise AssertionError(args.command)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run(args)
    except StalePinError as exc:
        print(f"stale pin: {exc}", file=sys.stderr)
        return EXIT_STALE_PIN
    except IntegrityError as exc:
        print(f"integrity failure: {exc}", file=sys.stderr)
        return EXIT_INTEGRITY
    except OutputError as exc:
        print(f"output failure: {exc}", file=sys.stderr)
        return EXIT_OUTPUT
    except ContrainteError as exc:
        print(f"input rejected: {exc}", file=sys.stderr)
        return EXIT_INPUT
    except (RecursionError, UnicodeError) as exc:
        # Defence in depth: decoding paths already map these; never surface a traceback.
        print(f"input rejected: {type(exc).__name__}", file=sys.stderr)
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
