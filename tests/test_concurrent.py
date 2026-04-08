"""
tests/test_concurrent.py
==========================

Tests for asyncio-based concurrent sub-agent dispatch.

We mock ``MasterAgent._invoke_sub_agent`` to avoid real API calls while
still validating that:

  1. asyncio.gather dispatches all tasks concurrently (not sequentially).
  2. Individual task failures don't cancel sibling tasks.
  3. Results are returned for every task regardless of outcome.
  4. Task ordering in results matches the input decomposition.
  5. Latency is measured per-task.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from agent_family.a2a.schemas import A2ATask, TaskDecomposition, TaskStatus
from agent_family.agents.calendar_agent import CALENDAR_AGENT_CARD
from agent_family.agents.master_agent import MasterAgent, SubAgentResult
from agent_family.agents.task_agent import TASK_AGENT_CARD
from agent_family.registry.registry import AgentRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry(isolated_registry) -> AgentRegistry:
    isolated_registry.register(CALENDAR_AGENT_CARD)
    isolated_registry.register(TASK_AGENT_CARD)
    return isolated_registry


@pytest.fixture
def master(registry) -> MasterAgent:
    return MasterAgent(model="gemini-2.0-flash-lite", registry=registry)


def make_task(agent: str, skill: str, prompt: str = "p") -> A2ATask:
    return A2ATask(agent_name=agent, skill_id=skill, prompt=prompt)


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConcurrentDispatch:
    async def test_two_tasks_dispatched_concurrently(self, master):
        """
        With mocked sub-agent that sleeps 0.1s, two tasks should finish
        in ~0.1s total (concurrent), not ~0.2s (sequential).
        """
        call_times: list[float] = []

        async def mock_invoke(message, card):
            call_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return f"done: {message.params.skill_id}"

        tasks = [
            make_task("CalendarAgent", "schedule_event", "Book a room"),
            make_task("TaskAgent", "create_task", "Create task"),
        ]
        decomp = TaskDecomposition(
            original_prompt="dual intent",
            tasks=tasks,
        )

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            t_start = time.monotonic()
            results = await master._dispatch_all(decomp)
            elapsed = time.monotonic() - t_start

        assert len(results) == 2
        # Two 50ms tasks concurrently must finish < 150ms (generous headroom)
        assert elapsed < 0.15, f"Expected concurrent execution, took {elapsed:.3f}s"
        # Both tasks called near-simultaneously
        assert abs(call_times[0] - call_times[1]) < 0.03

    async def test_results_count_matches_task_count(self, master):
        tasks = [
            make_task("CalendarAgent", "schedule_event"),
            make_task("TaskAgent", "create_task"),
            make_task("CalendarAgent", "list_upcoming"),
        ]
        decomp = TaskDecomposition(original_prompt="three tasks", tasks=tasks)

        async def mock_invoke(msg, card):
            return "ok"

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        assert len(results) == 3

    async def test_all_results_are_subagent_result_instances(self, master):
        tasks = [make_task("CalendarAgent", "schedule_event")]
        decomp = TaskDecomposition(original_prompt="one task", tasks=tasks)

        async def mock_invoke(msg, card):
            return "completed output"

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        for r in results:
            assert isinstance(r, SubAgentResult)


# ---------------------------------------------------------------------------
# Failure isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFailureIsolation:
    async def test_one_failure_does_not_cancel_sibling(self, master):
        """If one sub-agent raises, the others must still complete."""
        call_count = 0

        async def mock_invoke(msg, card):
            nonlocal call_count
            call_count += 1
            if msg.params.agent_name == "CalendarAgent":
                raise RuntimeError("Calendar service down")
            return "Task completed"

        tasks = [
            make_task("CalendarAgent", "schedule_event"),
            make_task("TaskAgent", "create_task"),
        ]
        decomp = TaskDecomposition(original_prompt="mixed intent", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        assert call_count == 2, "Both agents must be called even if one fails"
        statuses = {r.agent_name: r.status for r in results}
        assert statuses["CalendarAgent"] == TaskStatus.FAILED
        assert statuses["TaskAgent"] == TaskStatus.COMPLETED

    async def test_failed_result_contains_error_message(self, master):
        async def mock_invoke(msg, card):
            raise ValueError("Test error: API timeout")

        tasks = [make_task("CalendarAgent", "schedule_event")]
        decomp = TaskDecomposition(original_prompt="one task", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        assert results[0].status == TaskStatus.FAILED
        assert "Test error: API timeout" in results[0].error

    async def test_successful_result_contains_output(self, master):
        async def mock_invoke(msg, card):
            return "Event successfully scheduled"

        tasks = [make_task("CalendarAgent", "schedule_event")]
        decomp = TaskDecomposition(original_prompt="one task", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        assert results[0].status == TaskStatus.COMPLETED
        assert results[0].output == "Event successfully scheduled"

    async def test_all_failures_produces_failure_aggregate(self, master):
        async def mock_invoke(msg, card):
            raise RuntimeError("All down")

        tasks = [
            make_task("CalendarAgent", "schedule_event"),
            make_task("TaskAgent", "create_task"),
        ]
        decomp = TaskDecomposition(original_prompt="dual intent", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        # Both failed
        response = master._aggregate("dual intent", decomp, results)
        assert response.overall_status == "failure"


# ---------------------------------------------------------------------------
# Unknown agent / skill routing guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRoutingGuards:
    async def test_unknown_agent_yields_failed_result(self, master):
        task = make_task("UnknownAgent", "nonexistent_skill")
        decomp = TaskDecomposition(original_prompt="bad routing", tasks=[task])

        # No mock — should fail because UnknownAgent is not in registry
        results = await master._dispatch_all(decomp)
        assert results[0].status == TaskStatus.FAILED
        assert "not found" in (results[0].error or "").lower()

    async def test_unknown_skill_on_known_agent_yields_failed_result(self, master):
        task = make_task("CalendarAgent", "nonexistent_skill")
        decomp = TaskDecomposition(original_prompt="bad skill", tasks=[task])

        results = await master._dispatch_all(decomp)
        # CalendarAgent is registered but doesn't have 'nonexistent_skill'
        assert results[0].status == TaskStatus.FAILED
        assert "nonexistent_skill" in (results[0].error or "").lower()


# ---------------------------------------------------------------------------
# Latency measurement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLatencyMeasurement:
    async def test_latency_is_recorded(self, master):
        async def mock_invoke(msg, card):
            await asyncio.sleep(0.01)
            return "done"

        tasks = [make_task("CalendarAgent", "schedule_event")]
        decomp = TaskDecomposition(original_prompt="one task", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        assert results[0].latency_ms > 0, "Latency must be measured"

    async def test_latency_reasonable_for_fast_task(self, master):
        async def mock_invoke(msg, card):
            return "instant"

        tasks = [make_task("TaskAgent", "create_task")]
        decomp = TaskDecomposition(original_prompt="p", tasks=tasks)

        with patch.object(master, "_invoke_sub_agent", side_effect=mock_invoke):
            results = await master._dispatch_all(decomp)

        # Should be < 1000ms for a local stub
        assert results[0].latency_ms < 1000
