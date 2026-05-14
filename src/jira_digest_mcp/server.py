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
