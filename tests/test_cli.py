"""Tests for the CLI, driven through main(argv) so no subprocess is needed.

The exit-code contract: 0 = clean, 1 = analyze found defects, 2 = the command
could not run. The synthetic sample contains a dangling link (an error), so
`analyze` on it exits 1.
"""
import json
import os

from hsflow.cli import main

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample_flow.json")


def test_decode_returns_zero_and_explains(capsys):
    rc = main(["decode", "0-4"])
    assert rc == 0
    assert "SEND_EMAIL" in capsys.readouterr().out


def test_analyze_exits_one_when_defects_found(capsys):
    # The sample's dangling link is an error, so analyze reports a non-zero code.
    rc = main(["analyze", SAMPLE])
    assert rc == 1
    assert "DANGLING_LINK" in capsys.readouterr().out


def test_analyze_json_is_parseable(capsys):
    rc = main(["analyze", SAMPLE, "--json"])
    assert rc == 1
    data = json.loads(capsys.readouterr().out)
    assert data["dangling"] == ["9999"]


def test_analyze_mermaid_emits_a_flowchart(capsys):
    # --mermaid returns 0 regardless of defects: it is a render, not a verdict.
    rc = main(["analyze", SAMPLE, "--mermaid"])
    assert rc == 0
    assert capsys.readouterr().out.startswith("flowchart TD")


def test_missing_file_is_a_clean_error_not_a_traceback(capsys):
    rc = main(["analyze", os.path.join(HERE, "does_not_exist.json")])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""                  # nothing leaks to stdout
    assert captured.err.startswith("error:")   # clean one-line message on stderr
