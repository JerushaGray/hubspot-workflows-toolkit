"""Static metadata and pure helpers for interpreting a HubSpot v4 flow.

Nothing here touches the network. These are the constants and helpers used to
*read* a flow definition returned by ``GET /automation/v4/flows/{id}``.

Action types
------------
Most steps in a v4 flow carry an ``actionTypeId`` string. Branch steps instead
carry ``"type": "LIST_BRANCH"``. The table below covers the action types
commonly seen in marketing / email workflows; HubSpot's full catalog is larger
and may grow, so an unrecognized id is reported as ``UNKNOWN`` rather than
guessed at.
"""
from __future__ import annotations

# Action-type ids observed in marketing/email workflows.
ACTION_TYPE_DELAY = "0-1"
ACTION_TYPE_SEND_EMAIL = "0-4"
ACTION_TYPE_SET_PROPERTY = "0-5"

# Branch steps use "type" (not "actionTypeId").
ACTION_TYPE_LIST_BRANCH = "LIST_BRANCH"

# id -> (short label, human description)
ACTION_TYPES = {
    ACTION_TYPE_DELAY: (
        "DELAY",
        "Wait. fields.delta is in MINUTES (not ms); days = delta / 1440.",
    ),
    ACTION_TYPE_SEND_EMAIL: (
        "SEND_EMAIL",
        "Send a marketing email. fields.content_id = the marketing email id.",
    ),
    ACTION_TYPE_SET_PROPERTY: (
        "SET_PROPERTY",
        "Set/stamp a property. fields.property_name + value "
        "(a staticValue, or an EXECUTION_TIME timestamp = 'stamp now').",
    ),
    ACTION_TYPE_LIST_BRANCH: (
        "LIST_BRANCH",
        "If/then branch. listBranches[] of named conditions + optional defaultBranch.",
    ),
}

MINUTES_PER_DAY = 1440
MINUTES_PER_HOUR = 60


def action_kind(action: dict) -> str:
    """Return the type id for an action, preferring ``type`` (used by branches)."""
    if action.get("type"):
        return action["type"]
    return action.get("actionTypeId", "")


def action_type_label(type_id: str) -> str:
    entry = ACTION_TYPES.get(type_id)
    return entry[0] if entry else "UNKNOWN"


def action_type_description(type_id: str) -> str:
    entry = ACTION_TYPES.get(type_id)
    return entry[1] if entry else f"Unrecognized action type {type_id!r}."


def humanize_delay_minutes(minutes: int) -> str:
    """Render a delay given in minutes: 4320 -> '3 days', 120 -> '2 hours'."""
    if minutes is None or minutes <= 0:
        return "0 minutes"
    if minutes % MINUTES_PER_DAY == 0:
        d = minutes // MINUTES_PER_DAY
        return f"{d} day{'s' if d != 1 else ''}"
    if minutes % MINUTES_PER_HOUR == 0:
        h = minutes // MINUTES_PER_HOUR
        return f"{h} hour{'s' if h != 1 else ''}"
    return f"{minutes} minute{'s' if minutes != 1 else ''}"
