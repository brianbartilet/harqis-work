from workflows.second_brain.collectors.jira import normalize_jira_issues


def test__normalize_jira_issues_builds_portable_advisory_items():
    items = normalize_jira_issues(
        {
            "issues": [
                {
                    "key": "HARQIS-42",
                    "fields": {
                        "summary": "Add context feed",
                        "status": {"name": "In Progress"},
                        "priority": {"name": "High"},
                        "assignee": {"displayName": "Brian"},
                        "updated": "2026-08-24T10:00:00.000+0000",
                    },
                }
            ]
        },
        domain="jira.example.test",
        correlation_id="corr-1",
    )
    assert len(items) == 1
    assert items[0].logical_key == "jira:HARQIS-42"
    assert items[0].priority == 82
    assert items[0].links["jira"] == "https://jira.example.test/browse/HARQIS-42"
    assert "telegram" in items[0].allowed_clients
    assert items[0].actions == ()


def test__normalize_jira_issues_skips_malformed_rows():
    assert normalize_jira_issues({"issues": [{"fields": {"summary": "Missing key"}}]}, correlation_id="x") == []
