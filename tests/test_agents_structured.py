import pytest
from unittest.mock import MagicMock, AsyncMock

from agent_family.agents.master_agent import MasterAgent
from agent_family.a2a.schemas import TaskDecomposition, A2ATask, TaskStatus

@pytest.mark.asyncio
async def test_master_agent_structured_parsing():
    master = MasterAgent()
    master._call_gemini_for_decomposition = AsyncMock(return_value=TaskDecomposition(
        decomposition_id="123",
        original_prompt="test",
        reasoning="test reasoning",
        tasks=[
            A2ATask(
                task_id="t1",
                agent_name="TaskAgent",
                skill_id="create_task",
                prompt="create it",
                parameters={"title": "X"},
                priority=5
            )
        ]
    ))
    
    # Mock the full a2a sub-invocation response
    master._invoke_sub_agent = AsyncMock(return_value="Done")
    
    # Mock registry so the skill validation passes
    mock_card = MagicMock()
    mock_card.has_skill.return_value = True
    master.registry.get = MagicMock(return_value=mock_card)
    
    response = await master.run("user says make X")
    
    assert response.overall_status == "success"
    assert len(response.results) == 1
    assert response.results[0].agent_name == "TaskAgent"
    assert response.results[0].output == "Done"
    assert response.results[0].status == TaskStatus.COMPLETED

