"""Tests for the entity-availability signal and telemetry timestamps on
WebBoilerClient. These methods are read by every sensor and switch's
``available`` property, so a regression silently breaks every entity in HA.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "centrometal_boiler"))

from centrometal_web_boiler.WebBoilerClient import WebBoilerClient  # noqa: E402


def _make_client() -> WebBoilerClient:
    return WebBoilerClient(hass=None)


def test_has_fresh_data_false_when_never_connected() -> None:
    c = _make_client()
    c.last_successful_http_refresh = None
    c.websocket_connected = False
    assert c.has_fresh_data() is False


def test_has_fresh_data_true_when_websocket_connected() -> None:
    c = _make_client()
    c.last_successful_http_refresh = None
    c.websocket_connected = True
    assert c.has_fresh_data() is True


def test_has_fresh_data_true_with_recent_http_refresh() -> None:
    c = _make_client()
    c.websocket_connected = False
    c.last_successful_http_refresh = time.monotonic() - 30  # 30s ago
    assert c.has_fresh_data(max_age=300) is True


def test_has_fresh_data_false_with_stale_http_refresh() -> None:
    c = _make_client()
    c.websocket_connected = False
    c.last_successful_http_refresh = time.monotonic() - 1000  # >5min ago
    assert c.has_fresh_data(max_age=300) is False


def test_websocket_disconnected_for_zero_when_connected() -> None:
    c = _make_client()
    c.websocket_connected = True
    c.disconnected_since = None
    assert c.websocket_disconnected_for() == 0.0


def test_websocket_disconnected_for_returns_elapsed() -> None:
    c = _make_client()
    c.websocket_connected = False
    c.disconnected_since = time.monotonic() - 60
    elapsed = c.websocket_disconnected_for()
    assert 50 < elapsed < 70  # ~60s, allowing for execution time


def test_has_fresh_data_false_when_the_socket_is_connected_but_silent() -> None:
    """A connected socket that stopped delivering is not a source of data.

    The broker can keep the TCP connection and the pings alive while it has
    quietly stopped forwarding the installation topic. Trusting the
    "connected" flag on its own kept every entity available and showing
    hours-old values as current.
    """
    c = _make_client()
    c.websocket_connected = True
    c.last_websocket_message = time.monotonic() - 1000
    c.last_successful_http_refresh = None
    assert c.websocket_is_stale(max_age=300) is True
    assert c.has_fresh_data(max_age=300) is False


def test_recent_http_refresh_keeps_a_silent_socket_available() -> None:
    """The normal idle case: no realtime traffic, but polling still works."""
    c = _make_client()
    c.websocket_connected = True
    c.last_websocket_message = time.monotonic() - 1000
    c.last_successful_http_refresh = time.monotonic() - 30
    assert c.has_fresh_data(max_age=300) is True


def test_websocket_message_age_is_none_before_any_message() -> None:
    c = _make_client()
    assert c.websocket_message_age() is None
    # Nothing observed yet is not the same as stale.
    assert c.websocket_is_stale() is False


def test_freshness_window_can_follow_a_longer_refresh_interval() -> None:
    """The window must outlast the gap between two scheduled refreshes.

    With a fixed 300 s window and a 240 s interval the two were close enough
    that tick jitter alone could push an entity to unavailable between
    refreshes; a longer configured interval would have done it every time.
    """
    c = _make_client()
    c.freshness_window = 480.0
    c.websocket_connected = False
    c.last_successful_http_refresh = time.monotonic() - 400
    assert c.has_fresh_data() is True
    # An explicit argument still wins, and a genuinely dead integration still
    # goes unavailable.
    assert c.has_fresh_data(max_age=300) is False
    c.last_successful_http_refresh = time.monotonic() - 600
    assert c.has_fresh_data() is False
