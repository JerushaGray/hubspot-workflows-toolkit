import json
import os

from hsflow.analyzer import build_report

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample_flow.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def test_orphan_detected():
    # Action 11 connects forward to 9 but nothing connects into it.
    report = build_report(load_sample())
    assert report.orphans == ["11"]


def test_dangling_link_detected():
    # Action 10 points at 9999, which is not defined.
    report = build_report(load_sample())
    assert report.dangling == ["9999"]
    codes = {(f.code, f.action_id) for f in report.findings}
    assert ("DANGLING_LINK", "10") in codes


def test_branch_without_default_is_flagged():
    report = build_report(load_sample())
    flagged = {f.action_id for f in report.findings if f.code == "BRANCH_NO_DEFAULT"}
    assert "8" in flagged       # two positive conditions, no default
    assert "5" not in flagged   # branch 5 has a default


def test_goto_edge_found():
    report = build_report(load_sample())
    assert {"from": "6", "to": "8"} in report.gotos


def test_delays_humanized():
    report = build_report(load_sample())
    by_id = {d["action_id"]: d for d in report.delays}
    assert by_id["2"]["human"] == "1 day"
    assert by_id["10"]["human"] == "3 days"


def test_emails_and_lists_collected():
    report = build_report(load_sample())
    assert set(report.content_ids) >= {"100001", "100002", "100003", "100004", "100005"}
    assert set(report.list_ids) >= {"5001", "5002", "5003"}


def test_report_has_errors_and_warnings():
    report = build_report(load_sample())
    assert report.errors      # the dangling link
    assert report.warnings    # orphan + branch-without-default
    assert report.ok is False


def test_terminals_include_terminal_send():
    report = build_report(load_sample())
    # Action 9 is a real terminal; the orphan (11) is reachable-from-nowhere, not a terminal.
    assert "9" in report.terminals
    assert "11" not in report.terminals


def test_empty_flow_is_safe():
    report = build_report({"id": "1", "name": "empty", "startActionId": None, "actions": []})
    assert report.action_count == 0
    assert report.findings == []
    assert report.ok is True
