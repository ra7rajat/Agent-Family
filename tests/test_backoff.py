import pytest
from tenacity import RetryError
from agent_family.tools.backoff import google_api_retry

import googleapiclient.errors
import httplib2

def test_google_api_retry_success():
    call_count = 0
    
    @google_api_retry
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        return "success"
        
    assert mock_api_call() == "success"
    assert call_count == 1

def test_google_api_retry_429():
    call_count = 0
    resp = httplib2.Response({"status": 429})
    
    @google_api_retry
    def mock_api_call():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise googleapiclient.errors.HttpError(resp, b"Rate limit exceeded")
        return "success"
        
    # Should succeed on 3rd try
    assert mock_api_call() == "success"
    assert call_count == 3
