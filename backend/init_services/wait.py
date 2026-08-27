from __future__ import annotations

import time
from collections.abc import Callable

import httpx


def wait_for(name: str, check: Callable[[], bool], timeout_s: float = 60, interval_s: float = 2) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if check():
                print(f"[ok] {name}")
                return True
        except Exception as exc:  # noqa: BLE001
            last = exc
        else:
            last = None
        time.sleep(interval_s)
    print(f"[skip] {name} not ready ({last})")
    return False


def http_ok(url: str, *, verify: bool = True, auth: tuple[str, str] | None = None) -> Callable[[], bool]:
    def _check() -> bool:
        response = httpx.get(url, timeout=5, verify=verify, auth=auth)
        return response.status_code < 500

    return _check
