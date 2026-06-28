"""hsflow — a small client and static analyzer for the HubSpot Workflows v4 API.

Two independent halves:

* ``WorkflowsClient`` — a thin, retrying HTTP client for the workflow / list /
  email / email-stats endpoints (needs ``requests`` and a private-app token).
* ``build_report`` — a pure, offline analyzer that turns a flow definition into
  a structural report (orphans, dangling links, GOTO loops, branch coverage).

The analyzer never touches the network, so you can audit a saved flow JSON with
no credentials at all.
"""
from .analyzer import Finding, FlowReport, build_report, format_report
from .client import (
    HubSpotAPIError,
    HubSpotAuthError,
    WorkflowsClient,
    load_token,
)
from .models import (
    ACTION_TYPES,
    action_type_description,
    action_type_label,
    humanize_delay_minutes,
)

__version__ = "0.1.0"

__all__ = [
    "WorkflowsClient",
    "HubSpotAPIError",
    "HubSpotAuthError",
    "load_token",
    "build_report",
    "format_report",
    "FlowReport",
    "Finding",
    "ACTION_TYPES",
    "action_type_label",
    "action_type_description",
    "humanize_delay_minutes",
    "__version__",
]
