"""
Simple local caching for raw API responses, so re-running the pipeline
doesn't repeatedly hit the Parliament APIs and so raw data stays inspectable
in data/raw/.

Deliberately simple: no expiry logic, no database. Just save/load a JSON
file per (client_name, cache_key). If you need fresher data later, delete
the relevant file(s) in data/raw/ or pass use_cache=False from the caller.
"""

import json
import os
import re

# data/raw/ lives at the project root, three levels up from this file
# (src/utils/cache.py -> src/utils -> src -> project root).
DATA_RAW_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "raw",
)


def _cache_path(client_name, cache_key):
    """Build a safe file path for a given client/cache_key pair."""
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", cache_key)
    client_dir = os.path.join(DATA_RAW_DIR, client_name)
    os.makedirs(client_dir, exist_ok=True)
    return os.path.join(client_dir, f"{safe_key}.json")


def save_response(client_name, cache_key, data):
    """
    Save a raw (already-parsed) API response to data/raw/<client_name>/<cache_key>.json.

    Args:
        client_name: name of the data client, e.g. "members_client".
        cache_key: identifies this specific request, e.g. an endpoint + params
            summary. Non-alphanumeric characters are replaced so it's always
            a safe filename.
        data: JSON-serialisable data (list/dict) to save.
    """
    path = _cache_path(client_name, cache_key)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_cached_response(client_name, cache_key):
    """
    Load a previously cached response, if one exists.

    Returns:
        The cached data (list/dict), or None if nothing is cached yet.
    """
    path = _cache_path(client_name, cache_key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)
