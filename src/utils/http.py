"""
Shared HTTP helper for the data clients.

The Parliament APIs occasionally fail transiently even when the same
request succeeds moments later — observed directly against the live Bills
API on 2026-07-26, in two different forms: a plain 500 response, and (during
a long batch fetch) a dropped connection (requests.exceptions.ConnectionError,
"Connection reset by peer") that never got as far as an HTTP response at
all. Both are retried; a real 4xx (the request itself is wrong) is not.
"""

import time

import requests


def get_json(url, params=None, max_retries=3, retry_delay_seconds=1):
    """
    GET a URL and return its parsed JSON body, retrying on transient server
    errors (5xx) and dropped-connection errors.

    Args:
        url: full URL to request.
        params: optional dict of query params.
        max_retries: total attempts before giving up.
        retry_delay_seconds: pause between attempts (doubles each retry).

    Returns:
        Parsed JSON (dict or list).

    Raises:
        requests.exceptions.RequestException: if every attempt fails, or if
            the response is a 4xx (not retried).
    """
    delay = retry_delay_seconds

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, params=params)
        except requests.exceptions.ConnectionError:
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= 2
            continue

        if response.status_code < 500:
            response.raise_for_status()
            return response.json()

        if attempt == max_retries:
            response.raise_for_status()

        time.sleep(delay)
        delay *= 2
