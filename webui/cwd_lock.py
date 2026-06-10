"""Thread-safe CWD isolation for background tasks.

The Auth singleton reads from CWD, and os.chdir() is process-global.
This module provides a lock so only one thread mutates CWD at a time,
plus helpers that acquire fresh tokens for a given user without holding
the lock longer than necessary.
"""
import os
import json
import time
import threading
from pathlib import Path

from webui.users import user_dir, PROJECT_DIR

_lock = threading.Lock()
_cache_lock = threading.Lock()
_token_cache: dict[tuple[str, int], tuple[float, dict]] = {}
_TOKEN_CACHE_TTL = 120  # seconds — avoid re-refreshing on every button tap


class _UserCwd:
    """Context manager: chdir into a user dir, reload AuthInstance, yield, chdir back."""

    def __init__(self, username: str):
        self.username = username
        self.prev = None

    def __enter__(self):
        _lock.acquire()
        self.prev = os.getcwd()
        udir = user_dir(self.username)
        udir.mkdir(parents=True, exist_ok=True)
        os.chdir(udir)
        try:
            from app.service.auth import AuthInstance
            AuthInstance.reload_for_current_dir()
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            os.chdir(self.prev or PROJECT_DIR)
        except Exception:
            os.chdir(PROJECT_DIR)
        _lock.release()
        return False


def user_cwd(username: str) -> _UserCwd:
    return _UserCwd(username)


def list_user_accounts(username: str) -> list[dict]:
    """Account metadata from refresh-tokens.json — no network calls."""
    udir = user_dir(username)
    rt_file = udir / "refresh-tokens.json"
    if not rt_file.exists():
        return []
    try:
        entries = json.loads(rt_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    results = []
    for entry in entries:
        msisdn = entry.get("number")
        if not msisdn:
            continue
        results.append({
            "number": int(msisdn),
            "subscriber_id": entry.get("subscriber_id", ""),
            "subscription_type": entry.get("subscription_type", ""),
        })
    return results


def invalidate_user_token_cache(username: str, msisdn: int | None = None) -> None:
    with _cache_lock:
        if msisdn is None:
            keys = [k for k in _token_cache if k[0] == username]
        else:
            keys = [(username, int(msisdn))]
        for key in keys:
            _token_cache.pop(key, None)


def get_user_tokens(username: str, msisdn: int, *, force: bool = False) -> dict | None:
    """Get tokens for one MSISDN. Cached briefly to keep Telegram menus snappy."""
    key = (username, int(msisdn))
    if not force:
        with _cache_lock:
            hit = _token_cache.get(key)
            if hit and (time.time() - hit[0]) < _TOKEN_CACHE_TTL:
                return dict(hit[1])

    with user_cwd(username):
        from app.service.auth import AuthInstance
        try:
            AuthInstance.set_active_user(msisdn)
        except Exception:
            return None
        user = AuthInstance.get_active_user()
        if not user or user.get("number") != msisdn:
            return None
        tokens = dict(user["tokens"])

    with _cache_lock:
        _token_cache[key] = (time.time(), tokens)
    return tokens


def get_all_user_tokens(username: str) -> list[dict]:
    """Tokens for all accounts — uses per-number cache when possible."""
    results = []
    for entry in list_user_accounts(username):
        tokens = get_user_tokens(username, entry["number"])
        if tokens:
            results.append({**entry, "tokens": tokens})
    return results


def get_api_key() -> str:
    from app.util import ensure_api_key
    return ensure_api_key()
