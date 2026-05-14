# jira-digest-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server exposing one tool, `get_resolved_issues`, that queries resolved Jira tickets across many Atlassian Cloud sites and returns a lean response shaped for executive summarization.

**Architecture:** Four-module layout under `src/jira_digest_mcp/`: pure-functions `jql.py` (date parsing + JQL builder), Pydantic-based `models.py` (response shaping), async `jira_client.py` (httpx + Basic auth + token pagination + per-site story-points field discovery), FastMCP entry point `server.py` (stdio transport, env-var validation, error translation).

**Tech Stack:** Python 3.12, uv, FastMCP (`mcp` SDK), httpx (async), pydantic v2, pytest.

**Companion spec:** `docs/superpowers/specs/2026-05-13-jira-digest-mcp-design.md`

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv-managed package metadata, deps, console script entry point |
| `README.md` | Install, env vars, MCP client config block, usage example |
| `src/jira_digest_mcp/__init__.py` | Package marker; re-export `main` for convenience |
| `src/jira_digest_mcp/jql.py` | `parse_date`, `parse_until`, `build_jql` — pure, no I/O |
| `src/jira_digest_mcp/models.py` | `ResolvedIssue` Pydantic model + `from_raw` shaping |
| `src/jira_digest_mcp/jira_client.py` | `JiraClient` (async), exceptions, pagination, story-points field cache |
| `src/jira_digest_mcp/server.py` | FastMCP server, tool registration, `main()` entry point |
| `tests/test_jql.py` | Unit tests for date parsing + JQL building |
| `tests/test_models.py` | Unit tests for `ResolvedIssue.from_raw` shape |

---

## Task 1: Project scaffold with uv

**Files:**
- Create: `pyproject.toml`
- Create: `src/jira_digest_mcp/__init__.py`
- Create: `tests/__init__.py` (empty)
- Create: `.python-version` (uv writes this)
- Create: `uv.lock` (uv writes this)

- [ ] **Step 1: Initialize the package**

From the worktree root (the directory containing `docs/`), run:

```
uv init --package --name jira-digest-mcp --python 3.12
```

This generates `pyproject.toml`, `src/jira_digest_mcp/__init__.py`, `.python-version`. It may also generate a stub `README.md` and a `hello.py`-style file under `src/jira_digest_mcp/` — delete any generated example file (e.g. `src/jira_digest_mcp/__init__.py` will likely contain a `def hello(): ...`; leave the file but empty it for now, see Step 3).

- [ ] **Step 2: Add runtime and dev dependencies**

Run:

```
uv add "mcp[cli]" httpx pydantic
uv add --dev pytest
```

This populates `[project.dependencies]` and `[dependency-groups].dev` in `pyproject.toml`, and writes `uv.lock`.

- [ ] **Step 3: Set the package entry point and clean the init module**

Edit `pyproject.toml` to add the console script section (place it next to `[project]`, not inside it):

```toml
[project.scripts]
jira-digest-mcp = "jira_digest_mcp.server:main"
```

Also confirm the `[project]` block includes:

```toml
requires-python = ">=3.12"
```

Replace the contents of `src/jira_digest_mcp/__init__.py` with:

```python
"""jira-digest-mcp: MCP server for portfolio Jira queries."""
```

- [ ] **Step 4: Create the tests package marker**

Create `tests/__init__.py` as an empty file.

- [ ] **Step 5: Verify the scaffold builds**

Run:

```
uv sync
uv run python -c "import jira_digest_mcp; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 6: Commit**

```
git add pyproject.toml uv.lock .python-version src/ tests/
git commit -m "chore: scaffold jira-digest-mcp package with uv"
```

---

## Task 2: JQL date parser — TDD

**Files:**
- Create: `tests/test_jql.py`
- Create: `src/jira_digest_mcp/jql.py`

- [ ] **Step 1: Write the failing test for ISO date parsing**

Create `tests/test_jql.py`:

```python
from datetime import date, timedelta

import pytest

from jira_digest_mcp.jql import build_jql, parse_date, parse_until


def test_parse_date_iso():
    assert parse_date("2026-04-01", label="since") == date(2026, 4, 1)


def test_parse_date_relative_days():
    today = date.today()
    assert parse_date("-7d", label="since") == today - timedelta(days=7)
    assert parse_date("-30d", label="since") == today - timedelta(days=30)


def test_parse_date_relative_weeks():
    today = date.today()
    assert parse_date("-2w", label="since") == today - timedelta(weeks=2)


