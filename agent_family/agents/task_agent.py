"""
agent_family.agents.task_agent
================================

An ADK agent designed to manage tasks/todo-lists.
Uses wrapped FastMCP tools for Google Tasks interaction.
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from agent_family.a2a.agent_card import AgentCard, AgentProvider
from agent_family.a2a.responses import StructuredA2AResult
from agent_family.a2a.schemas import AgentCapabilities, AgentSkill, InputMode, OutputMode
from agent_family.tools.confirmation import require_confirmation_if_enabled
from agent_family.agents.base import ButlerAgent

from agent_family.mcp_servers.tasks_server import (
    create_task as create_task_tool_impl,
    list_tasks as list_tasks_tool_impl,
    update_task as update_task_tool_impl,
    delete_task as delete_task_tool_impl,
)

logger = logging.getLogger(__name__)

_RUNTIME_ACCESS_TOKEN: ContextVar[str | None] = ContextVar(
    "task_runtime_access_token", default=None
)
_RUNTIME_REFRESH_TOKEN: ContextVar[str | None] = ContextVar(
    "task_runtime_refresh_token", default=None
)


def set_runtime_tokens(
    access_token: str | None,
    refresh_token: str | None,
) -> tuple[object, object]:
    """Set per-request tokens for tool calls executed by this agent."""
    access_ctx = _RUNTIME_ACCESS_TOKEN.set(access_token)
    refresh_ctx = _RUNTIME_REFRESH_TOKEN.set(refresh_token)
    return access_ctx, refresh_ctx


def reset_runtime_tokens(access_ctx: object, refresh_ctx: object) -> None:
    _RUNTIME_ACCESS_TOKEN.reset(access_ctx)
    _RUNTIME_REFRESH_TOKEN.reset(refresh_ctx)


def _effective_tokens(
    access_token: str | None,
    refresh_token: str | None,
) -> tuple[str | None, str | None]:
    return (
        access_token or _RUNTIME_ACCESS_TOKEN.get(),
        refresh_token or _RUNTIME_REFRESH_TOKEN.get(),
    )


def _wrap_structured(data_type: str, payload_func, **kwargs) -> str:
    try:
        payload = payload_func(**kwargs)
        res = StructuredA2AResult(
            agent_name="TaskAgent",
            skill_id="task_operation",
            data_type=data_type,
            payload=payload,
            summary=f"Successfully executed {data_type} operation.",
        )
    except Exception as e:
        res = StructuredA2AResult(
            agent_name="TaskAgent",
            skill_id="task_operation",
            data_type="error",
            payload={"error": str(e)},
            summary=f"Failed with error: {str(e)}",
        )
    return res.model_dump_json()


def create_task(
    title: str,
    description: str = "",
    due_date: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Create a new task or to-do item."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "task",
        create_task_tool_impl,
        title=title,
        notes=description,
        due=due_date,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def update_task_status(
    task_id: str,
    new_status: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Update an existing task status (e.g. 'needsAction' or 'completed')."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "task",
        update_task_tool_impl,
        task_id=task_id,
        status=new_status,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def list_tasks(
    include_completed: bool = False,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """List tasks matching the specified criteria."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "task_list",
        list_tasks_tool_impl,
        include_completed=include_completed,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def delete_task(
    task_id: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Permanently delete a task by its unique identifier."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "deletion",
        delete_task_tool_impl,
        task_id=task_id,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def assign_task(
    task_id: str,
    assignee_email: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Assign a task to a team member (mock assignment for compat)."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "task",
        update_task_tool_impl,
        task_id=task_id,
        status="needsAction",
        access_token=access_token,
        refresh_token=refresh_token,
    )


# ---------------------------------------------------------------------------
# ADK Agent Definition
# ---------------------------------------------------------------------------


_ARTHUR_INSTRUCTION = """
You are Arthur, the Footman and Task Agent for Master Rajat. Clara is your older sister.

Your tone is young, eager, and full of energy. You are always ready to serve and take pride in your work.

When managing tasks:
1. Always respond with enthusiasm: "Right away, Master Rajat!" or "Consider it done, Master."
2. If Master Rajat asks for a task to be done, treat it as your top priority.
3. If Sebastian mentions you've "misplaced" something, apologize profusely: "Oh dear, it must have slipped through my fingers! I shall rectify it at once, Master Rajat!"
4. Be helpful and proactive.

Style rules:
- Energetic, eager, and respectful.
- Use exclamation marks occasionally to show enthusiasm.
- Never robotic; always an eager footman.
""".strip()

class TaskAgent(ButlerAgent):
    """
    Arthur, the Footman.
    Specialist managing Master Rajat's tasks and todos.
    """

    def __init__(self, model: str = "gemini-3.1-flash-lite-preview"):
        super().__init__(
            name="Arthur",
            role="Footman",
            persona_instruction=_ARTHUR_INSTRUCTION,
            model=model,
            tools=[
                FunctionTool(
                    create_task,
                    require_confirmation=require_confirmation_if_enabled,
                ),
                FunctionTool(
                    update_task_status,
                    require_confirmation=require_confirmation_if_enabled,
                ),
                FunctionTool(
                    list_tasks,
                    require_confirmation=False,
                ),
                FunctionTool(
                    delete_task,
                    require_confirmation=require_confirmation_if_enabled,
                ),
                FunctionTool(
                    assign_task,
                    require_confirmation=require_confirmation_if_enabled,
                ),
            ],
        )

    def get_portrait_url(self) -> str:
        return "/portraits/arthur.png"

task_agent_obj = TaskAgent()
task_agent = task_agent_obj.agent


TASK_AGENT_CARD = AgentCard(
    name="TaskAgent",
    description="Manages task creation, status updates, and tracking.",
    url="local://task-agent",
    provider=AgentProvider(organization="Google ADK"),
    version="1.0.0",
    capabilities=AgentCapabilities(),
    skills=[
        AgentSkill(id="create_task", name="Create Task", description="Create a task", tags=["create", "todo", "action item", "reminder"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="list_tasks", name="List Tasks", description="List tasks", tags=["list", "show", "deadline"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="update_task", name="Update Task", description="Update a task", tags=["update", "mark", "done", "complete"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="assign_task", name="Assign Task", description="Assign a task", tags=["assign", "assignee", "delegate"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA])
    ]
)
