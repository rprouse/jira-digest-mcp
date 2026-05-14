# jira-digest-mcp

I want to build a small, focused MCP server in Python that lets me query
resolved Jira tickets across multiple Atlassian Cloud sites using a single
set of API credentials. I'll use it to generate executive summaries of
what each portfolio company's dev team has been working on.

Do not take anything in this spec as a given. Push back if you see any
inconsistencies, gaps or better approaches.

Context on how I'll use it: I'm CTO over ~20 B2B SaaS portfolio companies,
each with their own Atlassian Cloud site. I use the same email + API token
across all of them. I'll drive this from a Claude skill that knows the
mapping of company name -> base URL -> project key, so the MCP tools must
accept site/project as parameters rather than reading them from env.

The PyPI package name is `jira-digest-mcp`.
The Python module name is `jira_digest_mcp`.
The MCP tool name is `get_resolved_issues`.
The console script entry point should be `jira-digest-mcp`.

## Functional requirements

Expose exactly ONE MCP tool to start — keep the surface minimal:

  get_resolved_issues(
      base_url: str,        # e.g. "https://stabletrack.atlassian.net"
      project_key: str,     # e.g. "ST"
      since: str,           # ISO date "2026-04-01" or relative "-7d", "-30d"
      until: str | None,    # optional, defaults to now
      max_results: int = 100,
  ) -> list[dict]

Behaviour:
- Build a JQL query: project = {project_key} AND resolved >= {since}
  AND resolved <= {until} ORDER BY resolved DESC
- Use Jira Cloud REST API v3 /rest/api/3/search/jql endpoint
  (the older /search endpoint is deprecated)
- Handle pagination — fetch all pages up to max_results
- Authenticate with HTTP Basic Auth using JIRA_USERNAME + JIRA_API_TOKEN
  from environment variables
- Return a list of lean dicts shaped for executive summaries, NOT the
  raw Jira response. Each dict should contain:
    key, summary, issue_type, status, resolution, resolved_date,
    assignee_display_name, priority, labels, components,
    parent_key (if subtask or has epic), parent_summary,
    story_points (if present)
- Strip out everything else. No avatars, no self URLs, no expand metadata,
  no ADF descriptions — descriptions are too noisy for summary work and
  will blow the context window across 20 companies.

## Non-functional requirements

- Python 3.12, use uv for dependency management
- FastMCP framework (the modern `mcp` Python SDK with the FastMCP API)
- httpx for HTTP, async throughout
- Stdio transport for now; we can add streamable-http later
- Pydantic models for the response shape so it's typed and self-documenting
- Read JIRA_USERNAME and JIRA_API_TOKEN from environment. Fail clearly at
  startup if either is missing.
- Sensible error handling: surface Jira 401/403/404 as readable error
  messages back through MCP, not stack traces. Wrap network errors.
- Log to stderr (so it doesn't break stdio MCP), at INFO level by default,
  DEBUG if LOG_LEVEL=DEBUG is set.

## Project layout

  jira-portfolio-mcp/
    pyproject.toml          # uv-managed, declares mcp, httpx, pydantic
    README.md               # how to run it, env vars, example MCP config
    src/
      jira_portfolio_mcp/
        __init__.py
        server.py           # FastMCP entry point, tool registration
        jira_client.py      # async httpx client, auth, pagination
        models.py           # Pydantic models for the slimmed response
        jql.py              # JQL date parsing (handle "-7d", ISO dates)
    tests/
      test_jql.py           # unit test the date parser
      test_models.py        # unit test the response shaping

Don't write integration tests against real Jira — I'll smoke-test it
against one of my live sites.

## What I want you to do

1. Start by asking me anything that's genuinely ambiguous. Don't ask
   about colour-of-the-bikeshed stuff.
2. Scaffold the project with uv (uv init, then add deps).
3. Write the code in small, reviewable commits — I want to read each step.
4. After the implementation works locally with `uv run jira-portfolio-mcp`,
   write me the Claude Desktop / Claude Code MCP config block I need to
   add to use it.
5. Don't add features I didn't ask for. If you think something is missing,
   tell me and let me decide. In particular: no extra tools, no
   write/create/comment functionality, no Confluence, no caching layer,
   no admin endpoints. Just resolved-issues querying.

## Things I might add later (do NOT build now, but design with these in mind)

- A second tool that returns in-progress / unresolved work for "what is
  the team doing right now" queries
- A tool that returns sprint information
- Optional Streamable HTTP transport so I can run it as a Docker container
  on Unraid and hit it from multiple Claude clients
