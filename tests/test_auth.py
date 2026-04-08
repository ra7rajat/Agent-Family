import pytest
import os
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet
from agent_family.auth.token_store import EncryptedTokenStore
from agent_family.auth.oauth2 import GoogleOAuth2Manager


@pytest.fixture
def temp_token_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def mock_env_key():
    key = Fernet.generate_key().decode()
    os.environ["TOKEN_ENCRYPTION_KEY"] = key
    yield key
    del os.environ["TOKEN_ENCRYPTION_KEY"]


def test_encrypted_token_store_save_load(temp_token_dir, mock_env_key):
    store = EncryptedTokenStore(temp_token_dir)
    
    mock_creds = MagicMock()
    mock_creds.to_json.return_value = '{"token": "fake"}'
    
    # Save
    store.save("test_service", mock_creds)
    
    # Check it actually wrote a file
    assert os.path.exists(os.path.join(temp_token_dir, "test_service.enc"))
    
    # Load
    with patch('agent_family.auth.token_store.Credentials.from_authorized_user_info') as mock_from_info:
        mock_from_info.return_value = mock_creds
        loaded = store.load("test_service")
        assert loaded == mock_creds
        mock_from_info.assert_called_with({"token": "fake"})

def test_google_oauth2_missing_env_vars(mock_env_key):
    GoogleOAuth2Manager.reset_singleton()
    with patch.dict(os.environ, {"TOKEN_ENCRYPTION_KEY": mock_env_key}, clear=True):
        m = GoogleOAuth2Manager()
        with pytest.raises(ValueError):
            m._get_client_config()

def test_google_oauth2_manager_singleton():
    GoogleOAuth2Manager.reset_singleton()
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "a", "GOOGLE_CLIENT_SECRET": "b", "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode()}):
        m1 = GoogleOAuth2Manager()
        m2 = GoogleOAuth2Manager()
        assert m1 is m2

