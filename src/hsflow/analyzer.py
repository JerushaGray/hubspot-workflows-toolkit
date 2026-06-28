"""Static analysis of a HubSpot v4 flow definition.

Given the JSON from ``GET /automation/v4/flows/{id}``, build the action graph
and surface the structural defects the HubSpot UI hides behind its canvas:

  * dangling links          - a step points at an action id that does not exist
  * orphan actions          - a defined action is unreachable from the start
  * branches with no default - potential silent drop-off (verify it partitions)
  * GOTO edges              - merges/loops to follow and confirm they terminate

Why this exists: action ids (1, 8, 137, ...) are internal and never shown in
the editor, so a broken link or an unreachable step is invisible there. Auditing
the JSON makes them obvious.

The analyzer is pure and offline — pass it a dict (e.g. ``json.load`` of a saved
flow) and it returns a :class:`FlowReport`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, List, Optional

from .models import (
    ACTION_TYPE_DELAY,
    ACTION_TYPE_LIST_BRANCH,
    ACTION_TYPE_SEND_EMAIL,
    action_kind,
    action_type_label,
    humanize_delay_minutes,
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
_SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}


@dataclass
class Finding:
    severity: str
    code: str
    message: str
    action_id: Optional[str] = None

    def __str__(self) -> str:
        where = f" [action {self.action_id}]" if self.action_id else ""
        return f"{self.severity.upper():7} {self.code}{where}: {self.message}"


@dataclass
class FlowReport:
    flow_id: Optional[str]
    name: Optional[str]
    is_enabled: Optional[bool]
    start_action_id: Optional[str]
    action_count: int
    type_counts: dict
    defined_ids: List[str]
    referenced_ids: List[str]
    orphans: List[str]
    dangling: List[str]
    terminals: List[str]
    gotos: List[dict]
    branches: List[dict]
    delays: List[dict]
    content_ids: List[str]
    list_ids: List[str]
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == SEVERITY_WARNING]

    @property
    def ok(self) -> bool:
        """True when there are no errors or warnings (info is allowed)."""
        return not self.errors and not self.warnings


def _iter_dicts(obj: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere within obj (depth-first)."""
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _iter_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_dicts(value)


def _edges(action: dict) -> Iterator[tuple]:
    """Yield (edge_type, target_id) for every outgoing connection in an action.

    Connections live at the top level (``connection``) and inside each
    ``listBranches[]`` entry and the ``defaultBranch`` of a LIST_BRANCH. Walking
    for any dict carrying ``nextActionId`` finds them all, schema changes aside.
    """
    for d in _iter_dicts(action):
        nxt = d.get("nextActionId")
        if nxt is not None:
            yield (d.get("edgeType", "STANDARD"), str(nxt))


