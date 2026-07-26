"""
Shared HTTP helper for the data clients.

The Parliament APIs occasionally return a transient 500 even when the same
request succeeds moments later (observed directly against the live Bills
API on 2026-07-26). Retrying a few times on server errors (5xx) is a
reasonable thing to do at this system boundary; client errors (4xx) mean
the request itself is wrong and are not retried.
"""

import time

import requests


def get_json(url, params=None, max_retries=3, retry_delay_seconds=1):
    """
    GET a URL and return its parsed JSON body, retrying on transient
    server errors (5xx).

    Args:
        url: full URL to request.
        params: optional dict of query params.
        max_retries: total attempts before giving up.
        retry_delay_seconds: pause between attempts (doubles each retry).

    Returns:
        Parsed JSON (dict or list).

    Raises:
        requests.exceptions.HTTPError: if every attempt fails, or if the
            response is a 4xx (not retried).
    """
    delay = retry_delay_seconds

    for attempt in range(1, max_retries + 1):
        response = requests.get(url, params=params)

        if response.status_code < 500:
            response.raise_for_status()
            return response.json()

        if attempt == max_retries:
            response.raise_for_status()

        time.sleep(delay)
        delay *= 2
