from datetime import datetime, timezone

import pytest

from hsflow.client import (
    HubSpotAPIError,
    HubSpotAuthError,
    HubSpotConnectionError,
    WorkflowsClient,
    load_token,
    to_iso8601,
)


def test_to_iso8601_passes_through_strings():
    assert to_iso8601("2026-03-04T00:00:00Z") == "2026-03-04T00:00:00Z"


def test_to_iso8601_formats_datetime():
    dt = datetime(2026, 3, 4, tzinfo=timezone.utc)
    assert to_iso8601(dt) == "2026-03-04T00:00:00Z"


def test_to_iso8601_assumes_utc_for_naive_datetime():
    assert to_iso8601(datetime(2026, 3, 4)) == "2026-03-04T00:00:00Z"


def test_to_iso8601_rejects_epoch_millis():
    # HubSpot's stats endpoint 400s on epoch ms; reject it early and loudly.
    with pytest.raises(TypeError):
        to_iso8601(1740000000000)


def test_load_token_prefers_argument():
    assert load_token("  pat-na1-abc  ") == "pat-na1-abc"


def test_load_token_reads_env(monkeypatch):
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-na1-from-env")
    assert load_token() == "pat-na1-from-env"


def test_load_token_raises_when_missing(monkeypatch):
    monkeypatch.delenv("HUBSPOT_TOKEN", raising=False)
    monkeypatch.delenv("HUBSPOT_TOKEN_FILE", raising=False)
    with pytest.raises(HubSpotAuthError):
        load_token()


# --- HTTP layer: retry, backoff, fallback, and error wrapping ---------------
# Driven through an injected fake session (and a no-op sleep) so nothing hits
# the network. Constructing a client needs `requests`, so these skip without it.

class _Resp:
    def __init__(self, status_code, json_data=None, text="", headers=None, reason=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}
        self.reason = reason

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


class _Session:
    """Yields the given outcomes (responses or exceptions-to-raise) in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(session, **kwargs):
    pytest.importorskip("requests")  # client construction requires requests
    return WorkflowsClient(token="x", session=session, sleep=lambda _seconds: None, **kwargs)


def test_get_retries_on_429_then_succeeds():
    session = _Session([_Resp(429, headers={"Retry-After": "0"}), _Resp(200, {"ok": True})])
    assert _client(session).get_flow("123") == {"ok": True}
    assert len(session.calls) == 2


def test_get_raises_api_error_after_exhausting_retries():
    session = _Session([_Resp(500, text="boom")] * 6)
    with pytest.raises(HubSpotAPIError) as exc:
        _client(session, max_retries=2).get_flow("123")
    assert exc.value.status_code == 500
    assert len(session.calls) == 3  # 1 initial + 2 retries


def test_non_retryable_status_raises_immediately():
    session = _Session([_Resp(403, text="nope")])
    with pytest.raises(HubSpotAPIError) as exc:
        _client(session).get_flow("123")
    assert exc.value.status_code == 403
    assert len(session.calls) == 1


def test_transport_error_is_retried_then_wrapped():
    requests = pytest.importorskip("requests")
    boom = requests.exceptions.ConnectionError("down")
    session = _Session([boom, boom, boom])
    with pytest.raises(HubSpotConnectionError):
        _client(session, max_retries=2).get_flow("123")
    assert len(session.calls) == 3


def test_transport_error_recovers_on_retry():
    requests = pytest.importorskip("requests")
    session = _Session([requests.exceptions.Timeout("slow"), _Resp(200, {"ok": 1})])
    assert _client(session).get_flow("123") == {"ok": 1}


def test_get_list_falls_back_to_legacy_on_404():
    session = _Session([_Resp(404, text="not in v3"), _Resp(200, {"legacy": True})])
    assert _client(session).get_list("4092") == {"legacy": True}
    assert "/crm/v3/lists/4092" in session.calls[0]
    assert "/contacts/v1/lists/4092" in session.calls[1]


def test_get_list_reraises_non_404():
    # A non-404 (and non-retryable) error must propagate, not trigger the
    # legacy fallback. 403 is not in the retryable set, so it raises at once.
    session = _Session([_Resp(403, text="forbidden")])
    with pytest.raises(HubSpotAPIError) as exc:
        _client(session).get_list("4092")
    assert exc.value.status_code == 403
    assert len(session.calls) == 1


def test_non_json_success_body_becomes_api_error():
    session = _Session([_Resp(200, json_data=None, text="<html>oops</html>")])
    with pytest.raises(HubSpotAPIError):
        _client(session).get_flow("123")


def test_email_statistics_builds_iso_and_repeated_ids():
    captured = {}

    class _Capture(_Session):
        def get(self, url, params=None, timeout=None):
            captured["params"] = params
            return _Resp(200, {})

    _client(_Capture([])).get_email_statistics(
        ["100", 200], datetime(2026, 3, 1, tzinfo=timezone.utc), "2026-03-08T00:00:00Z"
    )
    assert captured["params"]["startTimestamp"] == "2026-03-01T00:00:00Z"
    assert captured["params"]["endTimestamp"] == "2026-03-08T00:00:00Z"
    assert captured["params"]["emailIds"] == ["100", "200"]