def _int_key(value: str):
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def build_report(flow: dict) -> FlowReport:
    """Analyze a v4 flow dict and return a structural :class:`FlowReport`."""
    actions = flow.get("actions") or []
    start = flow.get("startActionId")
    start = str(start) if start is not None else None

    defined_ids = [str(a.get("actionId")) for a in actions if a.get("actionId") is not None]
    defined_set = set(defined_ids)

    adjacency: dict = {}
    referenced: set = set()
    gotos: List[dict] = []
    terminals: List[str] = []
    type_counts: dict = {}
    branches: List[dict] = []
    delays: List[dict] = []
    content_ids: List[str] = []

    for action in actions:
        aid = str(action.get("actionId"))
        kind = action_kind(action)
        type_counts[action_type_label(kind)] = type_counts.get(action_type_label(kind), 0) + 1

        out = list(_edges(action))
        adjacency[aid] = [target for _, target in out]
        for edge_type, target in out:
            referenced.add(target)
            if edge_type == "GOTO":
                gotos.append({"from": aid, "to": target})
        if not out:
            terminals.append(aid)

        if kind == ACTION_TYPE_LIST_BRANCH:
            branches.append(
                {
                    "action_id": aid,
                    "name": action.get("branchName") or action.get("name"),
                    "branch_count": len(action.get("listBranches") or []),
                    "has_default": "defaultBranch" in action,
                }
            )
        elif kind == ACTION_TYPE_DELAY:
            raw = (action.get("fields") or {}).get("delta")
            try:
                minutes = int(raw)
            except (TypeError, ValueError):
                minutes = None
            delays.append(
                {
                    "action_id": aid,
                    "minutes": minutes,
                    "human": humanize_delay_minutes(minutes) if minutes is not None else "unknown",
                }
            )
        elif kind == ACTION_TYPE_SEND_EMAIL:
            cid = (action.get("fields") or {}).get("content_id")
            if cid is not None:
                content_ids.append(str(cid))

    # Every list id referenced anywhere (enrollment, branch filters, suppression).
    list_ids = sorted(
        {str(d["listId"]) for d in _iter_dicts(flow) if d.get("listId") is not None},
        key=_int_key,
    )

    # Reachability from the start action — the authoritative orphan check.
    reachable: set = set()
    if start is not None:
        stack = [start]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for target in adjacency.get(node, []):
                if target in defined_set and target not in reachable:
                    stack.append(target)

    orphans = sorted(defined_set - reachable, key=_int_key) if start is not None else []
    dangling = sorted(referenced - defined_set, key=_int_key)

    findings: List[Finding] = []
    for missing in dangling:
        for src in sorted((aid for aid, t in adjacency.items() if missing in t), key=_int_key):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "DANGLING_LINK",
                    f"points to action {missing}, which does not exist (broken link).",
                    src,
                )
            )
    for orphan in orphans:
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "ORPHAN_ACTION",
                "defined but unreachable from the start action (dead step).",
                orphan,
            )
        )
    for b in branches:
        if not b["has_default"]:
            findings.append(
                Finding(
                    SEVERITY_WARNING,
                    "BRANCH_NO_DEFAULT",
                    f"LIST_BRANCH with {b['branch_count']} branch(es) and no default: "
                    "contacts matching none will silently exit unless the branch "
                    "conditions fully partition the audience (e.g. IN_LIST + "
                    "NOT_IN_LIST on the same list). Verify coverage.",
                    b["action_id"],
                )
            )
    for g in gotos:
        findings.append(
            Finding(
                SEVERITY_INFO,
                "GOTO_EDGE",
                f"GOTO -> action {g['to']} (merge/loop); confirm any loop can terminate.",
                g["from"],
            )
        )

    findings.sort(key=lambda f: (_SEVERITY_ORDER.get(f.severity, 9), f.code, _int_key(f.action_id or "")))

    return FlowReport(
        flow_id=str(flow["id"]) if flow.get("id") is not None else None,
        name=flow.get("name"),
        is_enabled=flow.get("isEnabled"),
        start_action_id=start,
        action_count=len(actions),
        type_counts=type_counts,
        defined_ids=sorted(defined_set, key=_int_key),
        referenced_ids=sorted(referenced, key=_int_key),
        orphans=orphans,
        dangling=dangling,
        terminals=sorted(terminals, key=_int_key),
        gotos=gotos,
        branches=branches,
        delays=delays,
        content_ids=content_ids,
        list_ids=list_ids,
        findings=findings,
    )


def format_report(report: FlowReport) -> str:
    """Render a :class:`FlowReport` as a readable text block."""
    lines: List[str] = []
    lines.append(f"Flow: {report.name or '(unnamed)'}  (id={report.flow_id}, enabled={report.is_enabled})")
    lines.append(f"Start action: {report.start_action_id}   Actions: {report.action_count}")
    if report.type_counts:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(report.type_counts.items()))
        lines.append(f"Action types: {counts}")
    if report.delays:
        ds = ", ".join(f"{d['action_id']}:{d['human']}" for d in report.delays)
        lines.append(f"Delays: {ds}")
    if report.branches:
        no_default = sum(1 for b in report.branches if not b["has_default"])
        lines.append(f"Branches: {len(report.branches)} ({no_default} without a default)")
    lines.append(f"Emails sent: {len(report.content_ids)}  content_ids={report.content_ids}")
    if report.list_ids:
        lines.append(f"Lists referenced: {report.list_ids}")
    lines.append(f"Terminals: {report.terminals}")
    if report.gotos:
        lines.append("GOTO edges: " + ", ".join(f"{g['from']}->{g['to']}" for g in report.gotos))

    n_err, n_warn = len(report.errors), len(report.warnings)
    n_info = len(report.findings) - n_err - n_warn
    lines.append("")
    lines.append(f"Findings: {n_err} error(s), {n_warn} warning(s), {n_info} info")
    if report.findings:
        for f in report.findings:
            lines.append(f"  {f}")
    else:
        lines.append("  (no structural issues found)")
    return "\n".join(lines)
