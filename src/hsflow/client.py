"""A thin, dependency-light client for the HubSpot Workflows (Automation) v4 API.

Wraps the handful of endpoints needed to pull and reason about workflows:

  * GET /automation/v4/flows/{id}                - workflow ("flow") definition
  * GET /crm/v3/lists/{id}?includeFilters=true   - list definition
        (falls back to GET /contacts/v1/lists/{id} for legacy list ids)
  * GET /marketing/v3/emails/{id}                - marketing email
  * GET /marketing/v3/emails/statistics/list     - per-email stats for a window

Auth is a HubSpot private-app token ("pat-na1-..."). Never hard-code it: pass it
explicitly, set ``HUBSPOT_TOKEN``, or point at a token file.

Error model: every failure raises a subclass of :class:`HubSpotError`, so a
caller never has to know about ``requests``. ``requests`` itself is imported
lazily, so the rest of the package (the analyzer) works with no third-party
dependency installed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Iterable, Optional, Union

try:  # optional: only needed to actually make HTTP calls
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_BASE_URL = "https://api.hubapi.com"
_RETRYABLE = {429, 500, 502, 503, 504}
_MAX_BACKOFF = 30


class HubSpotError(RuntimeError):
    """Base class for every error this client raises."""


class HubSpotAuthError(HubSpotError):
    """Raised when no token can be found."""


class HubSpotAPIError(HubSpotError):
    """Raised for a non-retryable (or retry-exhausted) HTTP error response."""

    def __init__(self, status_code: int, message: str, url: str):
        super().__init__(f"HTTP {status_code} for {url}: {message}")
        self.status_code = status_code
        self.url = url


class HubSpotConnectionError(HubSpotError):
    """Raised when the request never received an HTTP response (transport failure)."""

    def __init__(self, message: str, url: str):
        super().__init__(message)
        self.url = url


def _backoff_seconds(attempt: int) -> float:
    """Capped exponential backoff: 2, 4, 8, ... up to _MAX_BACKOFF seconds."""
    return float(min(2 ** attempt, _MAX_BACKOFF))


def to_iso8601(value: Union[str, datetime]) -> str:
    """Coerce a timestamp to ISO-8601 UTC, e.g. ``2026-03-04T00:00:00Z``.

    ``/marketing/v3/emails/statistics/list`` *requires* ISO-8601 timestamps;
    passing epoch milliseconds returns HTTP 400. This makes the correct format
    the default and rejects raw epochs loudly instead of failing at the API.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise TypeError(
        "stats timestamps must be ISO-8601 strings or datetime objects, "
        f"not {type(value).__name__} (HubSpot rejects epoch milliseconds)."
    )


def load_token(token: Optional[str] = None, token_file: Optional[str] = None) -> str:
    """Resolve a token from (in order): argument, ``HUBSPOT_TOKEN``, a file."""
    if token:
        return token.strip()
    env = os.environ.get("HUBSPOT_TOKEN")
    if env:
        return env.strip()
    path = token_file or os.environ.get("HUBSPOT_TOKEN_FILE")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    raise HubSpotAuthError(
        "No HubSpot token found. Pass token=..., set the HUBSPOT_TOKEN "
        "environment variable, or provide a token file."
    )


class WorkflowsClient:
    """Minimal HubSpot client scoped to workflows and their referenced assets."""

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        token_file: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        session=None,
        max_retries: int = 4,
        timeout: float = 30,
        sleep=None,
    ):
        if requests is None:  # pragma: no cover
            raise RuntimeError(
                "The 'requests' package is required for network calls. "
                "Install it with: pip install requests"
            )
        self._token = load_token(token, token_file)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        # injectable for tests; defaults to time.sleep
        if sleep is None:
            import time

            sleep = time.sleep
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            }
        )

    # -- core request: retry transport errors + 429/5xx, then surface a HubSpotError --
    def _get(self, path: str, *, params=None) -> dict:
        url = f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                # No HTTP response at all (DNS, connection, timeout). Retry the
                # transient failure, then wrap it so a caller never sees a raw
                # requests exception.
                if attempt < self.max_retries:
                    attempt += 1
                    self._sleep(_backoff_seconds(attempt))
                    continue
                raise HubSpotConnectionError(f"request to {url} failed: {exc}", url) from exc

            if resp.status_code < 400:
                return _parse_json(resp, url)
            if resp.status_code in _RETRYABLE and attempt < self.max_retries:
                attempt += 1
                self._sleep(self._retry_after(resp, attempt))
                continue
            raise HubSpotAPIError(resp.status_code, _short(resp), url)

    @staticmethod
    def _retry_after(resp, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return _backoff_seconds(attempt)

    # -- Workflows v4 --
    def get_flow(self, flow_id: Union[str, int]) -> dict:
        """GET /automation/v4/flows/{id}: the full workflow definition."""
        return self._get(f"/automation/v4/flows/{flow_id}")

    # -- Lists (v3 with legacy fallback) --
    def get_list(self, list_id: Union[str, int], *, include_filters: bool = True) -> dict:
        """GET a list definition, trying CRM v3 then falling back to legacy v1."""
        try:
            params = {"includeFilters": "true"} if include_filters else None
            return self._get(f"/crm/v3/lists/{list_id}", params=params)
        except HubSpotAPIError as exc:
            if exc.status_code != 404:
                raise
            return self._get(f"/contacts/v1/lists/{list_id}")

    # -- Marketing emails --
    def get_email(self, email_id: Union[str, int]) -> dict:
        """GET /marketing/v3/emails/{id}. (A send action's content_id is this id.)"""
        return self._get(f"/marketing/v3/emails/{email_id}")

    def get_email_statistics(
        self,
        email_ids: Union[str, int, Iterable[Union[str, int]]],
        start: Union[str, datetime],
        end: Union[str, datetime],
    ) -> dict:
        """GET /marketing/v3/emails/statistics/list for a window.

        ``start`` / ``end`` accept ISO-8601 strings or ``datetime`` objects and
        are coerced to the ISO-8601 the endpoint requires.
        """
        if isinstance(email_ids, (str, int)):
            email_ids = [email_ids]
        params = {
            "startTimestamp": to_iso8601(start),
            "endTimestamp": to_iso8601(end),
            "emailIds": [str(e) for e in email_ids],
        }
        return self._get("/marketing/v3/emails/statistics/list", params=params)


def _parse_json(resp, url: str) -> dict:
    """Decode a success response, turning a non-JSON body into a HubSpotAPIError."""
    try:
        return resp.json()
    except ValueError as exc:  # includes requests/json JSONDecodeError
        raise HubSpotAPIError(resp.status_code, f"response was not valid JSON ({exc})", url) from exc


def _short(resp, limit: int = 300) -> str:
    try:
        body = resp.text
    except Exception:  # pragma: no cover
        body = ""
    return body[:limit] if body else getattr(resp, "reason", "")
