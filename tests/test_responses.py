import pytest
from pydantic import ValidationError
from agent_family.a2a.responses import StructuredA2AResult, CalendarEventData, TaskData

def test_structured_a2a_result():
    res = StructuredA2AResult(
        agent_name="CalendarAgent",
        skill_id="event_created",
        data_type="calendar_event",
        payload={"id": "123", "summary": "Test"},
        summary="Event created."
    )
    assert res.agent_name == "CalendarAgent"
    
    # Must fail without required fields
    with pytest.raises(ValidationError):
        StructuredA2AResult(agent_name="Only")

def test_calendar_event_data():
    cal = CalendarEventData(
        event_id="abc",
        title="Standup",
        start="2024-01-01T10:00:00Z",
        end="2024-01-01T10:30:00Z",
        attendees=[],
        html_link="http://link"
    )
    assert cal.event_id == "abc"

def test_task_data():
    task = TaskData(
        task_id="abc",
        title="Buy milk",
        status="needsAction",
        task_list_id="@default"
    )
    assert task.due is None
