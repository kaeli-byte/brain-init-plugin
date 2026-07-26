import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .adapters.capture import capture_checks
from .budget import FanoutRequest
from .contracts import BudgetSpec, RunSpec, VerificationReport
from .run import (
    create_run,
    declare_artifacts,
    finish_run,
    load_manifest,
    plan_run,
    record_event,
    run_dir_for,
)
from .verify import merge_semantic_report, verify_run


def _json_file(path: str) -> Any:
    with Path(path).open(encoding="utf-8") as source_file:
        return json.load(source_file)


def _vault_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vault", type=Path, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain_runtime.cli")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    _vault_argument(start)
    start.add_argument("--operation", required=True)
    start.add_argument("--mode", choices=["shadow"], required=True)
    start.add_argument("--profile")
    start.add_argument("--input", nargs="+", default=[])
    start.add_argument("--max-workers", type=int, default=4)
    start.add_argument("--max-attempts", type=int, default=3)
    start.add_argument("--max-semantic-verifier-calls", type=int, default=1)

    plan = commands.add_parser("plan")
    _vault_argument(plan)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--request-file", required=True)

    event = commands.add_parser("event")
    _vault_argument(event)
    event.add_argument("--run-id", required=True)
    event.add_argument("--kind", required=True)
    event.add_argument("--label", required=True)
    event.add_argument("--data-json")

    declare = commands.add_parser("declare")
    _vault_argument(declare)
    declare.add_argument("--run-id", required=True)
    declare.add_argument("--paths-file", required=True)

    verify = commands.add_parser("verify")
    _vault_argument(verify)
    verify.add_argument("--run-id", required=True)

    semantic = commands.add_parser("semantic")
    _vault_argument(semantic)
    semantic.add_argument("--run-id", required=True)
    semantic.add_argument("--report-file", required=True)

    finish = commands.add_parser("finish")
    _vault_argument(finish)
    finish.add_argument("--run-id", required=True)
    return parser


def _start(args: argparse.Namespace) -> None:
    budget = BudgetSpec(
        max_workers=args.max_workers,
        max_attempts=args.max_attempts,
        max_semantic_verifier_calls=args.max_semantic_verifier_calls,
    )
    run_id = create_run(
        args.vault,
        RunSpec(
            operation=args.operation,
            mode=args.mode,
            input_refs=args.input,
            profile=args.profile,
            budget=budget,
        ),
    )
    print(run_id)


def _plan(args: argparse.Namespace) -> None:
    payload = _json_file(args.request_file)
    if not isinstance(payload, dict):
        raise ValueError("request file must contain a JSON object")
    request = FanoutRequest(**payload)
    plan_run(args.vault, args.run_id, request)


def _event(args: argparse.Namespace) -> None:
    data = json.loads(args.data_json) if args.data_json is not None else {}
    if not isinstance(data, dict):
        raise ValueError("--data-json must contain a JSON object")
    record_event(args.vault, args.run_id, args.kind, args.label, data)


def _declare(args: argparse.Namespace) -> None:
    paths = _json_file(args.paths_file)
    if not isinstance(paths, list) or not all(
        isinstance(path, str) for path in paths
    ):
        raise ValueError("paths file must contain an array of strings")
    declare_artifacts(args.vault, args.run_id, paths)


def _summary(run_id: str, report: VerificationReport) -> str:
    verdict = "ACCEPT" if report.accepted else "REJECT"
    critical_count = len(report.failures)
    warning_count = len(report.warnings)
    warning_label = "warning" if warning_count == 1 else "warnings"
    return (
        f"Runtime shadow: {verdict} "
        f"({critical_count} critical, {warning_count} {warning_label}) "
        f"— .brain/runs/{run_id}/verification.json"
    )


def _verify(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.vault, args.run_id)
    if manifest["operation"] != "capture":
        raise ValueError(
            f"unsupported verification operation: {manifest['operation']}"
        )
    report = verify_run(args.vault, args.run_id, capture_checks)
    print(_summary(args.run_id, report))


def _semantic(args: argparse.Namespace) -> None:
    report = merge_semantic_report(
        args.vault,
        args.run_id,
        _json_file(args.report_file),
    )
    if report is None:
        print("Runtime shadow: semantic verification skipped (budget exhausted)")
        return
    print(_summary(args.run_id, report))


def _finish(args: argparse.Namespace) -> None:
    verification_path = (
        run_dir_for(args.vault.resolve(), args.run_id) / "verification.json"
    )
    shadow_verdict = None
    if verification_path.is_file():
        payload = _json_file(str(verification_path))
        shadow_verdict = payload["accepted"]
    finish_run(args.vault, args.run_id, shadow_verdict)


_COMMANDS = {
    "start": _start,
    "plan": _plan,
    "event": _event,
    "declare": _declare,
    "verify": _verify,
    "semantic": _semantic,
    "finish": _finish,
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _COMMANDS[args.command](args)
    except Exception as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
