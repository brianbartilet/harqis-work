import pytest
from workflows.social.tasks.social_linkedin_monthly import (
    generate_monthly_linkedin_post,
    _get_git_commits,
    _load_previous_post_from_logs,
    _format_commits_for_prompt,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__generate_monthly_linkedin_post():
    generate_monthly_linkedin_post(skip_draft=True, skip_email=True)


def test__generate_monthly_linkedin_post_march_2026():
    generate_monthly_linkedin_post(month=3, year=2026, skip_draft=True, skip_email=True)


@pytest.mark.skip(reason="Manual only — creates a real LinkedIn draft")
def test__generate_monthly_linkedin_post_with_draft():
    generate_monthly_linkedin_post(month=3, year=2026, skip_email=True)


@pytest.mark.skip(reason="Manual only — creates a real LinkedIn draft and sends email")
def test__generate_monthly_linkedin_post_full_pipeline():
    generate_monthly_linkedin_post(month=3, year=2026)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__get_git_commits_returns_list():
    result = _get_git_commits(2026, 3)
    assert isinstance(result, list)


def test__get_git_commits_structure():
    result = _get_git_commits(2026, 3)
    if result:
        assert "hash" in result[0]
        assert "date" in result[0]
        assert "subject" in result[0]


def test__get_git_commits_empty_future_month():
    result = _get_git_commits(2099, 1)
    assert result == []


def test__format_commits_for_prompt_empty():
    result = _format_commits_for_prompt([])
    assert "no commits" in result.lower()


def test__format_commits_for_prompt_with_data():
    commits = [{"hash": "abc12345", "date": "2026-03-15", "subject": "(work) add feature"}]
    result = _format_commits_for_prompt(commits)
    assert "2026-03-15" in result
    assert "add feature" in result


def test__load_previous_post_no_file_returns_none():
    result = _load_previous_post_from_logs(2099, 1)
    assert result is None
