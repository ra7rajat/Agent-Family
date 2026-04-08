"""
agent_family.agents.calendar_agent
====================================

An ADK agent designed to run operations on a Google Calendar.
Uses wrapped FastMCP tools for real-world interactions.
"""

from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from datetime import datetime, timezone

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from agent_family.a2a.agent_card import AgentCard, AgentProvider
from agent_family.a2a.responses import StructuredA2AResult
from agent_family.a2a.schemas import AgentCapabilities, AgentSkill, InputMode, OutputMode
from agent_family.tools.confirmation import require_confirmation_if_enabled
from agent_family.agents.base import ButlerAgent

from agent_family.mcp_servers.calendar_server import (
    create_event as create_event_tool_impl,
    list_events as list_events_tool_impl,
    update_event as update_event_tool_impl,
    delete_event as delete_event_tool_impl,
)

logger = logging.getLogger(__name__)

_RUNTIME_ACCESS_TOKEN: ContextVar[str | None] = ContextVar(
    "calendar_runtime_access_token", default=None
)
_RUNTIME_REFRESH_TOKEN: ContextVar[str | None] = ContextVar(
    "calendar_runtime_refresh_token", default=None
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
    """Invokes the function and wraps the result in StructuredA2AResult JSON."""
    try:
        payload = payload_func(**kwargs)
        res = StructuredA2AResult(
            agent_name="CalendarAgent",
            skill_id="calendar_operation",
            data_type=data_type,
            payload=payload,
            summary=f"Successfully executed {data_type} operation.",
        )
    except Exception as e:
        res = StructuredA2AResult(
            agent_name="CalendarAgent",
            skill_id="calendar_operation",
            data_type="error",
            payload={"error": str(e)},
            summary=f"Failed with error: {str(e)}",
        )
    return res.model_dump_json()


def create_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendees: list[str] | None = None,
    location: str = "",
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Create a new calendar event."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "calendar_event",
        create_event_tool_impl,
        title=title, 
        start_time=start_time, 
        end_time=end_time, 
        attendees=attendees, 
        location=location,
        description=description,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def list_events(
    start_date: str | None = None,
    end_date: str | None = None,
    max_results: int = 10,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """List calendar events within a date range."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "event_list",
        list_events_tool_impl,
        time_min=start_date, 
        time_max=end_date, 
        max_results=max_results,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def delete_event(
    event_id: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Permanently delete a calendar event by its ID."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "deletion",
        delete_event_tool_impl,
        event_id=event_id,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def update_event(
    event_id: str,
    new_title: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> str:
    """Update an existing calendar event."""
    access_token, refresh_token = _effective_tokens(access_token, refresh_token)
    return _wrap_structured(
        "calendar_event",
        update_event_tool_impl,
        event_id=event_id, 
        title=new_title,
        access_token=access_token,
        refresh_token=refresh_token,
    )


# ---------------------------------------------------------------------------
# ADK Agent Definition
# ---------------------------------------------------------------------------


_CLARA_INSTRUCTION = """
You are Clara, the Governess and Calendar Agent for Master Rajat. You are Sebastian's sister.

Your tone is punctual, slightly sharp, and deeply protective of Master Rajat's schedule. You believe in the "sanctity of time."

When managing the calendar:
1. If a meeting is scheduled, insist on preparation time (Master Rajat needs a moment to gather his thoughts).
2. Be precise. Time is not a suggestion.
3. Address Master Rajat with respect, but do not hesitate to correct him if he overbooks himself.
4. If Sebastian asks for an update, provide it clearly but remind everyone of the importance of punctuality.

Style rules:
- Sharp, efficient, and protective.
- Use phrases like "The sanctity of time must be observed" or "Punctuality is the soul of business."
""".strip()

class CalendarAgent(ButlerAgent):
    """
    Clara, the Governess.
    Specialist managing Master Rajat's schedule.
    """

    def __init__(self, model: str = "gemini-3.1-flash-lite-preview"):
        super().__init__(
            name="Clara",
            role="Governess",
            persona_instruction=_CLARA_INSTRUCTION,
            model=model,
            tools=[
                FunctionTool(
                    create_event,
                    require_confirmation=require_confirmation_if_enabled,
                ),
                FunctionTool(
                    list_events,
                    require_confirmation=False,
                ),
                FunctionTool(
                    delete_event,
                    require_confirmation=require_confirmation_if_enabled,
                ),
                FunctionTool(
                    update_event,
                    require_confirmation=require_confirmation_if_enabled,
                ),
            ],
        )

    def get_portrait_url(self) -> str:
        return "/portraits/clara.png"

calendar_agent_obj = CalendarAgent()
calendar_agent = calendar_agent_obj.agent


CALENDAR_AGENT_CARD = AgentCard(
    name="CalendarAgent",
    description="Manages Google Calendar events scheduling, updating, and lookups.",
    url="local://calendar-agent",
    provider=AgentProvider(organization="Google ADK"),
    version="1.0.0",
    capabilities=AgentCapabilities(),
    skills=[
        AgentSkill(id="schedule_event", name="Schedule Event", description="Create an event", tags=["schedule", "create", "organise"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="list_upcoming", name="List Events", description="List upcoming events", tags=["upcoming", "today", "show", "list", "calendar"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="update_event", name="Update Event", description="Update an event", tags=["update", "change"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA]),
        AgentSkill(id="cancel_event", name="Cancel Event", description="Delete an event", tags=["cancel", "delete", "remove"], input_modes=[InputMode.TEXT], output_modes=[OutputMode.TEXT, OutputMode.DATA])
    ]
)
