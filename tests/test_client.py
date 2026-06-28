from datetime import datetime, timezone

import pytest

from hsflow.client import HubSpotAuthError, load_token, to_iso8601


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
