from jira_digest_mcp.models import ResolvedIssue, ResolvedIssuesResponse

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


def _issue(key: str, parent_key: str | None, parent_summary: str | None, points: float | None) -> ResolvedIssue:
    return ResolvedIssue(
        key=key,
        summary=key,
        issue_type="Story",
        status="Done",
        resolved_date="2026-04-15T10:00:00.000+0000",
        parent_key=parent_key,
        parent_summary=parent_summary,
        story_points=points,
    )


def test_response_empty():
    r = ResolvedIssuesResponse.from_issues([])
    assert r.total_count == 0
    assert r.issues == []
    assert r.epic_rollup == []


def test_response_rollup_groups_by_parent():
    issues = [
        _issue("ST-1", "ST-100", "Epic A", 3.0),
        _issue("ST-2", "ST-100", "Epic A", 5.0),
        _issue("ST-3", "ST-200", "Epic B", 2.0),
    ]
    r = ResolvedIssuesResponse.from_issues(issues)
    assert r.total_count == 3
    # sorted by issue_count desc
    assert r.epic_rollup[0].parent_key == "ST-100"
    assert r.epic_rollup[0].issue_count == 2
    assert r.epic_rollup[0].points_total == 8.0
    assert r.epic_rollup[0].unestimated_count == 0
    assert r.epic_rollup[1].parent_key == "ST-200"
    assert r.epic_rollup[1].issue_count == 1
    assert r.epic_rollup[1].points_total == 2.0


def test_response_rollup_tracks_unestimated_separately():
    issues = [
        _issue("ST-1", "ST-100", "Epic A", 3.0),
        _issue("ST-2", "ST-100", "Epic A", None),
        _issue("ST-3", "ST-100", "Epic A", None),
    ]
    r = ResolvedIssuesResponse.from_issues(issues)
    assert r.epic_rollup[0].points_total == 3.0
    assert r.epic_rollup[0].unestimated_count == 2
    assert r.epic_rollup[0].issue_count == 3


def test_response_rollup_orphans_grouped_under_null_parent():
    issues = [
        _issue("ST-1", "ST-100", "Epic A", 3.0),
        _issue("ST-2", None, None, 1.0),
        _issue("ST-3", None, None, None),
    ]
    r = ResolvedIssuesResponse.from_issues(issues)
    # ST-100 (1 issue) and None (2 issues): None has more, but tiebreaker pushes None last
    # actually None has 2 vs ST-100's 1, so None comes first by issue_count
    by_parent = {row.parent_key: row for row in r.epic_rollup}
    assert by_parent[None].issue_count == 2
    assert by_parent[None].points_total == 1.0
    assert by_parent[None].unestimated_count == 1
    assert by_parent["ST-100"].issue_count == 1


def test_response_rollup_orphans_sort_after_named_on_tie():
    issues = [
        _issue("ST-1", "ST-100", "Epic A", 3.0),
        _issue("ST-2", None, None, 1.0),
    ]
    r = ResolvedIssuesResponse.from_issues(issues)
    # Both have issue_count=1; named parent should come before None
    assert r.epic_rollup[0].parent_key == "ST-100"
    assert r.epic_rollup[1].parent_key is None


def test_from_raw_subtask_with_parent_task():
    raw = _raw()
    raw["fields"]["issuetype"] = {"name": "Sub-task"}
    raw["fields"]["parent"] = {"key": "ST-50", "fields": {"summary": "Parent story"}}
    r = ResolvedIssue.from_raw(raw, SP_FIELD)
    assert r.issue_type == "Sub-task"
    assert r.parent_key == "ST-50"
    assert r.parent_summary == "Parent story"
