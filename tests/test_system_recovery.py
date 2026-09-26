"""Tests for WebBoilerSystem's outage handling.

These cover the orchestration that had no coverage before: what happens when
the HTTP API is healthy but the realtime websocket is not. That combination is
ordinary in the field (a blocked port 15671, a broker restart) and it used to
produce two compounding failures: the exponential backoff never engaged,
because a relogin was recorded as successful before the websocket had actually
come up; and the periodic HTTP refresh stopped running, so every entity went
unavailable although its data was still perfectly reachable.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler import WebBoilerSystem  # noqa: E402


class _StubClient:
    """Minimal stand-in for WebBoilerClient's orchestration surface."""

    def __init__(self, *, websocket_starts: bool = True, relogin_ok: bool = True, refresh_ok: bool = True) -> None:
        self._websocket_starts = websocket_starts
        self._relogin_ok = relogin_ok
        self._refresh_ok = refresh_ok
        self.connected = False
        self.running = False
        self.refresh_calls = 0
        self.start_websocket_calls = 0
        self.relogin_calls = 0
        self.http_client = SimpleNamespace()
        # _annotate_devices() walks this; an empty collection is enough, the
        # tests here are about the retry and refresh decisions.
        self.data: dict = {}

    def is_websocket_connected(self) -> bool:
        return self.connected

    def is_websocket_running(self) -> bool:
        return self.running

    def websocket_disconnected_for(self) -> float:
        return 0.0 if self.connected else 3600.0

    async def close_websocket(self) -> bool:
        return True

    async def relogin(self) -> bool:
        self.relogin_calls += 1
        return self._relogin_ok

    async def start_websocket(self, _callback) -> None:
        self.start_websocket_calls += 1
        if not self._websocket_starts:
            raise ConnectionError("Timed out waiting for websocket CONNECTED frame")
        self.connected = True
        self.running = True

    async def refresh(self) -> bool:
        self.refresh_calls += 1
        return self._refresh_ok


def _make_system(client: _StubClient) -> WebBoilerSystem:
    entry = SimpleNamespace(options={}, data={}, entry_id="test", async_start_reauth=lambda hass: None)
    system = WebBoilerSystem(
        hass=None,
        entry=entry,
        username="user@example.com",
        password="secret",
        prefix="",
    )
    system.web_boiler_client = client
    return system


def test_relogin_backs_off_when_the_websocket_does_not_come_up() -> None:
    """HTTP login succeeding is not enough to call a relogin successful.

    Recording success there reset the backoff counter on every attempt, so a
    websocket-only outage was retried at the base interval indefinitely.
    """

    async def runner() -> None:
        client = _StubClient(websocket_starts=False)
        system = _make_system(client)

        await system.relogin()
        await system.relogin()

        assert client.start_websocket_calls == 2
        assert system._relogin_attempt == 2
        assert system._current_retry_delay() > system.retry_base_interval

    asyncio.run(runner())


def test_relogin_still_refreshes_over_http_when_the_websocket_fails() -> None:
    """A websocket that will not start must not abort the rest of the relogin."""

    async def runner() -> None:
        client = _StubClient(websocket_starts=False)
        system = _make_system(client)

        await system.relogin()

        assert client.refresh_calls == 1

    asyncio.run(runner())


def test_relogin_resets_backoff_once_the_websocket_is_back() -> None:
    async def runner() -> None:
        client = _StubClient(websocket_starts=True)
        system = _make_system(client)
        system._relogin_attempt = 5

        await system.relogin()

        assert system._relogin_attempt == 0
        assert client.refresh_calls == 1

    asyncio.run(runner())


def test_tick_keeps_polling_http_while_the_websocket_is_down() -> None:
    """Entities stay available on HTTP data alone during a websocket outage.

    The refresh used to be skipped entirely once the reconnect task had died,
    which is exactly when it matters most.
    """

    async def runner() -> None:
        client = _StubClient(websocket_starts=False)
        system = _make_system(client)
        client.connected = False
        client.running = False
        system.last_refresh_timestamp = time.monotonic() - (system.refresh_interval + 60)
        # Not yet due for a relogin, so this tick can only either refresh or
        # do nothing at all.
        system.last_relogin_timestamp = time.monotonic()

        await system.tick()

        assert client.refresh_calls == 1
        assert client.relogin_calls == 0

    asyncio.run(runner())


def test_tick_does_not_relogin_twice_for_one_failed_refresh_while_disconnected() -> None:
    """The disconnected path owns relogin scheduling; a failed refresh there
    must not bypass the backoff with an immediate extra attempt."""

    async def runner() -> None:
        client = _StubClient(websocket_starts=False, refresh_ok=False)
        system = _make_system(client)
        client.connected = False
        client.running = False
        system.last_refresh_timestamp = time.monotonic() - (system.refresh_interval + 60)
        system.last_relogin_timestamp = time.monotonic()

        await system.tick()

        assert client.refresh_calls == 1
        assert client.relogin_calls == 0

    asyncio.run(runner())
