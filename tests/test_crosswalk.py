import json
import os

from hsflow.client import HubSpotAPIError
from hsflow.crosswalk import build_crosswalk, format_crosswalk

HERE = os.path.dirname(__file__)
SAMPLE = os.path.join(HERE, "..", "examples", "sample_flow.json")


def load_sample():
    with open(SAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


class FakeClient:
    """Offline stand-in for WorkflowsClient: canned lookups, no network."""

    EMAILS = {
        "100001": {"name": "Welcome aboard", "subject": "Welcome!", "state": "PUBLISHED"},
        "100002": {"name": "Glad you are active", "subject": "Nice to see you", "state": "PUBLISHED"},
        "100003": {"name": "We miss you", "subject": "Come back", "state": "PUBLISHED"},
        "100004": {"name": "Package A tips", "subject": "Tips", "state": "PUBLISHED"},
        # 100005 is intentionally absent -> simulates a deleted email (404).
    }
    LISTS = {
        # CRM v3 shape (wrapped under "list")
        "5001": {"list": {"name": "Engaged in last 30 days", "processingType": "DYNAMIC",
                          "additionalProperties": {"hs_list_size": "12345"}}},
        "5002": {"list": {"name": "Has Package A", "processingType": "DYNAMIC",
                          "additionalProperties": {"hs_list_size": "678"}}},
        # legacy /contacts/v1 shape (flat)
        "5003": {"name": "Has Package B (legacy)", "dynamic": True, "metaData": {"size": "910"}},
    }

    def get_email(self, email_id):
        eid = str(email_id)
        if eid not in self.EMAILS:
            raise HubSpotAPIError(404, "not found", f"/marketing/v3/emails/{eid}")
        return self.EMAILS[eid]

    def get_list(self, list_id, **kwargs):
        lid = str(list_id)
        if lid not in self.LISTS:
            raise HubSpotAPIError(404, "not found", f"/crm/v3/lists/{lid}")
        return self.LISTS[lid]


def test_resolves_email_names():
    cw = build_crosswalk(load_sample(), FakeClient())
    assert cw.emails["100001"]["name"] == "Welcome aboard"
    assert cw.emails["100001"]["subject"] == "Welcome!"


def test_missing_email_recorded_not_raised():
    cw = build_crosswalk(load_sample(), FakeClient())
    assert cw.emails["100005"].get("error")          # 404 captured
    assert "email 100005" in cw.unresolved


def test_resolves_list_crm_v3_shape():
    cw = build_crosswalk(load_sample(), FakeClient())
    assert cw.lists["5001"]["name"] == "Engaged in last 30 days"
    assert cw.lists["5001"]["size"] == "12345"
    assert cw.lists["5001"]["source"] == "crm/v3"


def test_resolves_list_legacy_shape():
    cw = build_crosswalk(load_sample(), FakeClient())
    assert cw.lists["5003"]["name"] == "Has Package B (legacy)"
    assert cw.lists["5003"]["size"] == "910"
    assert cw.lists["5003"]["source"] == "contacts/v1"


def test_branch_labels_from_flow_json():
    cw = build_crosswalk(load_sample(), FakeClient())
    assert cw.branches["5"]["paths"] == ["Engaged in last 30 days"]
    assert cw.branches["5"]["default"] == "Not engaged"
    assert cw.branches["8"]["paths"] == ["Has Package A", "Has Package B"]
    assert cw.branches["8"]["default"] is None  # the no-default branch from the sample


def test_format_text_mentions_names_and_unresolved():
    out = format_crosswalk(build_crosswalk(load_sample(), FakeClient()))
    assert "Welcome aboard" in out
    assert "Engaged in last 30 days" in out
    assert "unresolved" in out.lower()


def test_format_markdown_has_tables():
    out = format_crosswalk(build_crosswalk(load_sample(), FakeClient()), markdown=True)
    assert "### Emails" in out
    assert "| content_id | name | subject | state |" in out
    assert "Has Package B (legacy)" in out


def test_requires_client():
    try:
        build_crosswalk(load_sample(), None)
    except ValueError:
        return
    raise AssertionError("expected ValueError when client is None")
