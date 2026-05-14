# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A stdio MCP server (FastMCP) exposing a single tool, `get_resolved_issues`, that queries resolved Jira tickets across multiple Atlassian Cloud sites with one `(JIRA_USERNAME, JIRA_API_TOKEN)` credential pair. The intended consumer is an LLM producing executive summaries across a portfolio of companies, so the response shape is deliberately lean.

Python >=3.12, managed with `uv`. Entry point: `jira_digest_mcp.server:main`.

## Commands

```powershell
uv sync                       # install deps + create .venv
uv run pytest -v              # run the full test suite
uv run pytest tests/test_jql.py::test_name   # single test
uv run jira-digest-mcp        # run the stdio server (needs JIRA_USERNAME / JIRA_API_TOKEN env)
```

Pyright is configured via `pyrightconfig.json`; there is no separate lint command.

To run the server against the dev checkout from an MCP client, use `uv run --project D:\src\AI\jira-digest-mcp jira-digest-mcp` — restart the client to pick up source changes. Set `LOG_LEVEL=DEBUG` for request-level logs on stderr.

## Architecture

Four modules under `src/jira_digest_mcp/`, each with one responsibility:

- `jql.py` — **pure functions, no I/O.** Parses `since` / `until` (ISO `YYYY-MM-DD` or relative offsets like `-7d` / `-2w`) and builds the JQL string. Anything date- or query-shape-related belongs here, not in the client or server.
- `models.py` — Response-shape models and pure transforms over them. `ResolvedIssue.from_raw()` flattens the verbose Jira REST issue payload via the `_get()` nested-dict walker (use that pattern for new fields, not chained `.get()` calls). `ResolvedIssuesResponse.from_issues()` wraps a list with `total_count` and `epic_rollup` (per-`parent_key` aggregates that track `unestimated_count` separately so unpointed work doesn't get silently summed as zero). New aggregate/derived fields belong here, not in `server.py`.
- `jira_client.py` — async `httpx` client. Two important behaviors:
  1. **Per-site Story Points field discovery.** Atlassian assigns each custom field a different `customfield_XXXXX` ID per site, so the client looks up `/rest/api/3/field` once per `base_url`, matches by name (case-insensitive "story points"), and caches the result. `None` is cached too, meaning "looked, doesn't exist here" — don't re-query on misses.
  2. **Pagination via `nextPageToken`** against `/rest/api/3/search/jql` (the newer endpoint, not the deprecated `/search`). The `max_results` cap is honored both per-page (via `maxResults`) and across pages.
  HTTP errors are translated into `JiraAuthError` (401/403), `JiraNotFoundError` (404), `JiraTransportError` (5xx, network, JSON decode). The server layer turns these into user-facing `RuntimeError` messages.
- `server.py` — FastMCP wiring. Reads env vars, builds the client, registers `get_resolved_issues`, and starts stdio transport. Keep argument validation in `jql.parse_date` / `parse_until`; the tool handler should stay a thin shell.

The server is multi-tenant by design: `base_url` is a tool argument (not env), so a single running instance can serve many Atlassian sites in one conversation.

## Releases

Releases are published to PyPI via `.github/workflows/publish.yml`, which fires on any pushed tag matching `v*` and uses PyPI Trusted Publishing (no token secret in the repo). See the [Releases](README.md#releases) section of the README for the human-facing release steps.

**Always bump `version` in `pyproject.toml` using [semantic versioning](https://semver.org/) whenever you make changes that would warrant a release.** Bump in the same PR as the change, not after — that way `main` is always in a releasable state and the version reflects what's on disk.

- **MAJOR** (`X.0.0`) — breaking changes to the MCP surface: removing/renaming a tool, removing or renaming a tool argument, changing an argument's accepted type/format, removing a response field, or changing a response field's type. Anything an existing MCP client could be relying on.
- **MINOR** (`0.X.0`) — backward-compatible additions: new tool, new optional argument with a safe default, new response field, new env var, new opt-in behavior.
- **PATCH** (`0.0.X`) — bug fixes, internal refactors, doc/test/CI changes, dependency bumps that don't alter behavior.

When uncertain, prefer the higher bump. The git tag must match the `pyproject.toml` version exactly (e.g. tag `v0.2.0` ⇄ `version = "0.2.0"`) — `uv build` reads the version from `pyproject.toml`, not from the tag, so a mismatch silently publishes the wrong version.

## Conventions

- Tests are pure-Python and don't hit the network — they cover `jql` parsing and the `models.py` transforms. New `jira_client` logic should be refactorable into testable pure helpers where possible rather than mocking `httpx`.
- Errors raised from the tool handler should be plain `RuntimeError` / `ValueError` with user-facing messages — the FastMCP layer surfaces those to the MCP client. Internal exceptions (`JiraAuthError` etc.) stay inside `jira_client.py`.
- Logs go to **stderr only** — stdout is the MCP transport. Don't `print()` to stdout.
- Use `python`, not `python3` (per global instruction).
