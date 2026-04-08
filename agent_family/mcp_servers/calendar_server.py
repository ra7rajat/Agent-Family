"""
agent_family.mcp_servers.calendar_server
==========================================

FastMCP server for Google Calendar.
Tools accept an optional ``access_token`` for session-aware authentication.
"""

from __future__ import annotations

import datetime

from fastmcp import FastMCP

from agent_family.a2a.responses import CalendarEventData
from agent_family.mcp_servers.base import get_google_service
from agent_family.tools.backoff import google_api_retry

CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

mcp = FastMCP("GoogleCalendar")


def _get_service(access_token: str | None = None, refresh_token: str | None = None):
    return get_google_service(
        "calendar", "v3", CALENDAR_SCOPES,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def _format_event(item: dict) -> CalendarEventData:
    start = item.get("start", {}).get("dateTime", item.get("start", {}).get("date", ""))
    end = item.get("end", {}).get("dateTime", item.get("end", {}).get("date", ""))
    attendees = [a.get("email") for a in item.get("attendees", []) if "email" in a]
    return CalendarEventData(
        event_id=item["id"],
        title=item.get("summary", "Untitled"),
        start=start,
        end=end,
        attendees=attendees,
        meet_link=item.get("hangoutLink"),
        html_link=item.get("htmlLink", ""),
    )


@mcp.tool()
@google_api_retry
def list_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 10,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> list[dict]:
    """
    List upcoming Google Calendar events.
    Dates must be ISO format, e.g. 2025-04-10T10:00:00Z
    """
    service = _get_service(access_token, refresh_token)
    if not time_min:
        time_min = datetime.datetime.now(datetime.timezone.utc).isoformat()
    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return [_format_event(item).model_dump() for item in events_result.get("items", [])]


@mcp.tool()
@google_api_retry
def create_event(
    title: str,
    start_time: str,
    end_time: str,
    attendees: list[str] | None = None,
    location: str | None = None,
    description: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """
    Create a new event on the primary calendar.
    Times must be ISO format, e.g. '2025-04-10T14:30:00Z'.
    """
    service = _get_service(access_token, refresh_token)
    body: dict = {
        "summary": title,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
        "conferenceData": {
            "createRequest": {
                "requestId": f"adk-{datetime.datetime.now().timestamp()}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    if location:
        body["location"] = location
    if description:
        body["description"] = description

    event = service.events().insert(
        calendarId="primary", body=body, conferenceDataVersion=1
    ).execute()
    return _format_event(event).model_dump()


@mcp.tool()
@google_api_retry
def update_event(
    event_id: str,
    title: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """Update an existing calendar event."""
    service = _get_service(access_token, refresh_token)
    event = service.events().get(calendarId="primary", eventId=event_id).execute()
    if title:
        event["summary"] = title
    event = service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()
    return _format_event(event).model_dump()


@mcp.tool()
@google_api_retry
def delete_event(
    event_id: str,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """Delete an event from the calendar."""
    service = _get_service(access_token, refresh_token)
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"status": "deleted", "event_id": event_id}


if __name__ == "__main__":
    mcp.run()
