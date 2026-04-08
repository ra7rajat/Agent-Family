"""
tests/test_registry.py
========================

Unit tests for the AgentRegistry singleton.

Tests cover:
  - Singleton identity guarantee
  - Thread safety (concurrent registrations)
  - Registration, get, unregister, list
  - Duplicate registration enforcement
  - overwrite=True behaviour
  - clear() and reset_singleton() isolation
  - __len__, __repr__
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from agent_family.a2a.agent_card import AgentCard, AgentProvider
from agent_family.a2a.schemas import AgentSkill
from agent_family.registry.registry import AgentRegistry, RegistrationError, ResolutionError
from tests.conftest import make_card, make_skill


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_same_instance(self, isolated_registry):
        r1 = AgentRegistry()
        r2 = AgentRegistry()
        assert r1 is r2

    def test_singleton_after_reset(self):
        AgentRegistry.reset_singleton()
        r1 = AgentRegistry()
        AgentRegistry.reset_singleton()
        r2 = AgentRegistry()
        assert r1 is not r2  # different instances after reset

    def test_reset_clears_data(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        assert len(isolated_registry) == 1
        AgentRegistry.reset_singleton()
        fresh = AgentRegistry()
        assert len(fresh) == 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_single_agent(self, isolated_registry):
        card = make_card("Agent1")
        isolated_registry.register(card)
        assert isolated_registry.is_registered("Agent1")

    def test_register_multiple_agents(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        isolated_registry.register(make_card("Beta", url="http://localhost:9001"))
        assert len(isolated_registry) == 2
        assert set(isolated_registry.list_names()) == {"Alpha", "Beta"}

    def test_duplicate_registration_raises(self, isolated_registry):
        card = make_card("Alpha")
        isolated_registry.register(card)
        with pytest.raises(RegistrationError, match="already registered"):
            isolated_registry.register(card)

    def test_overwrite_true_replaces_card(self, isolated_registry):
        card_v1 = make_card("Alpha")
        card_v2 = AgentCard(
            name="Alpha",
            description="Updated Alpha",
            url="http://localhost:9999",
            skills=[make_skill("new_skill")],
        )
        isolated_registry.register(card_v1)
        isolated_registry.register(card_v2, overwrite=True)
        retrieved = isolated_registry.get("Alpha")
        assert retrieved.url == "http://localhost:9999"
        assert retrieved.has_skill("new_skill")

    def test_unregister(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        isolated_registry.unregister("Alpha")
        assert not isolated_registry.is_registered("Alpha")

    def test_unregister_nonexistent_raises(self, isolated_registry):
        with pytest.raises(KeyError, match="not registered"):
            isolated_registry.unregister("Nonexistent")

    def test_list_all_returns_copies(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        all_cards = isolated_registry.list_all()
        assert len(all_cards) == 1
        assert all_cards[0].name == "Alpha"


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestLookup:
    def test_get_existing_agent(self, isolated_registry):
        card = make_card("MyAgent")
        isolated_registry.register(card)
        retrieved = isolated_registry.get("MyAgent")
        assert retrieved.name == "MyAgent"

    def test_get_nonexistent_raises_key_error(self, isolated_registry):
        with pytest.raises(KeyError, match="not found"):
            isolated_registry.get("Nonexistent")

    def test_is_registered_true(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        assert isolated_registry.is_registered("Alpha") is True

    def test_is_registered_false(self, isolated_registry):
        assert isolated_registry.is_registered("Nope") is False

    def test_list_names_empty(self, isolated_registry):
        assert isolated_registry.list_names() == []

    def test_len(self, isolated_registry):
        assert len(isolated_registry) == 0
        isolated_registry.register(make_card("One"))
        assert len(isolated_registry) == 1
        isolated_registry.register(make_card("Two", url="http://localhost:9001"))
        assert len(isolated_registry) == 2

    def test_repr(self, isolated_registry):
        isolated_registry.register(make_card("Alpha"))
        r = repr(isolated_registry)
        assert "AgentRegistry" in r
        assert "Alpha" in r


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_registrations_no_race(self, isolated_registry):
        """Register 50 agents from 50 threads simultaneously — no errors."""
        errors: list[Exception] = []

        def register_agent(n: int) -> None:
            try:
                isolated_registry.register(
                    make_card(f"Agent{n:03d}", url=f"http://localhost:{9000+n}")
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=register_agent, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(isolated_registry) == 50

    def test_concurrent_reads_consistent(self, isolated_registry):
        """Concurrent reads during writes don't error."""
        isolated_registry.register(make_card("Stable", url="http://localhost:9999"))
        results: list[bool] = []

        def read_agent():
            try:
                _ = isolated_registry.is_registered("Stable")
                results.append(True)
            except Exception:
                results.append(False)

        threads = [threading.Thread(target=read_agent) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_registry(self, isolated_registry):
        isolated_registry.register(make_card("One"))
        isolated_registry.register(make_card("Two", url="http://localhost:9001"))
        assert len(isolated_registry) == 2
        isolated_registry.clear()
        assert len(isolated_registry) == 0

    def test_clear_then_register_works(self, isolated_registry):
        isolated_registry.register(make_card("One"))
        isolated_registry.clear()
        isolated_registry.register(make_card("Two"))
        assert isolated_registry.list_names() == ["Two"]
