"""
tests/conftest.py
==================

Shared pytest fixtures for the Agent Family test suite.

Fixtures are grouped by scope:
  - session: set up once per test session  (registry population)
  - function: set up per test (isolated registry, mock agents)

Important: each test that touches AgentRegistry must call
``AgentRegistry.reset_singleton()`` via the ``isolated_registry`` fixture
to avoid cross-test state pollution.
"""

from __future__ import annotations

import pytest

from agent_family.a2a.agent_card import AgentCard, AgentProvider
from agent_family.a2a.schemas import AgentCapabilities, AgentSkill, InputMode, OutputMode
from agent_family.registry.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def make_skill(
    skill_id: str = "test_skill",
    name: str = "Test Skill",
    description: str = "A test skill",
    tags: list[str] | None = None,
    examples: list[str] | None = None,
) -> AgentSkill:
    return AgentSkill(
        id=skill_id,
        name=name,
        description=description,
        tags=tags or ["test"],
        examples=examples or [f"example {skill_id} phrase"],
    )


def make_card(
    name: str = "TestAgent",
    url: str = "http://localhost:9000",
    skills: list[AgentSkill] | None = None,
) -> AgentCard:
    return AgentCard(
        name=name,
        description=f"Test agent: {name}",
        version="1.0.0",
        url=url,
        provider=AgentProvider(organization="Test Org"),
        capabilities=AgentCapabilities(),
        skills=skills or [make_skill()],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def isolated_registry():
    """
    Provide a fresh AgentRegistry for each test and tear it down afterwards.

    Use this fixture in any test that touches the registry to ensure
    complete isolation.
    """
    AgentRegistry.reset_singleton()
    registry = AgentRegistry()
    yield registry
    AgentRegistry.reset_singleton()


@pytest.fixture
def calendar_card() -> AgentCard:
    """Real CalendarAgent AgentCard from the production module."""
    from agent_family.agents.calendar_agent import CALENDAR_AGENT_CARD
    return CALENDAR_AGENT_CARD


@pytest.fixture
def task_card() -> AgentCard:
    """Real TaskAgent AgentCard from the production module."""
    from agent_family.agents.task_agent import TASK_AGENT_CARD
    return TASK_AGENT_CARD


@pytest.fixture
def populated_registry(isolated_registry, calendar_card, task_card) -> AgentRegistry:
    """Registry pre-populated with CalendarAgent + TaskAgent cards."""
    isolated_registry.register(calendar_card)
    isolated_registry.register(task_card)
    return isolated_registry
