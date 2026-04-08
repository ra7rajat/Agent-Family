"""
agent_family.auth.token_store
===============================

Encrypted token storage using cryptography.fernet.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


class EncryptedTokenStore:
    """Stores Google OAuth2 tokens securely using Fernet encryption."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        key_b64 = os.getenv("TOKEN_ENCRYPTION_KEY")
        if not key_b64:
            raise ValueError("TOKEN_ENCRYPTION_KEY environment variable is required")
        
        self.fernet = Fernet(key_b64.encode())
        
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path.home() / ".agent_family" / "tokens"
            
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, service_name: str) -> Path:
        return self.storage_dir / f"{service_name}.enc"

    def save(self, service_name: str, credentials: Credentials) -> None:
        """Encrypts and saves credentials to disk."""
        path = self._get_path(service_name)
        creds_json = credentials.to_json()
        encrypted_data = self.fernet.encrypt(creds_json.encode())
        
        path.write_bytes(encrypted_data)
        # Ensure only the owner can read/write the file
        os.chmod(path, 0o600)
        logger.info(f"Saved encrypted credentials for '{service_name}' to {path}")

    def load(self, service_name: str) -> Credentials | None:
        """Loads and decrypts credentials, refreshing them if expired."""
        path = self._get_path(service_name)
        if not path.exists():
            return None

        try:
            encrypted_data = path.read_bytes()
            decrypted_data = self.fernet.decrypt(encrypted_data)
            creds = Credentials.from_authorized_user_info(json.loads(decrypted_data))

            if creds and creds.expired and creds.refresh_token:
                logger.debug(f"Refreshing expired credentials for '{service_name}'")
                creds.refresh(Request())
                self.save(service_name, creds)  # Save the refreshed token

            return creds
        except Exception as e:
            logger.error(f"Failed to load credentials for '{service_name}': {e}")
            return None

    def delete(self, service_name: str) -> bool:
        """Deletes stored credentials."""
        path = self._get_path(service_name)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted credentials for '{service_name}'")
            return True
        return False
