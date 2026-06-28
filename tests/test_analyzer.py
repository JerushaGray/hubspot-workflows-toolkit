"""Tests for hsflow.analyzer, driven by the synthetic examples/sample_flow.json.

That sample is built with deliberate defects (see its "_note" field): an orphan
action (11), a dangling link (10 -> 9999), a branch with no default (8), and a
GOTO merge (6 -> 8). Each test below pins one analyzer behavior to one of those.
"""
import json
import os

from hsflow.analyzer import Codes, build_report, format_report

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample_flow.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def test_orphan_detected():
    # Action 11 connects forward to 9 but nothing connects into it, so it is
    # unreachable from the start action (1) -> orphan.
    report = build_report(load_sample())
    assert report.orphans == ["11"]


def test_dangling_link_detected():
    # Action 10's connection targets 9999, which no action defines.
    report = build_report(load_sample())
    assert report.dangling == ["9999"]
    codes = {(f.code, f.action_id) for f in report.findings}
    assert (Codes.DANGLING_LINK, "10") in codes


def test_dangling_link_reports_every_source():
    # The sample has a single source per dangling id; here two reachable actions
    # (2 and 3) both point at the same missing id (99). The analyzer should emit
    # one DANGLING_LINK finding per source, not collapse them into one. Branch 1
    # has a default and every action is reachable, so no other findings appear.
    flow = {
        "id": "x",
        "startActionId": "1",
        "actions": [
            {"actionId": "1", "type": "LIST_BRANCH",
             "listBranches": [
                 {"branchName": "A", "connection": {"edgeType": "STANDARD", "nextActionId": "2"}},
                 {"branchName": "B", "connection": {"edgeType": "STANDARD", "nextActionId": "3"}},
             ],
             "defaultBranch": {"connection": {"edgeType": "STANDARD", "nextActionId": "2"}}},
            {"actionId": "2", "actionTypeId": "0-4", "fields": {"content_id": "a"},
             "connection": {"edgeType": "STANDARD", "nextActionId": "99"}},
            {"actionId": "3", "actionTypeId": "0-4", "fields": {"content_id": "b"},
             "connection": {"edgeType": "STANDARD", "nextActionId": "99"}},
        ],
    }
    report = build_report(flow)
    assert report.dangling == ["99"]
    sources = sorted(f.action_id for f in report.findings if f.code == Codes.DANGLING_LINK)
    assert sources == ["2", "3"]


def test_branch_without_default_is_flagged():
    # Branch 8 has two positive conditions and no default (a silent-drop risk);
    # branch 5 does have a default, so it must NOT be flagged.
    report = build_report(load_sample())
    flagged = {f.action_id for f in report.findings if f.code == Codes.BRANCH_NO_DEFAULT}
    assert "8" in flagged
    assert "5" not in flagged


def test_goto_edge_found():
    # Action 6 reaches 8 via a GOTO (a merge), not a STANDARD edge.
    report = build_report(load_sample())
    assert {"from": "6", "to": "8"} in report.gotos


def test_delays_humanized():
    # delta is in minutes: 1440 -> "1 day", 4320 -> "3 days". The formatting is
    # unit-tested in test_models; here we only check the analyzer wires it up.
    report = build_report(load_sample())
    by_id = {d["action_id"]: d for d in report.delays}
    assert by_id["2"]["human"] == "1 day"
    assert by_id["10"]["human"] == "3 days"


def test_emails_and_lists_collected():
    # content_ids = every email the flow sends; list_ids = every list referenced
    # (in enrollment, branch filters, or suppression).
    report = build_report(load_sample())
    assert set(report.content_ids) >= {"100001", "100002", "100003", "100004", "100005"}
    assert set(report.list_ids) >= {"5001", "5002", "5003"}


def test_report_has_errors_and_warnings():
    # dangling link -> error; orphan + no-default branch -> warnings; so the
    # report is not "ok" (ok is True only when there are no errors or warnings).
    report = build_report(load_sample())
    assert report.errors
    assert report.warnings
    assert report.ok is False


def test_terminals_include_terminal_send():
    # A terminal has no outgoing edge. Action 9 qualifies; action 11 does not
    # (it still points at 9) even though it is an orphan -- terminal-ness is
    # about out-edges, not reachability.
    report = build_report(load_sample())
    assert "9" in report.terminals
    assert "11" not in report.terminals


def test_ids_sorted_numerically_not_lexically():
    # _int_key sorts ids as numbers; a plain string sort would put "10"/"11"
    # before "2". Defined ids are 1..11, so the expected order proves numeric
    # sorting is actually applied.
    report = build_report(load_sample())
    assert report.defined_ids == [str(i) for i in range(1, 12)]


def test_format_report_renders_summary_and_findings():
    # The populated branch of format_report: it should surface the flow name,
    # the severity tally line, and each rendered finding.
    text = format_report(build_report(load_sample()))
    assert "[SAMPLE] Welcome Nurture (synthetic)" in text
    assert "Findings: 1 error(s), 2 warning(s), 1 info" in text
    assert f"{Codes.DANGLING_LINK} [action 10]" in text


def test_broken_start_reference_is_flagged_not_an_orphan_flood():
    # startActionId names an action that does not exist. Without special
    # handling, every real action would be "unreachable" and flagged as an
    # orphan; instead the analyzer reports the broken entry point once and
    # suppresses the orphan flood.
    flow = {
        "id": "x",
        "startActionId": "999",
        "actions": [
            {"actionId": "1", "actionTypeId": "0-4", "fields": {"content_id": "a"},
             "connection": {"edgeType": "STANDARD", "nextActionId": "2"}},
            {"actionId": "2", "actionTypeId": "0-4", "fields": {"content_id": "b"}},
        ],
    }
    report = build_report(flow)
    assert any(f.code == Codes.START_NOT_FOUND for f in report.findings)
    assert report.orphans == []                                      # flood suppressed
    assert not any(f.code == Codes.ORPHAN_ACTION for f in report.findings)
    assert report.ok is False


def test_missing_start_with_actions_is_flagged():
    # No startActionId at all, but the flow has actions: still a broken entry
    # point, so START_NOT_FOUND fires and orphans stay empty.
    flow = {"id": "x", "actions": [
        {"actionId": "1", "actionTypeId": "0-4", "fields": {"content_id": "a"}},
    ]}
    report = build_report(flow)
    assert any(f.code == Codes.START_NOT_FOUND for f in report.findings)
    assert report.orphans == []


def test_empty_flow_is_safe():
    # No actions: no findings, ok is True, and format_report takes its
    # "(no structural issues found)" branch instead of listing anything.
    report = build_report({"id": "1", "name": "empty", "startActionId": None, "actions": []})
    assert report.action_count == 0
    assert report.findings == []
    assert report.ok is True
    assert "(no structural issues found)" in format_report(report)
