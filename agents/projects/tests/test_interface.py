"""
Tests for the KanbanCard dataclasses and AgentContext builder.
No network calls — fully offline.
"""

import pytest
from hamcrest import assert_that, equal_to, contains_string, instance_of, has_length

from agents.projects.agent.context import AgentContext, build_card_context
from agents.projects.trello.models import KanbanCard, KanbanChecklist, KanbanChecklistItem


@pytest.mark.smoke
def test_kanban_card_defaults():
    card = KanbanCard(
        id="c1",
        title="Test",
        description="desc",
        labels=[],
        assignees=[],
        column="Backlog",
        url="https://trello.com/c/c1",
    )
    assert_that(card.checklists, equal_to([]))
    assert_that(card.attachments, equal_to([]))
    assert_that(card.custom_fields, equal_to({}))
    assert_that(card.due_date, equal_to(None))


@pytest.mark.smoke
def test_agent_context_to_prompt_includes_task(sample_card):
    ctx = AgentContext(
        card_id=sample_card.id,
        card_url=sample_card.url,
        prompt=sample_card.description,
        checklists=sample_card.checklists,
        params=sample_card.custom_fields,
    )
    prompt = ctx.to_prompt()
    assert_that(prompt, contains_string("# Task"))
    assert_that(prompt, contains_string(sample_card.description))


@pytest.mark.smoke
def test_agent_context_includes_checklists(sample_card):
    ctx = AgentContext(
        card_id=sample_card.id,
        card_url=sample_card.url,
        prompt=sample_card.description,
        checklists=sample_card.checklists,
        params={},
    )
    prompt = ctx.to_prompt()
    assert_that(prompt, contains_string("# Sub-tasks"))
    assert_that(prompt, contains_string("Read existing code"))
    assert_that(prompt, contains_string("[ ]"))


@pytest.mark.smoke
def test_agent_context_includes_params(sample_card):
    ctx = AgentContext(
        card_id=sample_card.id,
        card_url=sample_card.url,
        prompt=sample_card.description,
        params={"repo_url": "https://github.com/example/repo"},
    )
    prompt = ctx.to_prompt()
    assert_that(prompt, contains_string("# Parameters"))
    assert_that(prompt, contains_string("repo_url"))


@pytest.mark.smoke
def test_agent_context_includes_card_url(sample_card):
    ctx = AgentContext(
        card_id=sample_card.id,
        card_url=sample_card.url,
        prompt="task",
    )
    prompt = ctx.to_prompt()
    assert_that(prompt, contains_string(sample_card.url))


@pytest.mark.smoke
def test_build_card_context_no_attachments(minimal_card):
    ctx = build_card_context(minimal_card, fetch_text_attachments=False)
    assert_that(ctx, instance_of(AgentContext))
    assert_that(ctx.card_id, equal_to(minimal_card.id))
    assert_that(ctx.prompt, equal_to(minimal_card.description))
    assert_that(ctx.file_contents, has_length(0))


@pytest.mark.smoke
def test_build_card_context_uses_description_over_title(sample_card):
    ctx = build_card_context(sample_card, fetch_text_attachments=False)
    assert_that(ctx.prompt, equal_to(sample_card.description))


@pytest.mark.smoke
def test_build_card_context_falls_back_to_title():
    card = KanbanCard(
        id="c2",
        title="Do the thing",
        description="",
        labels=[],
        assignees=[],
        column="Backlog",
        url="https://trello.com/c/c2",
    )
    ctx = build_card_context(card, fetch_text_attachments=False)
    assert_that(ctx.prompt, equal_to("Do the thing"))
