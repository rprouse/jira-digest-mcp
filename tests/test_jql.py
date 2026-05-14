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