@pytest.mark.parametrize("bad", ["", "abc", "-7", "7d", "-7x", "2026/04/01", "-0d"])
def test_parse_date_rejects_invalid(bad):
    with pytest.raises(ValueError, match="since"):
        parse_date(bad, label="since")


def test_parse_date_uses_label_in_error():
    with pytest.raises(ValueError, match="until"):
        parse_date("nope", label="until")


def test_parse_until_none_passthrough():
    assert parse_until(None) is None


def test_parse_until_iso():
    assert parse_until("2026-04-30") == date(2026, 4, 30)


def test_build_jql_with_until():
    j = build_jql("ST", date(2026, 4, 1), date(2026, 4, 30))
    assert j == (
        'project = "ST" AND resolved >= "2026-04-01" '
        'AND resolved <= "2026-04-30" ORDER BY resolved DESC'
    )


def test_build_jql_without_until():
    j = build_jql("ST", date(2026, 4, 1), None)
    assert j == (
        'project = "ST" AND resolved >= "2026-04-01" ORDER BY resolved DESC'
    )


def test_build_jql_quotes_project_key_with_special_chars():
    j = build_jql('weird"key', date(2026, 4, 1), None)
    assert 'project = "weird\\"key"' in j
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```
uv run pytest tests/test_jql.py -v
```

Expected: collection error or all tests FAIL (no `jql` module yet).

- [ ] **Step 3: Implement `jql.py`**

Create `src/jira_digest_mcp/jql.py`:

```python
"""JQL helpers: date parsing and query building. Pure functions, no I/O."""

from __future__ import annotations

import re
from datetime import date, timedelta

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RELATIVE_RE = re.compile(r"^-(?P<n>[1-9]\d*)(?P<unit>[dw])$")


def parse_date(value: str, *, label: str) -> date:
    """Parse an ISO date (YYYY-MM-DD) or a relative offset like -7d or -2w.

    `label` is woven into error messages so the caller can tell which argument
    was bad (e.g. "since" vs "until").
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string, got {value!r}")

    if _ISO_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{label} is not a valid ISO date: {value!r}") from exc

    m = _RELATIVE_RE.match(value)
    if m:
        n = int(m.group("n"))
        unit = m.group("unit")
        delta = timedelta(days=n) if unit == "d" else timedelta(weeks=n)
        return date.today() - delta

    raise ValueError(
        f"{label} must be ISO YYYY-MM-DD or relative like -7d/-2w, got {value!r}"
    )


def parse_until(value: str | None) -> date | None:
    """Like parse_date but `None` passes through (caller omits the upper bound)."""
    if value is None:
        return None
    return parse_date(value, label="until")


def build_jql(project_key: str, since: date, until: date | None) -> str:
    """Build the JQL for resolved-issue search, ordered newest first."""
    pk = project_key.replace('"', '\\"')
    parts = [f'project = "{pk}"', f'resolved >= "{since.isoformat()}"']
    if until is not None:
        parts.append(f'resolved <= "{until.isoformat()}"')
    return " AND ".join(parts) + " ORDER BY resolved DESC"
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```
uv run pytest tests/test_jql.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```
git add src/jira_digest_mcp/jql.py tests/test_jql.py
git commit -m "feat(jql): add date parser and JQL builder with unit tests"
```

---

## Task 3: ResolvedIssue model — TDD

**Files:**
- Create: `tests/test_models.py`
- Create: `src/jira_digest_mcp/models.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_models.py`:

