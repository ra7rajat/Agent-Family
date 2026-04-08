"""
agent_family.a2a.schemas
========================

Pydantic v2 strict schemas for the Agent-to-Agent (A2A) protocol.

A2A uses JSON-RPC 2.0 over HTTP/HTTPS with SSE for streaming.
This module implements the core data models described in:
  https://github.com/google-a2a/A2A/blob/main/specification/json/a2a.json

Key types
---------
AgentSkill          – A single capability an agent exposes
AgentCapabilities   – Feature flags for the A2A handshake
A2ATask             – A single discrete work unit destined for one agent
A2AMessage          – A JSON-RPC 2.0 request envelope
A2AResponse         – A JSON-RPC 2.0 response envelope
TaskDecomposition   – Master Agent output: list of parallel A2A tasks
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Lifecycle states for an A2A task."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InputMode(str, Enum):
    """Supported input modalities for agent skills."""

    TEXT = "text"
    FILE = "file"
    DATA = "data"


class OutputMode(str, Enum):
    """Supported output modalities for agent skills."""

    TEXT = "text"
    FILE = "file"
    DATA = "data"


# ---------------------------------------------------------------------------
# Agent Skill
# ---------------------------------------------------------------------------


class AgentSkill(BaseModel):
    """
    Describes a single capability that an agent exposes.

    Conforms to the A2A AgentCard ``skills`` array element schema.
    """

    model_config = {"strict": True, "frozen": True}

    id: str = Field(..., description="Machine-readable skill identifier, e.g. 'schedule_event'")
    name: str = Field(..., description="Human-readable skill name")
    description: str = Field(..., description="What this skill does")
    tags: list[str] = Field(default_factory=list, description="Discovery tags")
    input_modes: list[InputMode] = Field(
        default=[InputMode.TEXT],
        description="Acceptable input modalities",
    )
    output_modes: list[OutputMode] = Field(
        default=[OutputMode.TEXT],
        description="Produced output modalities",
    )
    examples: list[str] = Field(
        default_factory=list,
        description="Example prompts that trigger this skill",
    )

    @field_validator("id")
    @classmethod
    def id_must_be_snake_case(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Skill id must be snake_case alphanumeric, got: {v!r}")
        return v.lower()


# ---------------------------------------------------------------------------
# Agent Capabilities
# ---------------------------------------------------------------------------


class AgentCapabilities(BaseModel):
    """Feature flags exchanged during A2A discovery / handshake."""

    model_config = {"strict": True}

    streaming: bool = Field(default=False, description="Supports SSE streaming responses")
    push_notifications: bool = Field(default=False, description="Supports push-notification callbacks")
    state_transition_history: bool = Field(
        default=True,
        description="Returns task state-transition history in responses",
    )
    multi_turn: bool = Field(default=True, description="Supports multi-turn conversations")


# ---------------------------------------------------------------------------
# A2A Task (work unit dispatched to a sub-agent)
# ---------------------------------------------------------------------------


class A2ATask(BaseModel):
    """
    A single discrete work unit destined for exactly one sub-agent.

    The Master Agent decomposes complex user prompts into a list of
    these tasks which are then dispatched concurrently.
    """

    model_config = {"strict": False}  # allow flexible input from LLM

    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique task identifier (UUIDv4)",
    )
    agent_name: str = Field(
        ...,
        description="Target agent name as registered in AgentRegistry",
    )
    skill_id: str = Field(
        ...,
        description="Skill on the target agent to invoke",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description="Natural-language instruction for the sub-agent",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured parameters extracted from the user prompt",
    )
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Execution priority (1=low, 10=critical)",
    )
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @field_validator("agent_name")
    @classmethod
    def agent_name_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("agent_name must not be blank")
        return v.strip()

    @field_validator("skill_id")
    @classmethod
    def skill_id_snake_case(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError(f"skill_id must be snake_case alphanumeric, got: {v!r}")
        return v.lower()


# ---------------------------------------------------------------------------
# A2A Message (JSON-RPC 2.0 request envelope)
# ---------------------------------------------------------------------------


class A2APart(BaseModel):
    """A single content part in an A2A message (text, file, data)."""

    model_config = {"strict": False}

    type: Literal["text", "file", "data"] = "text"
    text: str | None = None
    data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def at_least_one_content(self) -> A2APart:
        if self.text is None and self.data is None:
            raise ValueError("A2APart must have either 'text' or 'data'")
        return self


class A2AMessage(BaseModel):
    """
    JSON-RPC 2.0 request message sent from the Master Agent to a sub-agent.

    This wraps an A2ATask inside the standard wire format.
    """

    model_config = {"strict": False}

    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str = Field(
        default="tasks/send",
        description="A2A JSON-RPC method name",
    )
    params: A2ATask = Field(..., description="The task payload")

    @field_validator("method")
    @classmethod
    def valid_method(cls, v: str) -> str:
        allowed = {"tasks/send", "tasks/get", "tasks/cancel", "tasks/sendSubscribe"}
        if v not in allowed:
            raise ValueError(f"method must be one of {allowed}, got: {v!r}")
        return v


# ---------------------------------------------------------------------------
# A2A Response (JSON-RPC 2.0 response envelope)
# ---------------------------------------------------------------------------


class A2AResult(BaseModel):
    """The result payload inside an A2AResponse."""

    model_config = {"strict": False}

    task_id: str
    agent_name: str
    status: TaskStatus
    output: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def output_required_when_completed(self) -> A2AResult:
        if self.status == TaskStatus.COMPLETED and self.output is None:
            raise ValueError("output is required when status is COMPLETED")
        return self


class A2AError(BaseModel):
    """JSON-RPC 2.0 error object."""

    model_config = {"strict": True}

    code: int
    message: str
    data: dict[str, Any] | None = None


class A2AResponse(BaseModel):
    """
    JSON-RPC 2.0 response envelope returned by a sub-agent to the Master.
    """

    model_config = {"strict": False}

    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: A2AResult | None = None
    error: A2AError | None = None

    @model_validator(mode="after")
    def exactly_one_of_result_or_error(self) -> A2AResponse:
        if self.result is None and self.error is None:
            raise ValueError("A2AResponse must contain either 'result' or 'error'")
        if self.result is not None and self.error is not None:
            raise ValueError("A2AResponse cannot contain both 'result' and 'error'")
        return self


# ---------------------------------------------------------------------------
# Task Decomposition (Master Agent structured output)
# ---------------------------------------------------------------------------


class TaskDecomposition(BaseModel):
    """
    The structured output produced by the Master Agent after parsing a
    complex user prompt. Contains one or more A2ATasks to be dispatched
    concurrently to sub-agents.
    """

    model_config = {"strict": False}

    decomposition_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_prompt: str = Field(..., min_length=1)
    tasks: list[A2ATask] = Field(
        ...,
        min_length=1,
        description="Ordered list of tasks (may execute in parallel)",
    )
    reasoning: str = Field(
        default="",
        description="Master Agent's explanation of how it split the prompt",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("tasks")
    @classmethod
    def no_duplicate_task_ids(cls, tasks: list[A2ATask]) -> list[A2ATask]:
        ids = [t.task_id for t in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("All tasks in a decomposition must have unique task_ids")
        return tasks
