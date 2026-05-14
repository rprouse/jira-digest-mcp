# jira-digest-mcp — design

## Purpose

A small, focused MCP server in Python that exposes one tool, `get_resolved_issues`, for querying resolved Jira tickets across multiple Atlassian Cloud sites with a single shared `(email, API token)` credential pair. The caller (a Claude skill) supplies the site `base_url` and `project_key` on every invocation; the server holds no per-company configuration.

The downstream use case is executive summarization of dev activity across ~20 portfolio companies, so the tool returns a **lean, shaped response** rather than raw Jira JSON.

## Scope

**In scope (v1):**

- A single MCP tool `get_resolved_issues(base_url, project_key, since, until=None, max_results=100)`.
- Stdio transport.
- HTTP Basic auth via `JIRA_USERNAME` + `JIRA_API_TOKEN` env vars.
- Pagination over Jira's `/rest/api/3/search/jql` endpoint up to `max_results`.
- Per-site auto-discovery of the "Story Points" custom field ID, cached in-memory.
- Clean error surfacing for 401/403/404 and transport failures.

**Out of scope (v1) — designed-for but not built:**

- A second tool for in-progress / unresolved work.
- Sprint information.
- Streamable HTTP transport (Docker on Unraid).

**Explicitly excluded (do not build):**

- Any write operation (create / comment / transition).
- Confluence anything.
- Persistent caching layer.
- Admin endpoints.
- Multiple tools in v1.

## Naming

| Thing | Value |
|---|---|
| PyPI package | `jira-digest-mcp` |
| Python module | `jira_digest_mcp` |
| Console entry point | `jira-digest-mcp` |
| MCP tool name | `get_resolved_issues` |

(The initial spec had `jira-portfolio-mcp` in some sections; that was a stale name and is superseded by the above.)

## Non-functional requirements

- Python 3.12.
- `uv` for project + dependency management.
- FastMCP API from the official `mcp` Python SDK.
- `httpx` for HTTP, async throughout.
- `pydantic` for the response shape.
- Logging to **stderr** only (stdio transport reserves stdout for JSON-RPC framing). INFO by default, DEBUG when `LOG_LEVEL=DEBUG`.
- Startup fails fast with a clear stderr message if `JIRA_USERNAME` or `JIRA_API_TOKEN` is missing.

## Architecture

Four modules under `src/jira_digest_mcp/`:

### `server.py`

FastMCP entry point. Responsibilities:

- Validate `JIRA_USERNAME` and `JIRA_API_TOKEN` at startup; exit with a clear stderr message if missing.
- Configure stderr logging at the level from `LOG_LEVEL` (default INFO).
- Construct a single shared `JiraClient` instance.
- Register the `get_resolved_issues` tool.
- Translate the three `JiraClient` exception types into MCP tool errors that echo `base_url` and `project_key` so per-site failures are identifiable when the caller fans out across companies.
- Run FastMCP over stdio.
- Expose `main()` as the console-script entry point.

### `jira_client.py`

Async wrapper around `httpx.AsyncClient`. Responsibilities:

- Hold the shared `(username, api_token)` and a long-lived `AsyncClient`.
- `async search_resolved(base_url, project_key, since, until, max_results) -> list[ResolvedIssue]`:
  - Resolves the story-points field ID for `base_url` (lazy, cached).
  - Builds the JQL via `jql.build_jql(...)`.
  - POSTs to `{base_url}/rest/api/3/search/jql` with explicit `fields` list and the dynamically resolved story-points field ID.
  - Iterates on `nextPageToken` until exhausted or `max_results` reached.
  - Shapes each raw issue via `ResolvedIssue.from_raw(raw, story_points_field_id)`.
- `async _resolve_story_points_field(base_url) -> str | None`:
  - On first hit per `base_url`, GET `/rest/api/3/field`, find the field whose `name` matches `"Story Points"` case-insensitively, cache the `id`.
  - On subsequent hits, return the cached value.
  - If no matching field exists on that site, cache `None` and return `None` (story points will be omitted from the response shape).
- Translate transport failures into a small typed exception set:
  - `JiraAuthError` for HTTP 401 / 403.
  - `JiraNotFoundError` for HTTP 404 (likely a wrong `base_url` or `project_key`).
  - `JiraTransportError` for network errors, timeouts, 5xx, JSON decode failures.

The cache is plain `dict[str, str | None]` keyed by `base_url`, in-memory, per-process. No TTL — Jira field IDs are stable; restarting the server flushes the cache.

### `jql.py`

Pure functions, no I/O. The caller passes naked dates (no timezone) — JQL interprets them in the target site's configured timezone, which is what we want (each portfolio company's workday).

- `parse_date(value: str, *, label: str) -> date`:
  - Accepts ISO `YYYY-MM-DD`.
  - Accepts relative forms `-Nd` (N days back from today, UTC) and `-Nw` (N weeks back).
  - Raises `ValueError` with a descriptive message on bad input; `label` is woven in for clearer errors (`"since"` vs `"until"`).
- `parse_until(value: str | None) -> date | None`: thin wrapper that returns `None` when the input is `None` (defaulting to "now" in JQL terms is handled by omitting the upper bound).
- `build_jql(project_key: str, since: date, until: date | None) -> str`:
  - Returns `project = "{project_key}" AND resolved >= "{since}" [AND resolved <= "{until}"] ORDER BY resolved DESC`.
  - Quotes `project_key` to tolerate keys that include unusual characters.

### `models.py`

Pydantic v2 models.

`ResolvedIssue` (the public shape, what each list element looks like after `.model_dump()`):

