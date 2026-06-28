"""Resolve the opaque ids in a flow to human labels (the "crosswalk").

The analyzer (:mod:`hsflow.analyzer`) is deliberately offline, so it can only
report the raw ids a flow references: `content_id` for each email it sends and
`listId` for each list it branches on. Those numbers mean nothing to a
stakeholder, and you can't act on a finding you can't name.

This module does the translation the audit always needs: it uses a
:class:`~hsflow.client.WorkflowsClient` to look up each id and build a map of

  * email `content_id`  -> name, subject, state
  * `listId`            -> name, size, source endpoint
  * branch `actionId`   -> its branch path names and default (from the flow JSON)

A lookup that 404s (a deleted or inaccessible asset) is recorded as an error
rather than raised. A stamp or send pointing at a deleted email is exactly the
kind of "phantom" the audit hunts for, so surfacing it is the point.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .analyzer import build_report
from .client import HubSpotAPIError


@dataclass
class Crosswalk:
    flow_id: Optional[str]
    flow_name: Optional[str]
    emails: Dict[str, dict] = field(default_factory=dict)   # content_id -> {...}
    lists: Dict[str, dict] = field(default_factory=dict)    # listId     -> {...}
    branches: Dict[str, dict] = field(default_factory=dict)  # actionId   -> {paths, default}

    @property
    def unresolved(self) -> List[str]:
        """Ids that could not be resolved (deleted or no access)."""
        out = [f"email {cid}" for cid, v in self.emails.items() if v.get("error")]
        out += [f"list {lid}" for lid, v in self.lists.items() if v.get("error")]
        return out


def _summarize_email(data: dict) -> dict:
    return {
        "name": data.get("name"),
        "subject": data.get("subject"),
        "state": data.get("state"),
    }


def _summarize_list(data: dict) -> dict:
    # CRM v3 wraps the list under "list"; legacy /contacts/v1 is flat.
    inner = data.get("list")
    if isinstance(inner, dict):
        extra = inner.get("additionalProperties") or {}
        return {
            "name": inner.get("name"),
            "size": extra.get("hs_list_size"),
            "processing_type": inner.get("processingType"),
            "source": "crm/v3",
        }
    meta = data.get("metaData") or {}
    return {
        "name": data.get("name"),
        "size": meta.get("size"),
        "processing_type": "DYNAMIC" if data.get("dynamic") else "STATIC",
        "source": "contacts/v1",
    }


def _branch_labels(flow: dict) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for action in flow.get("actions") or []:
        if action.get("type") == "LIST_BRANCH":
            aid = str(action.get("actionId"))
            out[aid] = {
                "paths": [lb.get("branchName") for lb in (action.get("listBranches") or [])],
                "default": action.get("defaultBranchName"),
            }
    return out


def build_crosswalk(flow: dict, client, *, report=None) -> Crosswalk:
    """Resolve a flow's ids to labels using ``client`` (a WorkflowsClient).

    ``report`` may be supplied to avoid re-analyzing the flow; otherwise it is
    computed here. Branch labels come from the flow JSON and need no API call.
    """
    if client is None:
        raise ValueError("build_crosswalk needs a WorkflowsClient to resolve ids.")
    if report is None:
        report = build_report(flow)

    emails: Dict[str, dict] = {}
    for cid in dict.fromkeys(report.content_ids):  # dedupe, preserve order
        try:
            emails[cid] = _summarize_email(client.get_email(cid))
        except HubSpotAPIError as exc:
            emails[cid] = {"error": f"HTTP {exc.status_code}", "name": None}

    lists: Dict[str, dict] = {}
    for lid in report.list_ids:
        try:
            lists[lid] = _summarize_list(client.get_list(lid))
        except HubSpotAPIError as exc:
            lists[lid] = {"error": f"HTTP {exc.status_code}", "name": None}

    return Crosswalk(
        flow_id=report.flow_id,
        flow_name=report.name,
        emails=emails,
        lists=lists,
        branches=_branch_labels(flow),
    )


def _email_line(cid: str, info: dict) -> str:
    if info.get("error"):
        return f"  {cid}  (unresolved: {info['error']} - deleted or no access)"
    subject = info.get("subject")
    subj = f'  "{subject}"' if subject else ""
    state = f"  [{info['state']}]" if info.get("state") else ""
    return f"  {cid}  {info.get('name') or '(unnamed)'}{subj}{state}"


def _list_line(lid: str, info: dict) -> str:
    if info.get("error"):
        return f"  {lid}  (unresolved: {info['error']} - deleted or no access)"
    size = info.get("size")
    size_s = f"  size={size}" if size is not None else ""
    src = f"  [{info['source']}]" if info.get("source") else ""
    return f"  {lid}  {info.get('name') or '(unnamed)'}{size_s}{src}"


def _branch_line(aid: str, info: dict) -> str:
    paths = " / ".join(p or "(unnamed)" for p in info.get("paths") or []) or "(none)"
    default = info.get("default")
    tail = f"  [default: {default}]" if default else "  [no default]"
    return f"  {aid}  {paths}{tail}"


def format_crosswalk(cw: Crosswalk, *, markdown: bool = False) -> str:
    if markdown:
        return _format_markdown(cw)
    lines: List[str] = [f"Crosswalk: {cw.flow_name or '(unnamed)'} (id={cw.flow_id})", ""]
    lines.append("Emails (content_id -> name | subject | state)")
    lines += [_email_line(c, i) for c, i in cw.emails.items()] or ["  (none)"]
    lines.append("")
    lines.append("Lists (listId -> name | size | source)")
    lines += [_list_line(l, i) for l, i in cw.lists.items()] or ["  (none)"]
    lines.append("")
    lines.append("Branches (action id -> paths [default])")
    lines += [_branch_line(a, i) for a, i in cw.branches.items()] or ["  (none)"]
    if cw.unresolved:
        lines += ["", f"Unresolved: {', '.join(cw.unresolved)}"]
    return "\n".join(lines)


def _format_markdown(cw: Crosswalk) -> str:
    lines: List[str] = [f"## Crosswalk: {cw.flow_name or '(unnamed)'} (id={cw.flow_id})", ""]

    lines += ["### Emails", "", "| content_id | name | subject | state |", "| --- | --- | --- | --- |"]
    for cid, info in cw.emails.items():
        if info.get("error"):
            lines.append(f"| {cid} | _unresolved ({info['error']})_ | | |")
        else:
            lines.append(f"| {cid} | {info.get('name') or ''} | {info.get('subject') or ''} | {info.get('state') or ''} |")

    lines += ["", "### Lists", "", "| listId | name | size | source |", "| --- | --- | --- | --- |"]
    for lid, info in cw.lists.items():
        if info.get("error"):
            lines.append(f"| {lid} | _unresolved ({info['error']})_ | | |")
        else:
            lines.append(f"| {lid} | {info.get('name') or ''} | {info.get('size') or ''} | {info.get('source') or ''} |")

    lines += ["", "### Branches", "", "| action id | paths | default |", "| --- | --- | --- |"]
    for aid, info in cw.branches.items():
        paths = " / ".join(p or "(unnamed)" for p in info.get("paths") or [])
        lines.append(f"| {aid} | {paths} | {info.get('default') or ''} |")

    return "\n".join(lines)
