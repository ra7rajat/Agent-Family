"""
agent_family.tools.backoff
============================

Exponential backoff decorators for Google API rate limits.
"""

from __future__ import annotations

import logging
from typing import Any

from googleapiclient.errors import HttpError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_random_exponential,
)

logger = logging.getLogger(__name__)


def is_rate_limit_error(exception: BaseException) -> bool:
    """True if the exception is an HttpError with status 429 or 503."""
    if isinstance(exception, HttpError):
        return exception.resp.status in {429, 503}
    return False


# Standard retry decorator for Google API calls
google_api_retry = retry(
    retry=retry_if_exception(is_rate_limit_error),
    wait=wait_random_exponential(multiplier=1, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
