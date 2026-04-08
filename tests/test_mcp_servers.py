import pytest

from agent_family.mcp_servers.calendar_server import mcp as calendar_mcp
from agent_family.mcp_servers.tasks_server import mcp as tasks_mcp

@pytest.mark.asyncio
async def test_calendar_server_tools_registered():
    tools_obj = await calendar_mcp.list_tools()
    tools = [t.name for t in tools_obj]
    assert "list_events" in tools
    assert "create_event" in tools
    assert "update_event" in tools
    assert "delete_event" in tools

@pytest.mark.asyncio
async def test_tasks_server_tools_registered():
    tools_obj = await tasks_mcp.list_tools()
    tools = [t.name for t in tools_obj]
    assert "list_tasks" in tools
    assert "create_task" in tools
    assert "update_task" in tools
    assert "delete_task" in tools
