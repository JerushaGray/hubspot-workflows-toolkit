from hsflow.models import (
    action_kind,
    action_type_description,
    action_type_label,
    humanize_delay_minutes,
)


def test_humanize_delay_minutes():
    assert humanize_delay_minutes(4320) == "3 days"
    assert humanize_delay_minutes(1440) == "1 day"
    assert humanize_delay_minutes(120) == "2 hours"
    assert humanize_delay_minutes(60) == "1 hour"
    assert humanize_delay_minutes(45) == "45 minutes"
    assert humanize_delay_minutes(1) == "1 minute"
    assert humanize_delay_minutes(0) == "0 minutes"


def test_action_type_label():
    assert action_type_label("0-1") == "DELAY"
    assert action_type_label("0-4") == "SEND_EMAIL"
    assert action_type_label("0-5") == "SET_PROPERTY"
    assert action_type_label("LIST_BRANCH") == "LIST_BRANCH"
    assert action_type_label("9-99") == "UNKNOWN"


def test_action_type_description_unknown():
    assert "Unrecognized" in action_type_description("9-99")


def test_action_kind_prefers_type_for_branches():
    assert action_kind({"type": "LIST_BRANCH", "actionTypeId": "0-9"}) == "LIST_BRANCH"
    assert action_kind({"actionTypeId": "0-4"}) == "0-4"
