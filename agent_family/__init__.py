"""
agent_family — Google ADK multi-agent system with A2A protocol.

Package init: expose top-level convenience imports.
"""

from agent_family.a2a.schemas import (
    A2AMessage,
    A2AResponse,
    A2ATask,
    AgentCapabilities,
    AgentSkill,
    TaskDecomposition,
    TaskStatus,
)
from agent_family.a2a.agent_card import AgentCard
from agent_family.registry.registry import AgentRegistry

__all__ = [
    "AgentCard",
    "AgentCapabilities",
    "AgentRegistry",
    "AgentSkill",
    "A2AMessage",
    "A2AResponse",
    "A2ATask",
    "TaskDecomposition",
    "TaskStatus",
]

__version__ = "0.1.0"
