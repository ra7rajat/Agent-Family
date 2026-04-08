"""
agent_family.a2a.agent_card
===========================

AgentCard — the A2A discovery manifest for a remote agent.

An AgentCard is served at ``/.well-known/agent-card.json`` by each
sub-agent service. It tells orchestrators:
  - What the agent is and where to reach it
  - What skills it has
  - What capabilities it supports (streaming, push, etc.)
  - What authentication scheme it requires

Spec: https://github.com/google-a2a/A2A/blob/main/specification/json/a2a.json
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from agent_family.a2a.schemas import AgentCapabilities, AgentSkill


class AgentProvider(BaseModel):
    """Identifies the organisation or team that created the agent."""

    model_config = {"frozen": True}

    organization: str = Field(..., description="Organisation name")
    url: str | None = Field(default=None, description="Organisation URL")


class AgentAuthentication(BaseModel):
    """Authentication requirements for reaching this agent's A2A endpoint."""

    model_config = {"frozen": True}

    schemes: list[str] = Field(
        default=["none"],
        description="Supported auth schemes, e.g. ['none', 'bearer', 'oauth2']",
    )
    credentials: str | None = Field(
        default=None,
        description="Serialised credential or reference (leave None for open agents)",
    )


class AgentCard(BaseModel):
    """
    Full A2A AgentCard compliant with the A2A specification.

    This is the canonical description of a sub-agent exposed to the
    Master Agent and any other A2A clients.

    Usage::

        card = AgentCard(
            name="CalendarAgent",
            description="Manages Google Calendar events",
            url="http://localhost:8001",
            version="1.0.0",
            skills=[...],
        )
        print(card.to_well_known_json())
    """

    model_config = {"frozen": True}

    # ── Identity ──────────────────────────────────────────────────────────────
    name: str = Field(..., description="Unique agent name used as registry key")
    description: str = Field(..., description="What this agent does")
    version: str = Field(default="1.0.0", description="SemVer-style version string")

    # ── Network ───────────────────────────────────────────────────────────────
    url: str = Field(
        ...,
        description="Base URL where this agent's A2A endpoint is hosted",
    )

    # ── Provider ──────────────────────────────────────────────────────────────
    provider: AgentProvider = Field(
        default_factory=lambda: AgentProvider(organization="Agent Family"),
    )

    # ── Capabilities & Skills ─────────────────────────────────────────────────
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = Field(..., min_length=1)

    # ── Auth ──────────────────────────────────────────────────────────────────
    authentication: AgentAuthentication = Field(
        default_factory=AgentAuthentication,
    )

    # ── Discovery metadata ────────────────────────────────────────────────────
    default_input_mode: str = Field(default="text")
    default_output_mode: str = Field(default="text")
    documentation_url: str | None = Field(
        default=None,
        description="Link to this agent's documentation",
    )

    @field_validator("name")
    @classmethod
    def name_no_spaces(cls, v: str) -> str:
        if " " in v.strip():
            raise ValueError(f"AgentCard name must not contain spaces, got: {v!r}")
        return v.strip()

    @field_validator("version")
    @classmethod
    def valid_semver(cls, v: str) -> str:
        parts = v.split(".")
        if not (1 <= len(parts) <= 3) or not all(p.isdigit() for p in parts):
            raise ValueError(f"version must be SemVer (e.g. '1.0.0'), got: {v!r}")
        return v

    # ── Helpers ───────────────────────────────────────────────────────────────

    def skill_ids(self) -> list[str]:
        """Return list of all skill IDs this agent exposes."""
        return [s.id for s in self.skills]

    def has_skill(self, skill_id: str) -> bool:
        """Return True if this agent has the requested skill."""
        return skill_id.lower() in self.skill_ids()

    def to_well_known_dict(self) -> dict[str, Any]:
        """Serialize to the ``/.well-known/agent-card.json`` shape."""
        return self.model_dump(mode="json", exclude_none=True)

    def to_well_known_json(self, *, indent: int = 2) -> str:
        """Return a pretty-printed JSON string of the AgentCard."""
        return json.dumps(self.to_well_known_dict(), indent=indent)

    def __repr__(self) -> str:
        return f"<AgentCard name={self.name!r} url={self.url!r} skills={self.skill_ids()}>"
