from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from .HttpClient import HttpClient, HttpClientAuthError, HttpClientConnectionError
from .HttpHelper import HttpHelper
from .WebBoilerDeviceCollection import WebBoilerDeviceCollection
from .WebBoilerWsClient import WebBoilerWsClient
from .logging_utils import redact_account


class WebBoilerClient:
    def __init__(self, hass=None):
        self.hass = hass
        self.logger = logging.getLogger(__name__)
        self.websocket_connected = False
        self.connectivity_callbacks: dict[str, Callable[[bool], Awaitable[None]]] = {}
        self.ws_client = WebBoilerWsClient(
            hass,
            self.ws_connected_callback,
            self.ws_disconnected_callback,
            self.ws_error_callback,
            self.ws_data_callback,
        )
        self.on_parameter_updated_callback = None
        self.log_account = "account-unknown"

    async def login(self, username, password):
        self.logger.info("WebBoilerClient - Logging in... (%s)", redact_account(username))
        self.username = username
        self.log_account = redact_account(username)
        self.password = password
        self.http_client = HttpClient(self.username, self.password)
        self.http_helper = HttpHelper(self.http_client)
        self.data = WebBoilerDeviceCollection(username)
        return await self.http_client.login()

    async def get_configuration(self):
        await self.http_client.get_installations()
        if self.http_helper.get_device_count() == 0:
            self.logger.warning("WebBoilerClient - there is no installed device (%s)", self.log_account)
            return False
        self.data.parse_installations(self.http_client.installations)
        await asyncio.gather(self.http_client.get_configuration(), self.http_client.get_widgetgrid_list())
        tasks = [
            self.http_client.get_widgetgrid(self.http_client.widgetgrid_list["selected"]),
            self.http_client.get_installation_status_all(self.http_helper.get_all_devices_ids()),
            self.http_client.get_notifications(),
        ]
        for serial in self.http_helper.get_all_devices_serials():
            tasks.append(self.http_client.get_parameter_list(serial))
        await asyncio.gather(*tasks)
        await self.data.parse_installation_statuses(self.http_client.installation_status_all)
        self.data.parse_parameter_lists(self.http_client.parameter_list)
        self.data.parse_grid(self.http_client)
        return True

    async def close_websocket(self) -> bool:
        try:
            await self.ws_client.close()
            return True
        except Exception as e:
            self.logger.error("WebBoilerClient::close_websocket failed %s (%s)", str(e), getattr(self, 'log_account', 'account-unknown'))
            return False

    async def close(self) -> None:
        await self.close_websocket()
        http_client = getattr(self, 'http_client', None)
        if http_client is not None:
            await http_client.close_session()

    async def start_websocket(self, on_parameter_updated_callback):
        self.logger.info("WebBoilerClient - Starting websocket... (%s)", self.log_account)
        self.on_parameter_updated_callback = on_parameter_updated_callback
        await self.ws_client.start(self.username)

    async def refresh(self, delay=2) -> bool:
        try:
            for id_ in self.http_helper.get_all_devices_ids():
                await self.http_client.refresh_device(id_)
                await asyncio.sleep(delay)
                await self.http_client.rstat_all_device(id_)
                await asyncio.sleep(delay)
            return True
        except HttpClientAuthError:
            raise
        except HttpClientConnectionError as e:
            self.logger.warning("WebBoilerClient::refresh failed: %s (%s)", e, self.log_account)
            return False
        except Exception as e:
            self.logger.warning("WebBoilerClient::refresh failed: %s (%s)", e, self.log_account)
            return False

    async def _notify_connectivity(self):
        for callback in list(self.connectivity_callbacks.values()):
            await callback(self.websocket_connected)

    async def ws_connected_callback(self, ws, frame):
        self.logger.info("WebBoilerClient - connected (%s)", self.log_account)
        self.websocket_connected = True
        await self._notify_connectivity()
        await self.ws_client.subscribe_to_notifications(ws)
        for serial in self.http_helper.get_all_devices_serials():
            device = self.data.get_device_by_serial(serial)
            await self.ws_client.subscribe_to_installation(ws, device)
        self.data.set_on_update_callback(self.on_parameter_updated_callback)
        await self.data.notify_all_updated()

    async def ws_disconnected_callback(self, ws, close_status_code, close_msg):
        self.websocket_connected = False
        await self._notify_connectivity()
        await self.data.notify_all_updated()
        log_level = logging.INFO
        if close_status_code not in (None, 1000, 1001):
            log_level = logging.WARNING
        self.logger.log(
            log_level,
            "WebBoilerClient - disconnected close_status_code:%s close_msg:%s (%s)",
            close_status_code,
            close_msg,
            self.log_account,
        )

    async def ws_error_callback(self, ws, err):
        self.logger.error("WebBoilerClient - error err:%s (%s)", err, self.log_account)

    async def ws_data_callback(self, ws, stomp_frame):
        await self.data.parse_real_time_frame(stomp_frame)

    def is_websocket_connected(self) -> bool:
        return self.websocket_connected

    def is_websocket_running(self) -> bool:
        return self.ws_client.is_running()

    async def relogin(self):
        await self.http_client.close_session()
        await self.http_client.reinitialize_session()
        return await self.http_client.login()

    async def turn(self, serial, on):
        device = self.data.get_device_by_serial(serial)
        try:
            response = await self.http_client.turn_device_by_id(device["id"], on)
            return response.get("status") == "success"
        except Exception as e:
            self.logger.error("WebBoilerClient::turn failed: %s (%s)", e, self.log_account)
            return False

    async def turn_circuit(self, serial, circuit, on):
        device = self.data.get_device_by_serial(serial)
        try:
            response = await self.http_client.turn_device_circuit(device["id"], circuit, on)
            return response.get("status") == "success"
        except Exception as e:
            self.logger.error("WebBoilerClient::turn_circuit failed: %s (%s)", e, self.log_account)
            return False

    def set_connectivity_callback(self, connectivity_callback, update_key="default"):
        if connectivity_callback is None:
            self.connectivity_callbacks.pop(update_key, None)
        else:
            self.connectivity_callbacks[update_key] = connectivity_callback
