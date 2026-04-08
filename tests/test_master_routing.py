"""
tests/test_master_routing.py
==============================

pytest cases for Master Agent intent routing.

These tests validate that the Master Agent correctly decomposes
complex prompts into A2A tasks routed to the right agents/skills.

Strategy: We bypass the Gemini API entirely and test the
``_rule_based_decomposition`` method (the fallback logic) plus the
``AgentRegistry.resolve_intent`` scoring. This makes all tests fast,
deterministic, and runnable without API keys.

Routing scenarios tested:
  1. Pure calendar prompt → CalendarAgent/schedule_event
  2. Pure task prompt → TaskAgent/create_task
  3. Mixed prompt (meeting + task) → both agents in parallel
  4. List calendar events → CalendarAgent/list_upcoming
  5. Update task status → TaskAgent/update_task
  6. Cancel event → CalendarAgent/cancel_event
  7. Assign task → TaskAgent/assign_task
  8. Ambiguous prompt → registry resolves to best match
  9. Complex multi-intent → 2 tasks dispatched
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_family.a2a.schemas import A2ATask, TaskDecomposition, TaskStatus
from agent_family.agents.calendar_agent import CALENDAR_AGENT_CARD
from agent_family.agents.master_agent import MasterAgent, MasterResponse, SubAgentResult
from agent_family.agents.task_agent import TASK_AGENT_CARD
from agent_family.registry.registry import AgentRegistry, ResolutionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry_with_agents(isolated_registry) -> AgentRegistry:
    """Pre-populated registry used by all routing tests."""
    isolated_registry.register(CALENDAR_AGENT_CARD)
    isolated_registry.register(TASK_AGENT_CARD)
    return isolated_registry


@pytest.fixture
def master(registry_with_agents) -> MasterAgent:
    """MasterAgent using the populated registry (no actual Gemini calls)."""
    return MasterAgent(model="gemini-2.0-flash-lite", registry=registry_with_agents)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def decompose(master: MasterAgent, prompt: str) -> TaskDecomposition:
    """Synchronously invoke rule-based decomposition."""
    return master._rule_based_decomposition(prompt)


@pytest.mark.asyncio
async def test_calendar_after_time_filter_passed_to_tool(master, monkeypatch):
    captured: dict[str, str | None] = {"time_min": None, "time_max": None}

    def fake_list_events(
        time_min=None,
        time_max=None,
        max_results=10,
        access_token=None,
        refresh_token=None,
    ):
        captured["time_min"] = time_min
        captured["time_max"] = time_max
        return []

    monkeypatch.setattr(
        "agent_family.mcp_servers.calendar_server.list_events",
        fake_list_events,
    )

    task = A2ATask(
        agent_name="CalendarAgent",
        skill_id="list_upcoming",
        prompt="any meeting after 6pm today?",
        parameters={},
    )
    await master._invoke_calendar_list_upcoming_direct(task)
    assert captured["time_min"] is not None


def test_rule_based_followup_uses_context_agent(master):
    dec = master._rule_based_decomposition(
        "there are multiple lists right?",
        context={"last_agent_name": "TaskAgent"},
    )
    assert dec.tasks[0].agent_name == "TaskAgent"
    assert dec.tasks[0].skill_id == "list_tasks"


@pytest.mark.asyncio
async def test_task_multiple_lists_direct_response(master, monkeypatch):
    def fake_list_task_lists(access_token=None, refresh_token=None):
        return [{"id": "a", "title": "Personal"}, {"id": "b", "title": "Shopping"}]

    def fake_list_tasks(task_list_id="@default", include_completed=False, access_token=None, refresh_token=None):
        return []

    monkeypatch.setattr("agent_family.mcp_servers.tasks_server.list_task_lists", fake_list_task_lists)
    monkeypatch.setattr("agent_family.mcp_servers.tasks_server.list_tasks", fake_list_tasks)

    task = A2ATask(
        agent_name="TaskAgent",
        skill_id="list_tasks",
        prompt="there are multiple lists right?",
        parameters={},
    )
    out = await master._invoke_task_list_direct(task)
    assert "you have 2 task lists" in out.lower()


def test_rule_based_followup_update_task(master):
    dec = master._rule_based_decomposition(
        "clear the bag",
        context={"last_agent_name": "TaskAgent", "last_skill_id": "update_task"},
    )
    assert dec.tasks[0].agent_name == "TaskAgent"
    assert dec.tasks[0].skill_id == "update_task"


@pytest.mark.asyncio
async def test_task_update_direct_marks_first_from_context(master, monkeypatch):
    def fake_list_tasks(task_list_id="@default", include_completed=False, access_token=None, refresh_token=None):
        return [
            {"task_id": "t1", "title": "Clear the bag", "task_list_id": "@default"},
            {"task_id": "t2", "title": "Cut the nails", "task_list_id": "@default"},
        ]

    def fake_update_task(task_id, status=None, task_list_id="@default", access_token=None, refresh_token=None):
        return {"task_id": task_id, "title": "Clear the bag", "task_list_id": task_list_id}

    monkeypatch.setattr("agent_family.mcp_servers.tasks_server.list_tasks", fake_list_tasks)
    monkeypatch.setattr("agent_family.mcp_servers.tasks_server.update_task", fake_update_task)

    task = A2ATask(
        agent_name="TaskAgent",
        skill_id="update_task",
        prompt="mark first one complete",
        parameters={"context": {"last_task_titles": "Clear the bag|||Cut the nails"}},
    )
    out = await master._invoke_task_update_direct(task)
    assert "marked task as completed" in out.lower()


@pytest.mark.asyncio
async def test_task_create_direct_creates_expected_title(master, monkeypatch):
    captured: dict[str, str | None] = {"title": None}

    def fake_create_task(title, notes=None, due=None, access_token=None, refresh_token=None):
        captured["title"] = title
        return {"task_id": "t123", "title": title, "task_list_id": "@default"}

    monkeypatch.setattr("agent_family.mcp_servers.tasks_server.create_task", fake_create_task)

    task = A2ATask(
        agent_name="TaskAgent",
        skill_id="create_task",
        prompt="add a task to play video game",
        parameters={},
    )
    out = await master._invoke_task_create_direct(task)
    assert captured["title"] == "play video game"
    assert "added this task" in out.lower()


@pytest.mark.asyncio
async def test_calendar_create_direct_uses_title_from_add_to_calendar_phrase(master, monkeypatch):
    captured: dict[str, str | None] = {"title": None}

    def fake_create_event(
        title,
        start_time,
        end_time,
        timezone="UTC",
        access_token=None,
        refresh_token=None,
    ):
        captured["title"] = title
        return {"event_id": "e123", "title": title, "start": start_time, "end": end_time}

    monkeypatch.setattr("agent_family.mcp_servers.calendar_server.create_event", fake_create_event)

    task = A2ATask(
        agent_name="CalendarAgent",
        skill_id="schedule_event",
        prompt="add karate class to my calendar at 5 am tomorrow",
        parameters={},
    )
    out = await master._invoke_calendar_create_direct(task)
    assert captured["title"] == "karate class"
    assert "added your karate class" in out.lower()


def test_smalltalk_no_subagent_routing(master):
    dec = decompose(master, "hi")
    assert len(dec.tasks) == 1
    assert dec.tasks[0].agent_name == "MasterAgent"
    assert dec.tasks[0].skill_id == "direct_reply"


def test_smalltalk_ignores_previous_agent_context(master):
    dec = master._rule_based_decomposition("hi", context={"last_agent_name": "TaskAgent"})
    assert len(dec.tasks) == 1
    assert dec.tasks[0].agent_name == "MasterAgent"
    assert dec.tasks[0].skill_id == "direct_reply"


@pytest.mark.asyncio
async def test_master_direct_reply_for_smalltalk(master):
    response = await master.run("hi")
    assert len(response.results) == 1
    assert response.results[0].agent_name == "MasterAgent"
    assert response.results[0].skill_id == "direct_reply"


def test_direct_reply_for_talk_intent_is_conversational(master):
    out = master._direct_master_reply("I just want to talk")
    assert "talk" in out.lower() or "chat" in out.lower()


# ---------------------------------------------------------------------------
# Scenario 1: Pure calendar prompt → schedule_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestCalendarRouting:
    def test_schedule_meeting_routes_to_calendar(self, master):
        dec = decompose(master, "Schedule a meeting with Alice tomorrow at 3pm")
        assert len(dec.tasks) >= 1
        calendar_tasks = [t for t in dec.tasks if t.agent_name == "CalendarAgent"]
        assert len(calendar_tasks) >= 1

    def test_schedule_routes_to_schedule_event_skill(self, master):
        dec = decompose(master, "Schedule a team standup every Monday at 9am")
        cal_tasks = [t for t in dec.tasks if t.agent_name == "CalendarAgent"]
        assert any(t.skill_id == "schedule_event" for t in cal_tasks)

    def test_book_appointment_routes_to_calendar(self, master):
        dec = decompose(master, "Book a dentist appointment next Friday")
        assert any(t.agent_name == "CalendarAgent" for t in dec.tasks)

    def test_calendar_keyword_triggers_calendar_agent(self, master):
        dec = decompose(master, "Add an event to my calendar for April 10th")
        assert any(t.agent_name == "CalendarAgent" for t in dec.tasks)

    def test_add_event_does_not_route_to_task_agent(self, master):
        dec = decompose(master, "Add an event to my calendar for April 10th at 10am")
        assert any(t.agent_name == "CalendarAgent" for t in dec.tasks)
        assert not any(t.agent_name == "TaskAgent" for t in dec.tasks)

    def test_add_to_my_calendar_routes_to_schedule_event(self, master):
        dec = decompose(master, "add karate class to my calendar at 7 am tomorrow")
        assert any(
            t.agent_name == "CalendarAgent" and t.skill_id == "schedule_event"
            for t in dec.tasks
        )

    def test_meeting_keyword_triggers_calendar(self, master):
        dec = decompose(master, "I have a meeting with the board next Tuesday")
        assert any(t.agent_name == "CalendarAgent" for t in dec.tasks)


# ---------------------------------------------------------------------------
# Scenario 2: Pure task prompt → create_task
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestTaskRouting:
    def test_add_task_does_not_route_to_calendar_agent(self, master):
        dec = decompose(master, "add a task to deploy on cloud run")
        assert any(t.agent_name == "TaskAgent" and t.skill_id == "create_task" for t in dec.tasks)
        assert not any(t.agent_name == "CalendarAgent" for t in dec.tasks)

    def test_create_task_routes_to_task_agent(self, master):
        dec = decompose(master, "Create a task to review the Q2 budget by Friday")
        task_tasks = [t for t in dec.tasks if t.agent_name == "TaskAgent"]
        assert len(task_tasks) >= 1

    def test_todo_keyword_routes_to_task(self, master):
        dec = decompose(master, "Add a todo: write documentation for the API")
        assert any(t.agent_name == "TaskAgent" for t in dec.tasks)

    def test_action_item_routes_to_task(self, master):
        dec = decompose(master, "Add an action item: Fix the login bug ASAP")
        assert any(t.agent_name == "TaskAgent" for t in dec.tasks)

    def test_reminder_routes_to_task(self, master):
        dec = decompose(master, "Create a reminder to submit the report by EOD")
        assert any(t.agent_name == "TaskAgent" for t in dec.tasks)

    def test_deadline_keyword_routes_to_task(self, master):
        dec = decompose(master, "Set a deadline for the design review task next week")
        assert any(t.agent_name == "TaskAgent" for t in dec.tasks)


# ---------------------------------------------------------------------------
# Scenario 3: Mixed prompt → both agents
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestMixedPromptRouting:
    def test_meeting_and_task_both_routed(self, master):
        prompt = "Schedule a meeting with Bob on Friday AND create a task to prepare slides"
        dec = decompose(master, prompt)
        agent_names = {t.agent_name for t in dec.tasks}
        assert "CalendarAgent" in agent_names
        assert "TaskAgent" in agent_names

    def test_multiple_tasks_created_for_mixed_prompt(self, master):
        prompt = "Book a room for tomorrow's standup and add a task to send the agenda"
        dec = decompose(master, prompt)
        assert len(dec.tasks) >= 2

    def test_mixed_prompt_original_preserved(self, master):
        prompt = "Schedule a call and create a task to follow up"
        dec = decompose(master, prompt)
        assert dec.original_prompt == prompt

    def test_each_task_has_unique_id(self, master):
        prompt = "Schedule a meeting and create a task and add another todo"
        dec = decompose(master, prompt)
        task_ids = [t.task_id for t in dec.tasks]
        assert len(task_ids) == len(set(task_ids)), "Task IDs must be unique"


# ---------------------------------------------------------------------------
# Scenario 4: List calendar events → list_upcoming
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestListEventsRouting:
    def test_list_events_uses_registry_resolution(self, registry_with_agents):
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "show me today's calendar events"
        )
        assert agent_name == "CalendarAgent"

    def test_upcoming_keyword_maps_to_list_skill(self, registry_with_agents):
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "show me upcoming events this week"
        )
        assert agent_name == "CalendarAgent"
        assert skill_id == "list_upcoming"

    def test_schedule_keyword_maps_to_schedule(self, registry_with_agents):
        results = registry_with_agents.resolve_all("schedule a meeting")
        top_result = results[0]
        assert top_result[0] == "CalendarAgent"
        assert top_result[1] == "schedule_event"

    def test_meeting_today_routes_to_list_upcoming(self, master):
        dec = decompose(master, "do I have any meeting today?")
        cal_tasks = [t for t in dec.tasks if t.agent_name == "CalendarAgent"]
        assert any(t.skill_id == "list_upcoming" for t in cal_tasks)

    def test_human_time_format_for_calendar_output(self, master):
        local_tz = datetime.now().astimezone().tzinfo
        formatted = master._format_event_start_for_humans("2026-04-08T15:00:00+05:30", local_tz)
        assert formatted == "3 pm"


# ---------------------------------------------------------------------------
# Scenario 5: Update task → update_task skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestUpdateTaskRouting:
    def test_mark_done_resolves_to_update_task(self, registry_with_agents):
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "mark the login bug task as done"
        )
        assert agent_name == "TaskAgent"
        assert skill_id == "update_task"

    def test_complete_task_resolves_to_update(self, registry_with_agents):
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "complete the user research task"
        )
        assert agent_name == "TaskAgent"


# ---------------------------------------------------------------------------
# Scenario 6: Cancel event → cancel_event skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestCancelEventRouting:
    def test_cancel_event_resolved(self, registry_with_agents):
        results = registry_with_agents.resolve_all("cancel my 3pm calendar event tomorrow")
        top = results[0]
        assert top[0] == "CalendarAgent"

    def test_delete_event_resolved_to_calendar(self, registry_with_agents):
        agent_name, _ = registry_with_agents.resolve_intent(
            "delete the Monday standup event from my calendar"
        )
        assert agent_name == "CalendarAgent"


# ---------------------------------------------------------------------------
# Scenario 7: Assign task → assign_task skill
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestAssignTaskRouting:
    def test_assign_task_routing(self, registry_with_agents):
        # Use 'assignee' which is an exact tag on assign_task
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "please set the assignee for the refactor task to Bob"
        )
        assert agent_name == "TaskAgent"
        assert skill_id == "assign_task"

    def test_delegate_routing(self, registry_with_agents):
        # Use 'assignee' + 'task' which are exact tags on assign_task
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "set the task assignee to Carol for the security work item"
        )
        assert agent_name == "TaskAgent"
        # 'assignee' is a strong tag on assign_task
        assert skill_id == "assign_task"


# ---------------------------------------------------------------------------
# Scenario 8: Ambiguous prompts — best match wins
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestAmbiguousRouting:
    def test_ambiguous_still_resolves(self, registry_with_agents):
        """Even ambiguous prompts must resolve to something."""
        agent_name, skill_id = registry_with_agents.resolve_intent(
            "I need to organise my week"
        )
        # Must resolve to some registered agent
        assert agent_name in {"CalendarAgent", "TaskAgent"}

    def test_resolution_error_for_empty_registry(self, isolated_registry):
        """Empty registry → ResolutionError."""
        with pytest.raises(ResolutionError, match="Could not resolve intent"):
            isolated_registry.resolve_intent("schedule a meeting")

    def test_resolve_all_returns_sorted_scores(self, registry_with_agents):
        results = registry_with_agents.resolve_all("schedule a meeting")
        scores = [r[2] for r in results]
        assert scores == sorted(scores, reverse=True), "resolve_all must be sorted descending"

    def test_resolve_all_includes_all_agents(self, registry_with_agents):
        results = registry_with_agents.resolve_all("do something")
        agent_names = {r[0] for r in results}
        assert "CalendarAgent" in agent_names
        assert "TaskAgent" in agent_names


# ---------------------------------------------------------------------------
# Scenario 9: Complex multi-intent prompt decomposition
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.routing
class TestComplexPromptDecomposition:
    def test_complex_prompt_decomposed_correctly(self, master):
        prompt = (
            "Please schedule a project kickoff meeting for next Monday at 10am, "
            "invite the engineering team, and create a task for me to prepare the agenda. "
            "Also, add a reminder task to send follow-up emails by EOD."
        )
        dec = decompose(master, prompt)
        # Should have both calendar and task agents
        agent_names = {t.agent_name for t in dec.tasks}
        assert "CalendarAgent" in agent_names
        assert "TaskAgent" in agent_names

    def test_all_tasks_have_valid_schema(self, master):
        """Every task in the decomposition must pass Pydantic validation."""
        prompt = "Book a meeting tomorrow and create a high-priority task for the review"
        dec = decompose(master, prompt)
        for task in dec.tasks:
            # Re-validate through Pydantic (should not raise)
            validated = A2ATask.model_validate(task.model_dump())
            assert validated.agent_name in {"CalendarAgent", "TaskAgent"}

    def test_task_prompts_are_non_empty(self, master):
        prompt = "Schedule a standup and add a task to write tests"
        dec = decompose(master, prompt)
        for task in dec.tasks:
            assert len(task.prompt.strip()) > 0

    def test_decomposition_id_is_uuid(self, master):
        import uuid
        dec = decompose(master, "Schedule a meeting and create a task")
        uuid.UUID(dec.decomposition_id)  # must not raise


# ---------------------------------------------------------------------------
# MasterAgent._aggregate tests (no API calls)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMasterAgentAggregate:
    def _make_decomposition(self) -> TaskDecomposition:
        return TaskDecomposition(
            original_prompt="test",
            tasks=[
                A2ATask(agent_name="CalendarAgent", skill_id="schedule_event", prompt="p1"),
                A2ATask(agent_name="TaskAgent", skill_id="create_task", prompt="p2"),
            ],
        )

    def test_all_success_status(self, master):
        decomp = self._make_decomposition()
        results = [
            SubAgentResult(
                task_id=decomp.tasks[0].task_id,
                agent_name="CalendarAgent",
                skill_id="schedule_event",
                status=TaskStatus.COMPLETED,
                output="Event created",
            ),
            SubAgentResult(
                task_id=decomp.tasks[1].task_id,
                agent_name="TaskAgent",
                skill_id="create_task",
                status=TaskStatus.COMPLETED,
                output="Task created",
            ),
        ]
        response = master._aggregate("test", decomp, results)
        assert response.overall_status == "success"
        assert response.success_count == 2
        assert response.failure_count == 0

    def test_all_failure_status(self, master):
        decomp = self._make_decomposition()
        results = [
            SubAgentResult(
                task_id=t.task_id,
                agent_name=t.agent_name,
                skill_id=t.skill_id,
                status=TaskStatus.FAILED,
                error="Something went wrong",
            )
            for t in decomp.tasks
        ]
        response = master._aggregate("test", decomp, results)
        assert response.overall_status == "failure"
        assert response.failure_count == 2

    def test_partial_failure_status(self, master):
        decomp = self._make_decomposition()
        results = [
            SubAgentResult(
                task_id=decomp.tasks[0].task_id,
                agent_name="CalendarAgent",
                skill_id="schedule_event",
                status=TaskStatus.COMPLETED,
                output="Done",
            ),
            SubAgentResult(
                task_id=decomp.tasks[1].task_id,
                agent_name="TaskAgent",
                skill_id="create_task",
                status=TaskStatus.FAILED,
                error="API error",
            ),
        ]
        response = master._aggregate("test", decomp, results)
        assert response.overall_status == "partial_failure"

    def test_summary_contains_agent_names(self, master):
        decomp = self._make_decomposition()
        results = [
            SubAgentResult(
                task_id=decomp.tasks[0].task_id,
                agent_name="CalendarAgent",
                skill_id="schedule_event",
                status=TaskStatus.COMPLETED,
                output="Done",
            ),
            SubAgentResult(
                task_id=decomp.tasks[1].task_id,
                agent_name="TaskAgent",
                skill_id="create_task",
                status=TaskStatus.COMPLETED,
                output="Done",
            ),
        ]
        response = master._aggregate("test", decomp, results)
        assert "CalendarAgent" in response.summary
        assert "TaskAgent" in response.summary

    def test_response_preserves_original_prompt(self, master):
        decomp = self._make_decomposition()
        results = [
            SubAgentResult(
                task_id=decomp.tasks[0].task_id,
                agent_name="CalendarAgent",
                skill_id="schedule_event",
                status=TaskStatus.COMPLETED,
                output="Done",
            ),
        ]
        resp = master._aggregate("My original request", decomp, results)
        assert resp.original_prompt == "My original request"
