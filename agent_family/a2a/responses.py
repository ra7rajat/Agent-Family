"""
agent_family.a2a.responses
============================

Structured Pydantic schemas for the artifacts field in A2AResult.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CalendarEventData(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    title: str
    start: str
    end: str
    attendees: list[str]
    meet_link: str | None = None
    html_link: str


class TaskData(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str
    title: str
    status: str
    due: str | None = None
    notes: str | None = None
    task_list_id: str


class StructuredA2AResult(BaseModel):
    """
    Standardised payload that sub-agents return to the Master Agent.
    This sits inside the 'data' field of an A2APart returned by ADK.
    """
    model_config = ConfigDict(frozen=True)

    agent_name: str
    skill_id: str
    data_type: Literal["calendar_event", "task", "event_list", "task_list", "deletion", "error"]
    payload: CalendarEventData | TaskData | list[CalendarEventData] | list[TaskData] | dict
    summary: str  # human-readable fallback for logs/UI
