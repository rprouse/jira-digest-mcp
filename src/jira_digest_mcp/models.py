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
            components=[
                name
                for c in components_raw
                if isinstance(c, dict) and isinstance((name := c.get("name")), str)
            ],
            parent_key=_get(fields, "parent", "key"),
            parent_summary=_get(fields, "parent", "fields", "summary"),
            story_points=story_points,
        )
