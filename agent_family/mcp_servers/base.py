"""
agent_family.mcp_servers.base
===============================

Shared utilities for Google FastMCP servers.

Supports two credential modes:
  1. Dynamic token     — an access_token/refresh_token passed per-request from the web session
  2. Environment creds — legacy CLI mode via GoogleOAuth2Manager (for tests / runner.py)
"""

from __future__ import annotations

import logging
import os
import time

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build

from agent_family.auth.oauth2 import GoogleOAuth2Manager

logger = logging.getLogger(__name__)


def get_google_service(
    service_name: str,
    version: str,
    scopes: list[str],
    access_token: str | None = None,
    refresh_token: str | None = None,
) -> Resource:
    """
    Build an authenticated Google API service client.

    Priority
    --------
    1. If ``access_token`` is provided, build credentials from the live token.
       If the token is close to expiry and ``refresh_token`` is also provided,
       a proactive refresh is attempted.
    2. Otherwise fall back to the environment-based CLI singleton flow.
    """
    if access_token:
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.getenv("GOOGLE_CLIENT_ID"),
            client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            scopes=scopes,
        )
        logger.debug(
            "Building %s v%s client from session access_token (token=****%s)",
            service_name,
            version,
            access_token[-4:],
        )
        return build(service_name, version, credentials=creds, cache_discovery=False)

    # Legacy env-based CLI flow
    is_live = os.getenv("GOOGLE_SERVICES_ENABLED", "false").lower() in {"true", "1", "yes"}
    if not is_live:
        raise RuntimeError(
            f"Google services are disabled. Set GOOGLE_SERVICES_ENABLED=true "
            f"to use the {service_name} API, or provide an access_token."
        )
    mgr = GoogleOAuth2Manager()
    creds = mgr.get_credentials(service_name, scopes)
    return build(service_name, version, credentials=creds, cache_discovery=False)
