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
