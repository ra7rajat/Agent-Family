"""
agent_family.registry.registry
================================

Thread-safe singleton AgentRegistry.

The registry is the central directory service that the Master Agent uses
to discover sub-agents and resolve user intents to specific agent skills.

Design decisions
----------------
* **Singleton** – guaranteed by ``__new__`` guard; safe for in-process use.
* **Thread-safe** – registration and lookup are protected by ``threading.Lock``.
* **Async-ready** – all public async methods delegate to sync helpers.
* **Intent resolution** – uses keyword / tag matching across all registered
  skill IDs and tags; returns the best (agent_name, skill_id) pair.

Usage::

    registry = AgentRegistry()           # always the same instance
    registry.register(calendar_card)
    registry.register(task_card)

    agent_name, skill_id = registry.resolve_intent("schedule a meeting tomorrow")
    card = registry.get("CalendarAgent")
"""

from __future__ import annotations

import logging
import threading
from typing import ClassVar

from agent_family.a2a.agent_card import AgentCard

logger = logging.getLogger(__name__)


class RegistrationError(Exception):
    """Raised when an invalid or duplicate AgentCard is registered."""


class ResolutionError(Exception):
    """Raised when no matching agent/skill can be found for an intent."""


class AgentRegistry:
    """
    Singleton registry that maps agent names → AgentCards and resolves
    natural-language intents to (agent_name, skill_id) pairs.

    Examples
    --------
    >>> r1 = AgentRegistry()
    >>> r2 = AgentRegistry()
    >>> assert r1 is r2          # guaranteed singleton
    """

    # ── Singleton machinery ───────────────────────────────────────────────────
    _instance: ClassVar[AgentRegistry | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __new__(cls) -> AgentRegistry:
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._registry: dict[str, AgentCard] = {}
                instance._rw_lock = threading.RLock()
                logger.debug("AgentRegistry singleton created")
                cls._instance = instance
        return cls._instance  # type: ignore[return-value]

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, card: AgentCard, *, overwrite: bool = False) -> None:
        """
        Register an AgentCard with the registry.

        Parameters
        ----------
        card:
            A fully validated AgentCard instance.
        overwrite:
            If False (default), raises RegistrationError when a card with
            the same name is already registered. Set True to update.

        Raises
        ------
        RegistrationError
            If ``card.name`` is already registered and ``overwrite=False``.
        """
        with self._rw_lock:
            if card.name in self._registry and not overwrite:
                raise RegistrationError(
                    f"Agent {card.name!r} is already registered. "
                    "Pass overwrite=True to replace it."
                )
            self._registry[card.name] = card
            logger.info(
                "Registered agent %r at %s with skills: %s",
                card.name,
                card.url,
                card.skill_ids(),
            )

    def unregister(self, name: str) -> None:
        """Remove an agent from the registry by name."""
        with self._rw_lock:
            if name not in self._registry:
                raise KeyError(f"Agent {name!r} is not registered")
            del self._registry[name]
            logger.info("Unregistered agent %r", name)

    # ── Lookup ────────────────────────────────────────────────────────────────

    def get(self, name: str) -> AgentCard:
        """
        Retrieve an AgentCard by exact name.

        Raises
        ------
        KeyError
            If no agent with that name is registered.
        """
        with self._rw_lock:
            try:
                return self._registry[name]
            except KeyError:
                raise KeyError(
                    f"Agent {name!r} not found. Registered agents: {self.list_names()}"
                ) from None

    def list_names(self) -> list[str]:
        """Return a snapshot of all registered agent names."""
        with self._rw_lock:
            return list(self._registry.keys())

    def list_all(self) -> list[AgentCard]:
        """Return a snapshot of all registered AgentCards."""
        with self._rw_lock:
            return list(self._registry.values())

    def is_registered(self, name: str) -> bool:
        """Return True if an agent with ``name`` is registered."""
        with self._rw_lock:
            return name in self._registry

    # ── Intent resolution ─────────────────────────────────────────────────────

    def resolve_intent(self, intent: str) -> tuple[str, str]:
        """
        Map a natural-language intent string to the best (agent_name, skill_id).

        Resolution strategy (scored, highest wins):
        1. Direct skill-ID match in the intent text        → +10 pts
        2. Agent name mentioned in the intent text         → +5 pts
        3. Skill tag keyword found in the intent text      → +3 pts per tag
        4. Skill example phrase found in the intent text   → +7 pts per example

        Parameters
        ----------
        intent:
            The natural-language intention, e.g.
            "schedule a meeting tomorrow at 3pm"

        Returns
        -------
        (agent_name, skill_id) tuple for the best match.

        Raises
        ------
        ResolutionError
            If no registered agent has any matching skill.
        """
        intent_lower = intent.lower()
        best_score = -1
        best: tuple[str, str] | None = None

        with self._rw_lock:
            cards = list(self._registry.values())

        for card in cards:
            agent_name_score = 5 if card.name.lower() in intent_lower else 0

            for skill in card.skills:
                score = agent_name_score

                # Direct skill-id match
                if skill.id in intent_lower:
                    score += 10

                # Tag keyword matches
                for tag in skill.tags:
                    if tag.lower() in intent_lower:
                        score += 3

                # Example phrase matches
                for example in skill.examples:
                    if any(word in intent_lower for word in example.lower().split()):
                        score += 7

                logger.debug(
                    "Intent score for (%s, %s): %d", card.name, skill.id, score
                )

                if score > best_score:
                    best_score = score
                    best = (card.name, skill.id)

        if best is None or best_score == 0:
            raise ResolutionError(
                f"Could not resolve intent {intent!r} to any registered agent skill. "
                f"Registered agents: {[c.name for c in cards]}"
            )

        logger.info(
            "Resolved intent %r → agent=%r, skill=%r (score=%d)",
            intent,
            best[0],
            best[1],
            best_score,
        )
        return best

    def resolve_all(self, intent: str) -> list[tuple[str, str, int]]:
        """
        Return *all* (agent_name, skill_id, score) matches sorted by score desc.

        Useful for debugging and testing intent routing.
        """
        intent_lower = intent.lower()
        results: list[tuple[str, str, int]] = []

        with self._rw_lock:
            cards = list(self._registry.values())

        for card in cards:
            agent_name_score = 5 if card.name.lower() in intent_lower else 0

            for skill in card.skills:
                score = agent_name_score
                if skill.id in intent_lower:
                    score += 10
                for tag in skill.tags:
                    if tag.lower() in intent_lower:
                        score += 3
                for example in skill.examples:
                    if any(word in intent_lower for word in example.lower().split()):
                        score += 7
                results.append((card.name, skill.id, score))

        results.sort(key=lambda x: x[2], reverse=True)
        return results

    # ── Admin ─────────────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all registrations. Primarily useful in tests."""
        with self._rw_lock:
            self._registry.clear()
            logger.warning("AgentRegistry cleared")

    @classmethod
    def reset_singleton(cls) -> None:
        """
        Destroy the singleton instance.

        **Test-only**: call this in pytest fixtures to get a fresh registry
        between tests. Do NOT use in production code.
        """
        with cls._lock:
            cls._instance = None
            logger.warning("AgentRegistry singleton reset (test-only)")

    def __repr__(self) -> str:
        return f"<AgentRegistry agents={self.list_names()}>"

    def __len__(self) -> int:
        return len(self._registry)
