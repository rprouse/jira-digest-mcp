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

If you installed from a checkout, see the [Development](#development) section
below for the equivalent MCP client config that points at your local source.

## Development

The source lives at `D:\src\AI\jira-digest-mcp`.

### Setup

From the repo root:

```
uv sync
```

### Tests

```
uv run pytest -v
```

### Running the server from source

To start the stdio server directly (it will hang waiting for JSON-RPC on stdin,
which is correct — interrupt with Ctrl-C when done):

```powershell
$env:JIRA_USERNAME = "you@example.com"
$env:JIRA_API_TOKEN = "..."
uv run --directory D:\src\AI\jira-digest-mcp jira-digest-mcp
```

Set `$env:LOG_LEVEL = "DEBUG"` to see request-level logs on stderr.

### Pointing Claude Desktop / Claude Code at the dev checkout

Use this MCP client config block to run the server from source instead of an
installed copy:

```json
{
  "mcpServers": {
    "jira-digest-dev": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "D:\\src\\AI\\jira-digest-mcp",
        "jira-digest-mcp"
      ],
      "env": {
        "JIRA_USERNAME": "you@example.com",
        "JIRA_API_TOKEN": "...",
        "LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

After editing a source file, restart the MCP client (or use its "reload MCP
servers" action) to pick up the change.
