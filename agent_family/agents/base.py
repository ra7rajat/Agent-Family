"""
agent_family.agents.base
========================

Base classes and interfaces for the Butler Family agents.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from google.adk.agents import LlmAgent
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class ButlerAgent(ABC):
    """
    Base class for all agents in the Butler Family.
    Enforces persona consistency and provides A2A channelling.
    """

    def __init__(
        self,
        name: str,
        role: str,
        persona_instruction: str,
        model: str = "gemini-3.1-flash-lite-preview",
        tools: list[Any] = None,
    ):
        self.name = name
        self.role = role
        self.persona_instruction = persona_instruction
        self.model = model
        
        # Initialize the underlying ADK LlmAgent
        self._llm_agent = LlmAgent(
            name=name,
            model=model,
            description=f"{role} in the AI Butler Family",
            instruction=persona_instruction,
            tools=tools or [],
        )

    @property
    def agent(self) -> LlmAgent:
        return self._llm_agent

    async def speak(self, prompt: str, **kwargs) -> str:
        """
        Execute a turn with the agent's persona.
        """
        logger.info(f"{self.name} is speaking...")
        # In a real ADK setup, we'd use self._llm_agent.run() or similar.
        # Here we delegate to the inner agent's capability.
        return await self._llm_agent.run(prompt, **kwargs)

    @abstractmethod
    def get_portrait_url(self) -> str:
        """Return the URL to the agent's portrait."""
        pass
