"""Async Jira Cloud REST client: auth, pagination, story-points field discovery."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx

from .jql import build_jql
from .models import ResolvedIssue

log = logging.getLogger(__name__)

_FIELDS_BASE = [
    "summary",
    "issuetype",
    "status",
    "resolution",
    "resolutiondate",
    "assignee",
    "priority",
    "labels",
    "components",
    "parent",
]


class JiraError(Exception):
    """Base class for Jira client errors."""


class JiraAuthError(JiraError):
    """HTTP 401 or 403."""


class JiraNotFoundError(JiraError):
    """HTTP 404."""


class JiraTransportError(JiraError):
    """Network failure, timeout, 5xx, or JSON decode error."""


class JiraClient:
    def __init__(self, username: str, api_token: str, timeout: float = 30.0) -> None:
        self._auth = httpx.BasicAuth(username, api_token)
        self._client = httpx.AsyncClient(
            auth=self._auth,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        # Per-base_url cache. None means "looked, no Story Points field exists here".
        self._story_points_field: dict[str, str | None] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "JiraClient":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def search_resolved(
        self,
        base_url: str,
        project_key: str,
        since: date,
        until: date | None,
        max_results: int,
    ) -> list[ResolvedIssue]:
        base = base_url.rstrip("/")
        sp_field = await self._resolve_story_points_field(base)
        jql = build_jql(project_key, since, until)
        fields = list(_FIELDS_BASE)
        if sp_field is not None:
            fields.append(sp_field)

        results: list[ResolvedIssue] = []
        next_token: str | None = None
        url = f"{base}/rest/api/3/search/jql"

        while True:
            payload: dict[str, Any] = {
                "jql": jql,
                "fields": fields,
                "maxResults": min(100, max_results - len(results)),
            }
            if next_token is not None:
                payload["nextPageToken"] = next_token

            data = await self._post_json(url, payload)
            for raw in data.get("issues", []) or []:
                results.append(ResolvedIssue.from_raw(raw, sp_field))
                if len(results) >= max_results:
                    return results

            next_token = data.get("nextPageToken")
            if not next_token:
                break

        return results

    async def _resolve_story_points_field(self, base: str) -> str | None:
        if base in self._story_points_field:
            return self._story_points_field[base]

        url = f"{base}/rest/api/3/field"
        data = await self._get_json(url)
        # /field returns a list of {id, name, ...}
        field_id: str | None = None
        if isinstance(data, list):
            for f in data:
                if isinstance(f, dict) and isinstance(f.get("name"), str) \
                        and f["name"].strip().lower() == "story points":
                    field_id = f.get("id")
                    break

        self._story_points_field[base] = field_id
        log.info("story points field for %s: %s", base, field_id)
        return field_id

    async def _get_json(self, url: str) -> Any:
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise JiraTransportError(str(exc)) from exc
        return self._parse(resp)

    async def _post_json(self, url: str, payload: dict[str, Any]) -> Any:
        try:
            resp = await self._client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise JiraTransportError(str(exc)) from exc
        return self._parse(resp)

    @staticmethod
    def _parse(resp: httpx.Response) -> Any:
        if resp.status_code in (401, 403):
            raise JiraAuthError(f"HTTP {resp.status_code} from {resp.request.url}")
        if resp.status_code == 404:
            raise JiraNotFoundError(f"HTTP 404 from {resp.request.url}")
        if resp.status_code >= 500 or resp.status_code >= 400:
            raise JiraTransportError(
                f"HTTP {resp.status_code} from {resp.request.url}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise JiraTransportError(f"Invalid JSON from {resp.request.url}") from exc
