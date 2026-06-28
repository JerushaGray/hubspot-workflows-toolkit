"""Command-line interface: ``hsflow <command>``.

    hsflow analyze <flow.json> [--json]   analyze a saved flow definition
    hsflow decode <actionTypeId>          explain an action type id
    hsflow pull-flow <id> [--out F]       GET the flow and save it  (needs token)
    hsflow pull-list <id> [--out F]       GET a list and save it    (needs token)

``analyze`` and ``decode`` need no credentials. ``pull-*`` read a token from
--token, HUBSPOT_TOKEN, or --token-file.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from typing import Optional

from . import __version__
from .analyzer import build_report, format_report
from .models import action_type_description, action_type_label


def _load_json(path: str) -> dict:
    # utf-8-sig tolerates the BOM that PowerShell's ConvertTo-Json writes.
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _save_json(data: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    print(f"Saved -> {path}")


def _cmd_analyze(args) -> int:
    report = build_report(_load_json(args.path))
    if args.json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
    else:
        print(format_report(report))
    return 1 if report.errors else 0  # non-zero on errors, handy in CI


def _cmd_decode(args) -> int:
    tid = args.action_type_id
    print(f"{tid}: {action_type_label(tid)} - {action_type_description(tid)}")
    return 0


def _make_client(args):
    from .client import WorkflowsClient

    return WorkflowsClient(token=args.token, token_file=args.token_file)


def _cmd_pull_flow(args) -> int:
    flow = _make_client(args).get_flow(args.flow_id)
    _save_json(flow, args.out or f"flow_{args.flow_id}.json")
    return 0


def _cmd_pull_list(args) -> int:
    data = _make_client(args).get_list(args.list_id)
    _save_json(data, args.out or f"list_{args.list_id}.json")
    return 0


def _add_token_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="HubSpot private-app token (overrides env/file)")
    parser.add_argument("--token-file", dest="token_file", help="path to a file holding the token")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hsflow",
        description="Client and static analyzer for the HubSpot Workflows v4 API.",
    )
    parser.add_argument("--version", action="version", version=f"hsflow {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="analyze a saved flow JSON for structural defects")
    p_analyze.add_argument("path", help="path to a flow definition JSON")
    p_analyze.add_argument("--json", action="store_true", help="emit the report as JSON")
    p_analyze.set_defaults(func=_cmd_analyze)

    p_decode = sub.add_parser("decode", help="explain an action type id (e.g. 0-4)")
    p_decode.add_argument("action_type_id")
    p_decode.set_defaults(func=_cmd_decode)

    p_flow = sub.add_parser("pull-flow", help="GET /automation/v4/flows/{id} and save it")
    p_flow.add_argument("flow_id")
    p_flow.add_argument("--out", help="output path (default flow_<id>.json)")
    _add_token_args(p_flow)
    p_flow.set_defaults(func=_cmd_pull_flow)

    p_list = sub.add_parser("pull-list", help="GET a list definition (v3, legacy fallback) and save it")
    p_list.add_argument("list_id")
    p_list.add_argument("--out", help="output path (default list_<id>.json)")
    _add_token_args(p_list)
    p_list.set_defaults(func=_cmd_pull_list)

    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