```python
from jira_digest_mcp.models import ResolvedIssue

SP_FIELD = "customfield_10016"


def _raw(**overrides):
    base = {
        "key": "ST-123",
        "fields": {
            "summary": "Do the thing",
            "issuetype": {"name": "Story"},
            "status": {"name": "Done"},
            "resolution": {"name": "Done"},
            "resolutiondate": "2026-04-15T10:00:00.000+0000",
            "assignee": {"displayName": "Alice"},
            "priority": {"name": "Medium"},
            "labels": ["backend", "perf"],
            "components": [{"name": "API"}, {"name": "DB"}],
            "parent": {"key": "ST-100", "fields": {"summary": "Epic: Q2 perf"}},
            SP_FIELD: 3.0,
        },
    }
    base["fields"].update(overrides.pop("fields_override", {}))
    base.update(overrides)
    return base


def test_from_raw_full_payload():
    r = ResolvedIssue.from_raw(_raw(), SP_FIELD)
    assert r.key == "ST-123"
    assert r.summary == "Do the thing"
    assert r.issue_type == "Story"
    assert r.status == "Done"
    assert r.resolution == "Done"
    assert r.resolved_date == "2026-04-15T10:00:00.000+0000"
    assert r.assignee_display_name == "Alice"
    assert r.priority == "Medium"
    assert r.labels == ["backend", "perf"]
    assert r.components == ["API", "DB"]
    assert r.parent_key == "ST-100"
    assert r.parent_summary == "Epic: Q2 perf"
    assert r.story_points == 3.0


def test_from_raw_no_parent():
    raw = _raw(fields_override={"parent": None})
    raw["fields"].pop("parent")
    r = ResolvedIssue.from_raw(raw, SP_FIELD)
    assert r.parent_key is None
    assert r.parent_summary is None


def test_from_raw_no_assignee_no_priority_no_resolution():
    raw = _raw()
    raw["fields"]["assignee"] = None
    raw["fields"]["priority"] = None
    raw["fields"]["resolution"] = None
    r = ResolvedIssue.from_raw(raw, SP_FIELD)
    assert r.assignee_display_name is None
    assert r.priority is None
    assert r.resolution is None


def test_from_raw_story_points_absent():
    raw = _raw()
    raw["fields"].pop(SP_FIELD)
    r = ResolvedIssue.from_raw(raw, SP_FIELD)
    assert r.story_points is None


def test_from_raw_story_points_field_unresolved_on_site():
    r = ResolvedIssue.from_raw(_raw(), None)
    assert r.story_points is None


def test_from_raw_handles_missing_nested_fields():
    sparse = {"key": "ST-1", "fields": {"summary": "x", "issuetype": {"name": "Task"},
                                         "status": {"name": "Done"},
                                         "resolutiondate": "2026-01-01T00:00:00.000+0000",
                                         "labels": [], "components": []}}
    r = ResolvedIssue.from_raw(sparse, SP_FIELD)
    assert r.key == "ST-1"
    assert r.resolution is None
    assert r.assignee_display_name is None
    assert r.priority is None
    assert r.parent_key is None
    assert r.parent_summary is None
    assert r.story_points is None
    assert r.labels == []
    assert r.components == []


def test_from_raw_subtask_with_parent_task():
    raw = _raw()
    raw["fields"]["issuetype"] = {"name": "Sub-task"}
    raw["fields"]["parent"] = {"key": "ST-50", "fields": {"summary": "Parent story"}}
    r = ResolvedIssue.from_raw(raw, SP_FIELD)
    assert r.issue_type == "Sub-task"
    assert r.parent_key == "ST-50"
    assert r.parent_summary == "Parent story"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```
