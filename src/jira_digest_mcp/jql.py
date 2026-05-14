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