| Field | Type | Source |
|---|---|---|
| `key` | `str` | `issue.key` |
| `summary` | `str` | `fields.summary` |
| `issue_type` | `str` | `fields.issuetype.name` |
| `status` | `str` | `fields.status.name` |
| `resolution` | `str \| None` | `fields.resolution.name` if present |
| `resolved_date` | `str` | `fields.resolutiondate` (ISO 8601 from Jira) |
| `assignee_display_name` | `str \| None` | `fields.assignee.displayName` if present |
| `priority` | `str \| None` | `fields.priority.name` if present |
| `labels` | `list[str]` | `fields.labels` |
| `components` | `list[str]` | `[c.name for c in fields.components]` |
| `parent_key` | `str \| None` | `fields.parent.key` |
| `parent_summary` | `str \| None` | `fields.parent.fields.summary` |
| `story_points` | `float \| None` | `fields[story_points_field_id]` if discovered |

A classmethod `ResolvedIssue.from_raw(raw: dict, story_points_field_id: str | None) -> ResolvedIssue` does the flattening. This keeps shaping logic testable without the network.

We do **not** model raw Jira responses as Pydantic types — Jira's payload is too variable across sites to validate strictly. `from_raw` uses defensive `.get()` traversal so missing nested fields produce `None`, not exceptions.

## Data flow for one tool invocation

1. Tool handler in `server.py` receives `(base_url, project_key, since, until, max_results)`.
2. `jql.parse_date(since, label="since")` → `date`; `jql.parse_until(until)` → `date | None`. Bad inputs raise `ValueError` → MCP error.
3. `JiraClient.search_resolved(...)`:
   a. Ensures story-points field ID is resolved for `base_url` (≤1 extra HTTP call per site per process).
   b. Builds the JQL.
   c. Loops POST `/rest/api/3/search/jql`, accumulating shaped `ResolvedIssue` instances, until `nextPageToken` is absent or `len(results) >= max_results`.
   d. Truncates to exactly `max_results` if the final page overshoots.
4. Handler returns `[r.model_dump() for r in results]` — a `list[dict]`.

## Error handling

The three exception types in `jira_client.py` are caught in `server.py` and turned into clean MCP tool errors. Message format:

- Auth: `"Jira authentication failed for {base_url} (project {project_key}). Check JIRA_USERNAME and JIRA_API_TOKEN."`
- Not found: `"Jira returned 404 for {base_url} / project {project_key}. Check the base_url and project_key."`
- Transport: `"Jira request to {base_url} failed: {underlying message}."`

Validation errors from `jql.py` (bad date input) bubble up as ordinary MCP tool errors describing which argument was malformed.

No stack traces escape to the MCP client. Full tracebacks go to stderr at DEBUG.

## Testing

Two unit-test files; no integration tests against real Jira (smoke-tested manually).

- `tests/test_jql.py`:
  - ISO date parses correctly.
  - `-7d`, `-30d`, `-2w` all produce expected `date` values relative to today.
  - Invalid input (`""`, `"abc"`, `"-7"`, `"7d"`, `"-7x"`) raises `ValueError` with a message naming the argument.
  - `build_jql` produces expected strings with and without `until`.
  - Project keys with quotes/spaces are handled (defensive).
- `tests/test_models.py`:
  - Canonical raw payloads → expected `ResolvedIssue` shape: a story with a parent epic, a subtask with a parent task, an issue with no parent, an issue with story points present, an issue with story points absent, an issue with missing optional fields (no assignee / no priority / no resolution).
  - `from_raw` never raises on partial payloads.

## Packaging / tooling

- `uv init --package` layout: source under `src/jira_digest_mcp/`.
- `pyproject.toml`:
  - `requires-python = ">=3.12"`.
  - Runtime deps: `mcp`, `httpx`, `pydantic`.
  - Dev deps: `pytest`.
  - `[project.scripts] jira-digest-mcp = "jira_digest_mcp.server:main"`.
- `README.md` covers: install via `uv`, required env vars, example MCP client config block for Claude Desktop / Claude Code, one usage example.

## Project layout

```
jira-digest-mcp/
  pyproject.toml
  README.md
  src/
    jira_digest_mcp/
      __init__.py
      server.py
      jira_client.py
      models.py
      jql.py
  tests/
    test_jql.py
    test_models.py
  docs/
    initial_spec.md
    superpowers/
      specs/
        2026-05-13-jira-digest-mcp-design.md   # this file
```

## Open assumptions worth surfacing during implementation

- **Story-points field name.** Auto-discovery matches `name == "Story Points"` case-insensitively. If a site has renamed the field, story points will be silently omitted for that site (cache stores `None`). Document this in the README so the user knows the failure mode.
- **Epic links on classic projects.** We read `fields.parent` only. On older classic projects that still use a separate "Epic Link" custom field, `parent_key` / `parent_summary` may be empty for stories whose parent is an epic. Accepted for v1.
- **`nextPageToken` semantics.** The new `/search/jql` endpoint is token-paginated; the response shape is `{ issues: [...], nextPageToken: "..."? }`. We loop until `nextPageToken` is absent.
- **`fields` parameter.** The new endpoint requires an explicit `fields` list. We send: `["summary", "issuetype", "status", "resolution", "resolutiondate", "assignee", "priority", "labels", "components", "parent", <story_points_field_id_if_resolved>]`.
- **Timeouts.** `httpx.AsyncClient` configured with a sensible total timeout (30s) so a hung site doesn't wedge a multi-company sweep.
