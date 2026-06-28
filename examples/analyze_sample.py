"""Analyze the bundled synthetic flow (no HubSpot credentials needed).

    python examples/analyze_sample.py

Equivalent to: ``hsflow analyze examples/sample_flow.json``
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from hsflow import build_report, format_report  # noqa: E402

HERE = os.path.dirname(__file__)

with open(os.path.join(HERE, "sample_flow.json"), encoding="utf-8") as fh:
    flow = json.load(fh)

report = build_report(flow)
print(format_report(report))
