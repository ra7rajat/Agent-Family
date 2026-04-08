"""
tests/test_schemas.py
======================

Unit tests for Pydantic v2 A2A protocol schemas.

Tests cover:
  - Valid construction of all schema types
  - Field validation (snake_case, min_length, enum values)
  - Model validators (exactly-one-of, output-required-when-completed)
  - Serialisation round-trips (model_dump / model_validate)
  - Invalid data rejection with clear error messages
  - AgentCard construction and helpers
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_family.a2a.agent_card import AgentCard, AgentAuthentication, AgentProvider
from agent_family.a2a.schemas import (
    A2AError,
    A2AMessage,
    A2APart,
    A2AResponse,
    A2AResult,
    A2ATask,
    AgentCapabilities,
    AgentSkill,
    InputMode,
    OutputMode,
    TaskDecomposition,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# AgentSkill
# ---------------------------------------------------------------------------


class TestAgentSkill:
    def test_valid_skill(self):
        skill = AgentSkill(
            id="schedule_event",
            name="Schedule Event",
            description="Creates a calendar event",
            tags=["calendar", "meeting"],
        )
        assert skill.id == "schedule_event"
        assert "calendar" in skill.tags

    def test_id_is_normalised_to_lowercase(self):
        skill = AgentSkill(id="MYSKILL", name="n", description="d")
        assert skill.id == "myskill"

    def test_id_must_be_alphanumeric_snake_case(self):
        with pytest.raises(ValidationError, match="snake_case"):
            AgentSkill(id="bad-id!", name="n", description="d")

    def test_skill_is_frozen(self):
        skill = AgentSkill(id="myskill", name="n", description="d")
        with pytest.raises(Exception):  # ValidationError or TypeError depending on pydantic version
            skill.id = "other"  # type: ignore[misc]

    def test_default_modes(self):
        skill = AgentSkill(id="test", name="n", description="d")
        assert InputMode.TEXT in skill.input_modes
        assert OutputMode.TEXT in skill.output_modes

    def test_examples_list(self):
        skill = AgentSkill(
            id="myskill",
            name="n",
            description="d",
            examples=["do something", "perform action"],
        )
        assert len(skill.examples) == 2


# ---------------------------------------------------------------------------
# AgentCapabilities
# ---------------------------------------------------------------------------


class TestAgentCapabilities:
    def test_defaults(self):
        caps = AgentCapabilities()
        assert caps.streaming is False
        assert caps.multi_turn is True
        assert caps.state_transition_history is True

    def test_custom_values(self):
        caps = AgentCapabilities(streaming=True, push_notifications=True)
        assert caps.streaming is True


# ---------------------------------------------------------------------------
# A2ATask
# ---------------------------------------------------------------------------


class TestA2ATask:
    def test_valid_task(self):
        task = A2ATask(
            agent_name="CalendarAgent",
            skill_id="schedule_event",
            prompt="Schedule a meeting tomorrow at 3pm",
        )
        assert task.agent_name == "CalendarAgent"
        assert task.skill_id == "schedule_event"
        assert task.status == TaskStatus.PENDING
        assert isinstance(task.task_id, str)

    def test_task_id_is_uuid_by_default(self):
        task = A2ATask(
            agent_name="TaskAgent",
            skill_id="create_task",
            prompt="Create a task",
        )
        # Should be a valid UUID string
        uuid.UUID(task.task_id)

    def test_agent_name_stripped_whitespace(self):
        task = A2ATask(
            agent_name="  CalendarAgent  ",
            skill_id="schedule_event",
            prompt="test",
        )
        assert task.agent_name == "CalendarAgent"

    def test_blank_agent_name_rejected(self):
        with pytest.raises(ValidationError, match="agent_name must not be blank"):
            A2ATask(agent_name="   ", skill_id="schedule_event", prompt="p")

    def test_skill_id_normalised_lowercase(self):
        task = A2ATask(
            agent_name="TaskAgent",
            skill_id="CREATE_TASK",
            prompt="p",
        )
        assert task.skill_id == "create_task"

    def test_invalid_skill_id_rejected(self):
        with pytest.raises(ValidationError, match="snake_case"):
            A2ATask(agent_name="A", skill_id="bad-skill!", prompt="p")

    def test_priority_bounds(self):
        with pytest.raises(ValidationError):
            A2ATask(agent_name="A", skill_id="s", prompt="p", priority=0)
        with pytest.raises(ValidationError):
            A2ATask(agent_name="A", skill_id="s", prompt="p", priority=11)

    def test_priority_valid_range(self):
        for p in [1, 5, 10]:
            task = A2ATask(agent_name="A", skill_id="myskill", prompt="p", priority=p)
            assert task.priority == p

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError):
            A2ATask(agent_name="A", skill_id="s", prompt="")

    def test_parameters_default_empty_dict(self):
        task = A2ATask(agent_name="A", skill_id="myskill", prompt="p")
        assert task.parameters == {}

    def test_serialisation_round_trip(self):
        task = A2ATask(
            agent_name="CalendarAgent",
            skill_id="schedule_event",
            prompt="Book a room at 2pm",
            parameters={"time": "14:00", "duration_hours": 1},
        )
        data = task.model_dump(mode="json")
        restored = A2ATask.model_validate(data)
        assert restored.agent_name == task.agent_name
        assert restored.parameters["time"] == "14:00"


# ---------------------------------------------------------------------------
# A2APart
# ---------------------------------------------------------------------------


class TestA2APart:
    def test_text_part(self):
        part = A2APart(type="text", text="Hello")
        assert part.text == "Hello"

    def test_data_part(self):
        part = A2APart(type="data", data={"key": "value"})
        assert part.data["key"] == "value"

    def test_empty_part_rejected(self):
        with pytest.raises(ValidationError, match="either 'text' or 'data'"):
            A2APart(type="text")


# ---------------------------------------------------------------------------
# A2AMessage
# ---------------------------------------------------------------------------


class TestA2AMessage:
    def test_valid_message(self):
        task = A2ATask(agent_name="A", skill_id="myskill", prompt="p")
        msg = A2AMessage(params=task)
        assert msg.jsonrpc == "2.0"
        assert msg.method == "tasks/send"

    def test_invalid_method_rejected(self):
        task = A2ATask(agent_name="A", skill_id="myskill", prompt="p")
        with pytest.raises(ValidationError, match="method must be one of"):
            A2AMessage(params=task, method="unknown/method")

    def test_all_valid_methods(self):
        task = A2ATask(agent_name="A", skill_id="myskill", prompt="p")
        for method in ["tasks/send", "tasks/get", "tasks/cancel", "tasks/sendSubscribe"]:
            msg = A2AMessage(params=task, method=method)
            assert msg.method == method


# ---------------------------------------------------------------------------
# A2AResult and A2AResponse
# ---------------------------------------------------------------------------


class TestA2AResult:
    def test_valid_completed_result(self):
        result = A2AResult(
            task_id="t1",
            agent_name="CalendarAgent",
            status=TaskStatus.COMPLETED,
            output="Event created",
        )
        assert result.output == "Event created"

    def test_output_required_when_completed(self):
        with pytest.raises(ValidationError, match="output is required when status is COMPLETED"):
            A2AResult(
                task_id="t1",
                agent_name="CalendarAgent",
                status=TaskStatus.COMPLETED,
                output=None,
            )

    def test_failed_result_no_output_required(self):
        result = A2AResult(
            task_id="t1",
            agent_name="CalendarAgent",
            status=TaskStatus.FAILED,
        )
        assert result.output is None


class TestA2AResponse:
    def _make_result(self) -> A2AResult:
        return A2AResult(
            task_id="t1",
            agent_name="CalendarAgent",
            status=TaskStatus.COMPLETED,
            output="Done",
        )

    def test_valid_success_response(self):
        resp = A2AResponse(id="r1", result=self._make_result())
        assert resp.result is not None
        assert resp.error is None

    def test_valid_error_response(self):
        resp = A2AResponse(
            id="r1",
            error=A2AError(code=-32600, message="Invalid Request"),
        )
        assert resp.error is not None
        assert resp.result is None

    def test_neither_result_nor_error_rejected(self):
        with pytest.raises(ValidationError, match="either 'result' or 'error'"):
            A2AResponse(id="r1")

    def test_both_result_and_error_rejected(self):
        with pytest.raises(ValidationError, match="cannot contain both"):
            A2AResponse(
                id="r1",
                result=self._make_result(),
                error=A2AError(code=-32600, message="err"),
            )


# ---------------------------------------------------------------------------
# TaskDecomposition
# ---------------------------------------------------------------------------


class TestTaskDecomposition:
    def _make_task(self, agent: str = "CalendarAgent", skill: str = "schedule_event") -> A2ATask:
        return A2ATask(agent_name=agent, skill_id=skill, prompt="p")

    def test_valid_single_task_decomposition(self):
        dec = TaskDecomposition(
            original_prompt="Schedule a meeting",
            tasks=[self._make_task()],
        )
        assert len(dec.tasks) == 1
        assert isinstance(dec.decomposition_id, str)

    def test_valid_multi_task_decomposition(self):
        dec = TaskDecomposition(
            original_prompt="Schedule a meeting AND create a task",
            tasks=[
                self._make_task("CalendarAgent", "schedule_event"),
                self._make_task("TaskAgent", "create_task"),
            ],
            reasoning="Two distinct intents detected",
        )
        assert len(dec.tasks) == 2

    def test_empty_tasks_rejected(self):
        with pytest.raises(ValidationError):
            TaskDecomposition(original_prompt="x", tasks=[])

    def test_empty_prompt_rejected(self):
        with pytest.raises(ValidationError):
            TaskDecomposition(original_prompt="", tasks=[self._make_task()])

    def test_duplicate_task_ids_rejected(self):
        fixed_id = str(uuid.uuid4())
        t1 = A2ATask(
            task_id=fixed_id,
            agent_name="CalendarAgent",
            skill_id="schedule_event",
            prompt="p1",
        )
        t2 = A2ATask(
            task_id=fixed_id,  # duplicate!
            agent_name="TaskAgent",
            skill_id="create_task",
            prompt="p2",
        )
        with pytest.raises(ValidationError, match="unique task_ids"):
            TaskDecomposition(original_prompt="x", tasks=[t1, t2])

    def test_serialisation_round_trip(self):
        dec = TaskDecomposition(
            original_prompt="Do A and B",
            tasks=[
                self._make_task("CalendarAgent", "schedule_event"),
                self._make_task("TaskAgent", "create_task"),
            ],
            reasoning="Two intents",
        )
        data = dec.model_dump(mode="json")
        restored = TaskDecomposition.model_validate(data)
        assert len(restored.tasks) == 2
        assert restored.reasoning == "Two intents"


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------


class TestAgentCard:
    def _make_card(self, **kwargs) -> AgentCard:
        defaults = dict(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:9000",
            skills=[
                AgentSkill(id="test_skill", name="Test", description="desc")
            ],
        )
        defaults.update(kwargs)
        return AgentCard(**defaults)

    def test_valid_card(self):
        card = self._make_card()
        assert card.name == "TestAgent"
        assert card.skill_ids() == ["test_skill"]

    def test_name_with_spaces_rejected(self):
        with pytest.raises(ValidationError, match="must not contain spaces"):
            self._make_card(name="Bad Agent Name")

    def test_invalid_version_rejected(self):
        with pytest.raises(ValidationError, match="SemVer"):
            self._make_card(version="not-a-version")

    def test_empty_skills_rejected(self):
        with pytest.raises(ValidationError):
            self._make_card(skills=[])

    def test_has_skill_true(self):
        card = self._make_card()
        assert card.has_skill("test_skill") is True

    def test_has_skill_false(self):
        card = self._make_card()
        assert card.has_skill("nonexistent_skill") is False

    def test_well_known_json_is_valid_json(self):
        import json
        card = self._make_card()
        raw = card.to_well_known_json()
        parsed = json.loads(raw)
        assert parsed["name"] == "TestAgent"

    def test_card_is_frozen(self):
        card = self._make_card()
        with pytest.raises(Exception):
            card.name = "Other"  # type: ignore[misc]
