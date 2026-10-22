"""Run the integration inside a real Home Assistant (pytest-homeassistant-custom-component),
connected to a local fake of the Centrometal cloud instead of web-boiler.com."""

from __future__ import annotations

import importlib
import pathlib
import sys
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestServer
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

# custom_components/ must be importable to be patched.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# The client package re-exports its classes under the same names as their
# modules, so the modules are fetched explicitly: the URLs are module globals.
_PACKAGE = "custom_components.centrometal_boiler.centrometal_web_boiler"
http_client_module = importlib.import_module(f"{_PACKAGE}.HttpClient")
ws_client_module = importlib.import_module(f"{_PACKAGE}.WebBoilerWsClient")
WebBoilerClient = importlib.import_module(f"{_PACKAGE}.WebBoilerClient").WebBoilerClient

from .fake_centrometal import EMAIL, PASSWORD, PELTEC2, FakeBroker, FakeWebsite  # noqa: E402

DOMAIN = "centrometal_boiler"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def boilers():
    return [PELTEC2]


@pytest.fixture
async def website(boilers, socket_enabled):
    fake = FakeWebsite(boilers)
    server = TestServer(fake.app, host="127.0.0.1")
    await server.start_server()
    fake.url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


@pytest.fixture
async def broker(socket_enabled):
    fake = FakeBroker()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def cloud(website, broker):
    """Point the integration's client at the fake cloud.

    Only test plumbing is patched: the two URLs, the realtime socket's TLS
    context (the fake broker speaks plain ws://), and the one-second pauses a
    refresh leaves between its control commands.
    """
    original_refresh = WebBoilerClient.refresh

    async def fast_refresh(self, delay: float = 1.0) -> bool:
        return await original_refresh(self, delay=0)

    async def no_tls(self):
        return None

    with (
        patch.object(http_client_module, "WEB_BOILER_WEBROOT", website.url),
        patch.object(ws_client_module, "WEB_BOILER_STOMP_URL", broker.url),
        patch.object(ws_client_module.WebBoilerWsClient, "_create_ssl_context", no_tls),
        patch.object(WebBoilerClient, "refresh", fast_refresh),
    ):
        yield website


@pytest.fixture
def entry_options():
    return {}


@pytest.fixture
async def entry(hass, cloud, entry_options):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=EMAIL,
        title="PelTec II Lambda",
        data={"email": EMAIL, "password": PASSWORD, "prefix": ""},
        options=entry_options,
    )
    entry.add_to_hass(hass)
    yield entry
    # Unload, otherwise the tick timer and the websocket outlive the test.
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
