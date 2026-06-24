"""Deployment guards for the knowledge beat schedule."""

import importlib


_ENV_KEYS = (
    "HARQIS_KNOWLEDGE_ENABLE_REPORT",
    "HARQIS_KNOWLEDGE_REPORT_SUMMARIZE",
    "HARQIS_KNOWLEDGE_REPORT_LIMIT",
    "HARQIS_KNOWLEDGE_CONFLUENCE_SPACES",
    "HARQIS_KNOWLEDGE_CONFLUENCE_MAX_PAGES",
    "HARQIS_KNOWLEDGE_CONFLUENCE_CQL_EXTRA",
    "HARQIS_KNOWLEDGE_ENABLE_CONFLUENCE",
    "HARQIS_KNOWLEDGE_JIRA_PROJECTS",
    "HARQIS_KNOWLEDGE_ENABLE_JIRA",
    "HARQIS_KNOWLEDGE_JIRA_MAX_ISSUES",
    "HARQIS_KNOWLEDGE_JIRA_MAX_COMMENTS",
    "HARQIS_KNOWLEDGE_JIRA_JQL_EXTRA",
    "HARQIS_KNOWLEDGE_ENABLE_MORNING_BRIEF",
    "HARQIS_KNOWLEDGE_MORNING_BRIEF_QUESTION",
    "HARQIS_KNOWLEDGE_MORNING_BRIEF_SOURCE",
    "HARQIS_KNOWLEDGE_MORNING_BRIEF_K",
)


def _reload_tasks_config(monkeypatch, **env):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    from workflows.knowledge import tasks_config

    return importlib.reload(tasks_config)


def test_default_schedule_is_live_safe(monkeypatch):
    cfg = _reload_tasks_config(monkeypatch)

    assert sorted(cfg.WORKFLOW_KNOWLEDGE) == ["run-job--knowledge_cross_link_report"]
    report = cfg.WORKFLOW_KNOWLEDGE["run-job--knowledge_cross_link_report"]
    assert report["kwargs"]["summarize"] is False
    assert report["kwargs"]["limit"] == 50


def test_report_can_be_disabled_for_deploy(monkeypatch):
    cfg = _reload_tasks_config(monkeypatch, HARQIS_KNOWLEDGE_ENABLE_REPORT="0")

    assert cfg.WORKFLOW_KNOWLEDGE == {}


def test_report_summary_and_limit_are_explicit_opt_ins(monkeypatch):
    cfg = _reload_tasks_config(
        monkeypatch,
        HARQIS_KNOWLEDGE_REPORT_SUMMARIZE="true",
        HARQIS_KNOWLEDGE_REPORT_LIMIT="12",
    )

    report = cfg.WORKFLOW_KNOWLEDGE["run-job--knowledge_cross_link_report"]
    assert report["kwargs"]["summarize"] is True
    assert report["kwargs"]["limit"] == 12


def test_confluence_requires_scoped_spaces(monkeypatch):
    cfg = _reload_tasks_config(monkeypatch, HARQIS_KNOWLEDGE_CONFLUENCE_SPACES="ENG, OPS")

    ingest = cfg.WORKFLOW_KNOWLEDGE["run-job--ingest_confluence_pages"]
    assert ingest["kwargs"]["space_keys"] == ["ENG", "OPS"]
    assert ingest["kwargs"]["max_pages"] == 200


def test_confluence_can_be_disabled_even_with_spaces(monkeypatch):
    cfg = _reload_tasks_config(
        monkeypatch,
        HARQIS_KNOWLEDGE_CONFLUENCE_SPACES="ENG",
        HARQIS_KNOWLEDGE_ENABLE_CONFLUENCE="false",
    )

    assert "run-job--ingest_confluence_pages" not in cfg.WORKFLOW_KNOWLEDGE

def test_jira_requires_scoped_projects(monkeypatch):
    cfg = _reload_tasks_config(monkeypatch, HARQIS_KNOWLEDGE_JIRA_PROJECTS="ABC, XYZ")

    ingest = cfg.WORKFLOW_KNOWLEDGE["run-job--ingest_jira_issues"]
    assert ingest["kwargs"]["project_keys"] == ["ABC", "XYZ"]
    assert ingest["kwargs"]["max_issues"] == 100
    assert ingest["kwargs"]["max_comments"] == 20


def test_jira_can_be_disabled_even_with_projects(monkeypatch):
    cfg = _reload_tasks_config(
        monkeypatch,
        HARQIS_KNOWLEDGE_JIRA_PROJECTS="ABC",
        HARQIS_KNOWLEDGE_ENABLE_JIRA="0",
    )

    assert "run-job--ingest_jira_issues" not in cfg.WORKFLOW_KNOWLEDGE


def test_morning_brief_requires_explicit_enable(monkeypatch):
    cfg = _reload_tasks_config(monkeypatch)

    assert "run-job--knowledge_answer_morning_brief" not in cfg.WORKFLOW_KNOWLEDGE


def test_morning_brief_env_overrides(monkeypatch):
    cfg = _reload_tasks_config(
        monkeypatch,
        HARQIS_KNOWLEDGE_ENABLE_MORNING_BRIEF="1",
        HARQIS_KNOWLEDGE_MORNING_BRIEF_QUESTION="What changed in Confluence?",
        HARQIS_KNOWLEDGE_MORNING_BRIEF_SOURCE="confluence",
        HARQIS_KNOWLEDGE_MORNING_BRIEF_K="5",
    )

    brief = cfg.WORKFLOW_KNOWLEDGE["run-job--knowledge_answer_morning_brief"]
    assert brief["kwargs"]["question"] == "What changed in Confluence?"
    assert brief["kwargs"]["source"] == "confluence"
    assert brief["kwargs"]["k"] == 5

