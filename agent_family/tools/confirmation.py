"""
agent_family.tools.confirmation
=================================

Human-In-The-Loop (HITL) helper functions.
"""

from __future__ import annotations

import os


def is_hitl_enabled() -> bool:
    """Returns True if the HITL_ENABLED env var is 'true'."""
    val = os.getenv("HITL_ENABLED", "false").lower()
    return val in {"true", "1", "yes"}


def require_confirmation_if_enabled(*args, **kwargs) -> bool:
    """
    A callable for ADK FunctionTool.require_confirmation.
    Returns True (prompt user) only if HITL_ENABLED is set.

    Accepts arbitrary args/kwargs because ADK may pass tool parameters
    either as a dict or expanded keyword arguments.
    """
    return is_hitl_enabled()