uv run pytest tests/test_models.py -v
```

Expected: collection error or all tests FAIL.

- [ ] **Step 3: Implement `models.py`**

Create `src/jira_digest_mcp/models.py`:

```python
"""Pydantic model for the lean response shape returned by get_resolved_issues."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def _get(d: dict | None, *path: str) -> Any:
    """Safely walk a nested dict, returning None at the first missing key."""
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


class ResolvedIssue(BaseModel):
    key: str
    summary: str
    issue_type: str
    status: str
    resolution: str | None = None
    resolved_date: str
    assignee_display_name: str | None = None
    priority: str | None = None
    labels: list[str] = []
    components: list[str] = []
    parent_key: str | None = None
    parent_summary: str | None = None
    story_points: float | None = None

    @classmethod
    def from_raw(cls, raw: dict, story_points_field_id: str | None) -> "ResolvedIssue":
        fields = raw.get("fields") or {}
        components_raw = fields.get("components") or []
        story_points = None
        if story_points_field_id is not None:
            value = fields.get(story_points_field_id)
            if isinstance(value, (int, float)):
                story_points = float(value)
        return cls(
            key=raw["key"],
            summary=fields.get("summary") or "",
            issue_type=_get(fields, "issuetype", "name") or "",
            status=_get(fields, "status", "name") or "",
            resolution=_get(fields, "resolution", "name"),
            resolved_date=fields.get("resolutiondate") or "",
            assignee_display_name=_get(fields, "assignee", "displayName"),
            priority=_get(fields, "priority", "name"),
            labels=list(fields.get("labels") or []),
            components=[c.get("name") for c in components_raw if isinstance(c, dict) and c.get("name")],
            parent_key=_get(fields, "parent", "key"),
            parent_summary=_get(fields, "parent", "fields", "summary"),
            story_points=story_points,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```
uv run pytest tests/test_models.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```
git add src/jira_digest_mcp/models.py tests/test_models.py
git commit -m "feat(models): add ResolvedIssue with defensive from_raw shaping"
```

---

## Task 4: JiraClient — async httpx wrapper

No unit tests in this task (per spec: only `test_jql.py` and `test_models.py`). The client will be smoke-tested manually against a real site.

**Files:**
- Create: `src/jira_digest_mcp/jira_client.py`

- [ ] **Step 1: Implement `jira_client.py`**

Create `src/jira_digest_mcp/jira_client.py`:

```python
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

    async def __aexit__(self, *exc: Any) -> None:
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
```

- [ ] **Step 2: Smoke-import to catch syntax / import errors**

Run:

```
uv run python -c "from jira_digest_mcp.jira_client import JiraClient, JiraAuthError, JiraNotFoundError, JiraTransportError; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 3: Commit**

```
git add src/jira_digest_mcp/jira_client.py
git commit -m "feat(client): async Jira client with token pagination and SP field discovery"
```

---

## Task 5: FastMCP server entry point

**Files:**
- Create: `src/jira_digest_mcp/server.py`

- [ ] **Step 1: Implement `server.py`**

Create `src/jira_digest_mcp/server.py`:

```python
"""FastMCP server exposing get_resolved_issues over stdio."""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .jira_client import (
    JiraAuthError,
    JiraClient,
    JiraNotFoundError,
    JiraTransportError,
)
from .jql import parse_date, parse_until

log = logging.getLogger("jira_digest_mcp")


def _configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"error: environment variable {name} is required", file=sys.stderr)
        sys.exit(2)
    return value


def build_server(client: JiraClient) -> FastMCP:
    mcp = FastMCP("jira-digest-mcp")

    @mcp.tool()
    async def get_resolved_issues(
        base_url: str,
        project_key: str,
        since: str,
        until: str | None = None,
        max_results: int = 100,
    ) -> list[dict]:
        """Return resolved Jira issues for a project, shaped for executive summaries.

        Args:
            base_url: e.g. "https://example.atlassian.net"
            project_key: e.g. "ST"
            since: ISO date "YYYY-MM-DD" or relative offset like "-7d", "-2w"
            until: optional, same forms as `since`; omitted = up to now
            max_results: hard cap on returned issues (default 100)
        """
        try:
            since_date = parse_date(since, label="since")
            until_date = parse_until(until)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        try:
            issues = await client.search_resolved(
                base_url=base_url,
                project_key=project_key,
                since=since_date,
                until=until_date,
                max_results=max_results,
            )
        except JiraAuthError as exc:
            log.debug("auth error", exc_info=True)
            raise RuntimeError(
                f"Jira authentication failed for {base_url} (project {project_key}). "
                "Check JIRA_USERNAME and JIRA_API_TOKEN."
            ) from exc
        except JiraNotFoundError as exc:
            log.debug("not found", exc_info=True)
            raise RuntimeError(
                f"Jira returned 404 for {base_url} / project {project_key}. "
                "Check the base_url and project_key."
            ) from exc
        except JiraTransportError as exc:
            log.debug("transport error", exc_info=True)
            raise RuntimeError(f"Jira request to {base_url} failed: {exc}") from exc

        return [i.model_dump() for i in issues]

    return mcp


def main() -> None:
    _configure_logging()
    username = _require_env("JIRA_USERNAME")
    token = _require_env("JIRA_API_TOKEN")

    client = JiraClient(username=username, api_token=token)
    server = build_server(client)
    try:
        server.run()  # stdio transport by default
    finally:
        # Best-effort close; the asyncio loop has already finished here.
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Re-export `main` from the package**

Replace `src/jira_digest_mcp/__init__.py` with:

```python
"""jira-digest-mcp: MCP server for portfolio Jira queries."""

from .server import main

__all__ = ["main"]
```

- [ ] **Step 3: Verify the entry point resolves**

Run:

```
uv sync
uv run jira-digest-mcp --help 2>&1 | head -n 20 || true
```

The server doesn't take `--help` (FastMCP just starts the stdio loop), so this is a smoke check that the entry point at least *exists*. If `uv run jira-digest-mcp` is found and starts a process (it will hang waiting for stdio JSON-RPC), Ctrl-C and move on. To verify without hanging, run instead:

```
uv run python -c "from jira_digest_mcp.server import build_server, main; print('ok')"
```

Expected output: `ok`.

- [ ] **Step 4: Verify env-var failure is clean**

Run (in a shell that does NOT have `JIRA_USERNAME` / `JIRA_API_TOKEN` set):

```
uv run python -c "import os; os.environ.pop('JIRA_USERNAME', None); os.environ.pop('JIRA_API_TOKEN', None); from jira_digest_mcp.server import main; main()"
```

Expected: exits with code 2 and prints `error: environment variable JIRA_USERNAME is required` (or `JIRA_API_TOKEN` if only that one is unset) to stderr.

- [ ] **Step 5: Run the full test suite**

Run:

```
uv run pytest -v
```

Expected: all `test_jql.py` and `test_models.py` tests PASS.

- [ ] **Step 6: Commit**

```
git add src/jira_digest_mcp/server.py src/jira_digest_mcp/__init__.py
git commit -m "feat(server): FastMCP stdio entry point with env validation and error translation"
```

---

## Task 6: README with install + MCP client config

**Files:**
- Create or replace: `README.md`

- [ ] **Step 1: Write the README**

Create `README.md`:

````markdown
# jira-digest-mcp

A small MCP server that exposes one tool, `get_resolved_issues`, for querying
resolved Jira tickets across multiple Atlassian Cloud sites using a single
`(email, API token)` credential pair. Designed for executive summarization of
dev activity across a portfolio of companies.

## Install

```
uv tool install jira-digest-mcp
```

Or, from a checkout:

```
uv sync
uv run jira-digest-mcp
```

## Required environment variables

- `JIRA_USERNAME` — the email address tied to your Atlassian API token.
- `JIRA_API_TOKEN` — an API token from <https://id.atlassian.com/manage-profile/security/api-tokens>.

Optional:

- `LOG_LEVEL` — `INFO` (default) or `DEBUG`. Logs go to stderr.

## MCP tool

### `get_resolved_issues`

```
get_resolved_issues(
    base_url: str,        # e.g. "https://example.atlassian.net"
    project_key: str,     # e.g. "ST"
    since: str,           # "2026-04-01" or "-7d", "-2w"
    until: str | None,    # optional, same forms
    max_results: int = 100,
) -> list[dict]
```

Each returned dict contains: `key`, `summary`, `issue_type`, `status`,
`resolution`, `resolved_date`, `assignee_display_name`, `priority`, `labels`,
`components`, `parent_key`, `parent_summary`, `story_points`.

`story_points` is auto-discovered per site by matching the field name
"Story Points" (case-insensitive). If the field has been renamed on a given
site, story points will be `null` for that site.

## Claude Desktop / Claude Code config

Add to your MCP client config:

```json
{
  "mcpServers": {
    "jira-digest": {
      "command": "uv",
      "args": ["tool", "run", "jira-digest-mcp"],
      "env": {
        "JIRA_USERNAME": "you@example.com",
        "JIRA_API_TOKEN": "..."
      }
    }
  }
}
```

If you installed from a checkout, point `command` at `uv` and `args` at
`["run", "--directory", "/abs/path/to/jira-digest-mcp", "jira-digest-mcp"]`.

## Development

```
uv sync
uv run pytest -v
```
````

- [ ] **Step 2: Commit**

```
git add README.md
git commit -m "docs: README with install, env vars, and MCP client config"
```

---

## Task 7: Final verification

- [ ] **Step 1: Full test run**

```
uv run pytest -v
```

Expected: all tests PASS, no warnings about deprecated APIs from our code.

- [ ] **Step 2: Import-graph smoke check**

```
uv run python -c "from jira_digest_mcp import main; from jira_digest_mcp.server import build_server; from jira_digest_mcp.jira_client import JiraClient; from jira_digest_mcp.models import ResolvedIssue; from jira_digest_mcp.jql import build_jql, parse_date, parse_until; print('all imports ok')"
```

Expected output: `all imports ok`.

- [ ] **Step 3: Confirm git state is clean**

```
git status
```

Expected: working tree clean, on branch `worktree-scaffold-design-spec`, with commits for: scaffold, jql, models, client, server, README (six commits beyond the spec commit).

- [ ] **Step 4: Hand back to user for smoke testing**

Tell the user:
- The implementation is done on branch `worktree-scaffold-design-spec` in the worktree at `.claude/worktrees/scaffold-design-spec`.
- They need to set `JIRA_USERNAME` and `JIRA_API_TOKEN` and run `uv run jira-digest-mcp` against one of their live sites via an MCP client to smoke-test.
- Offer to merge the worktree branch back to `main` once they've confirmed it works, per `superpowers:finishing-a-development-branch`.
