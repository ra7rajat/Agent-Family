"""
agent_family.mcp_servers.tasks_server
=======================================

FastMCP server for Google Tasks.
Tools accept an optional ``access_token`` for session-aware authentication.
"""

from __future__ import annotations

from fastmcp import FastMCP

from agent_family.a2a.responses import TaskData
from agent_family.mcp_servers.base import get_google_service
from agent_family.tools.backoff import google_api_retry

TASKS_SCOPES = ["https://www.googleapis.com/auth/tasks"]

mcp = FastMCP("GoogleTasks")


def _get_service(access_token: str | None = None, refresh_token: str | None = None):
    return get_google_service(
        "tasks", "v1", TASKS_SCOPES,
        access_token=access_token,
        refresh_token=refresh_token,
    )


def _format_task(item: dict) -> TaskData:
    return TaskData(
        task_id=item["id"],
        title=item.get("title", "Untitled"),
        status=item.get("status", "needsAction"),
        due=item.get("due"),
        notes=item.get("notes"),
        task_list_id=item.get("taskListId", "@default"),
    )


@mcp.tool()
@google_api_retry
def list_task_lists(
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> list[dict]:
    """List available Google Task lists."""
    service = _get_service(access_token, refresh_token)
    results = service.tasklists().list().execute()
    items = results.get("items", [])
    return [
        {"id": item.get("id"), "title": item.get("title", "Untitled")}
        for item in items
        if item.get("id")
    ]


@mcp.tool()
@google_api_retry
def list_tasks(
    task_list_id: str = "@default",
    include_completed: bool = False,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> list[dict]:
    """Retrieve tasks from a specific list."""
    service = _get_service(access_token, refresh_token)
    results = service.tasks().list(
        tasklist=task_list_id, showCompleted=include_completed
    ).execute()
    items = results.get("items", [])
    for i in items:
        i["taskListId"] = task_list_id
    return [_format_task(i).model_dump() for i in items]


@mcp.tool()
@google_api_retry
def create_task(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """
    Create a new task in the default list.
    due: ISO 8601 format, e.g. "2025-04-10T12:00:00.000Z"
    """
    service = _get_service(access_token, refresh_token)
    body: dict[str, str] = {"title": title}
    if notes:
        body["notes"] = notes
    if due:
        body["due"] = due
    result = service.tasks().insert(tasklist="@default", body=body).execute()
    result["taskListId"] = "@default"
    return _format_task(result).model_dump()


@mcp.tool()
@google_api_retry
def update_task(
    task_id: str,
    status: str | None = None,
    task_list_id: str = "@default",
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """
    Update an existing task.
    status: 'needsAction' (incomplete) or 'completed'
    """
    service = _get_service(access_token, refresh_token)
    task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
    if status is not None:
        task["status"] = status
    updated = service.tasks().update(
        tasklist=task_list_id, task=task_id, body=task
    ).execute()
    updated["taskListId"] = task_list_id
    return _format_task(updated).model_dump()


@mcp.tool()
@google_api_retry
def delete_task(
    task_id: str,
    task_list_id: str = "@default",
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> dict:
    """Delete a task."""
    service = _get_service(access_token, refresh_token)
    service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
    return {"status": "deleted", "task_id": task_id}


if __name__ == "__main__":
    mcp.run()
