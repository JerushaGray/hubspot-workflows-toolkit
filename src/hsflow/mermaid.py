"""Render a flow definition as a Mermaid flowchart.

GitHub renders ```mermaid blocks natively, so `to_mermaid` turns the action
graph into a picture with the defects the analyzer finds highlighted:

  * dangling targets (a step pointing at a missing action) in red
  * orphan steps (unreachable from the start) in orange
  * branches with no default in yellow
  * the start action in green

It is offline: it only needs the flow dict (and reuses the analyzer to classify
the nodes). GOTO edges render as dashed, labelled arrows.
"""
from __future__ import annotations

from typing import List, Optional

from .analyzer import FlowReport, build_report, iter_edges
from .models import (
    ACTION_TYPE_DELAY,
    ACTION_TYPE_LIST_BRANCH,
    ACTION_TYPE_SEND_EMAIL,
    ACTION_TYPE_SET_PROPERTY,
    action_kind,
    action_type_label,
    humanize_delay_minutes,
)


def _san(text) -> str:
    # Keep node labels safe inside a Mermaid ["..."] string.
    return str(text).replace('"', "'").replace("[", "(").replace("]", ")")


def _node_label(action: dict) -> str:
    aid = str(action.get("actionId"))
    kind = action_kind(action)
    label = action_type_label(kind)
    fields = action.get("fields") or {}
    detail = ""
    if kind == ACTION_TYPE_DELAY:
        try:
            detail = " " + humanize_delay_minutes(int(fields.get("delta")))
        except (TypeError, ValueError):
            detail = ""
    elif kind == ACTION_TYPE_SEND_EMAIL:
        cid = fields.get("content_id")
        detail = f" #{cid}" if cid else ""
    elif kind == ACTION_TYPE_SET_PROPERTY:
        prop = fields.get("property_name")
        detail = f" {prop}" if prop else ""
    elif kind == ACTION_TYPE_LIST_BRANCH:
        label = "BRANCH"
    return _san(f"{aid}: {label}{detail}")


def to_mermaid(flow: dict, report: Optional[FlowReport] = None) -> str:
    """Return Mermaid flowchart source (no ```mermaid fence) for a flow dict."""
    if report is None:
        report = build_report(flow)
    actions = flow.get("actions") or []
    dangling = sorted(set(report.dangling))
    orphans = sorted(set(report.orphans))
    nodefault = sorted({branch["action_id"] for branch in report.branches if not branch["has_default"]})
    start = report.start_action_id

    lines: List[str] = ["flowchart TD"]

    # Node declarations.
    for action in actions:
        aid = str(action.get("actionId"))
        lines.append(f'  n{aid}["{_node_label(action)}"]')
    for missing in dangling:
        lines.append(f'  n{missing}["{missing} (missing)"]')

    # Edges.
    for action in actions:
        src = f"n{action.get('actionId')}"
        for edge_type, target in iter_edges(action):
            if edge_type == "GOTO":
                lines.append(f"  {src} -. GOTO .-> n{target}")
            else:
                lines.append(f"  {src} --> n{target}")

    # Defect styling.
    lines.append("  classDef dangling fill:#ffd6d6,stroke:#d33333,color:#7a0000;")
    lines.append("  classDef orphan fill:#ffe3c2,stroke:#e08a00,color:#7a4a00;")
    lines.append("  classDef nodefault fill:#fff3b0,stroke:#c9a800,color:#6b5b00;")
    lines.append("  classDef start fill:#d7f3d7,stroke:#2c9c2c,color:#0c5c0c;")
    for missing in dangling:
        lines.append(f"  class n{missing} dangling;")
    for orphan in orphans:
        lines.append(f"  class n{orphan} orphan;")
    for branch in nodefault:
        lines.append(f"  class n{branch} nodefault;")
    if start:
        lines.append(f"  class n{start} start;")

    return "\n".join(lines)
