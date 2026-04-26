from __future__ import annotations

import datetime
import json
import logging
from json import JSONDecodeError
import time
from typing import Any

from .const import WEB_BOILER_STOMP_DEVICE_TOPIC, WEB_BOILER_STOMP_NOTIFICATION_TOPIC
from .logging_utils import redact_account


def _normalize_timestamp(timestamp: Any) -> int:
    if timestamp is None:
        return int(time.time())
    if isinstance(timestamp, (int, float)):
        return int(timestamp)

    value = str(timestamp).strip()
    if not value:
        return int(time.time())
    if value.isdigit():
        return int(value)

    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.datetime.strptime(value, fmt)
            return int(parsed.replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            continue

    return int(time.time())


def _decode_json_body(body: str) -> dict[str, Any]:
    cleaned = body.strip().rstrip("\x00")
    decoder = json.JSONDecoder()
    try:
        data, end = decoder.raw_decode(cleaned)
    except JSONDecodeError as first_err:
        # Corruption pattern: two STOMP frames merged (missing \x00 separator).
        # The JSON is valid up to a point, then garbled.  Try to salvage the
        # valid prefix so sensor values aren't dropped unnecessarily.
        data = _salvage_json_prefix(cleaned, first_err)
        if data is None:
            raise
        return data

    remainder = cleaned[end:].strip()
    if remainder:
        logging.getLogger(__name__).debug(
            "Ignoring trailing realtime payload data after JSON body: %r", remainder
        )
    if not isinstance(data, dict):
        raise ValueError("Realtime payload must decode to a JSON object")
    return data


def _salvage_json_prefix(cleaned: str, original_err: JSONDecodeError) -> dict[str, Any] | None:
    """Try to recover a valid JSON object from the prefix of a corrupted body.

    When two STOMP frames are merged (the \\x00 terminator between them is lost),
    the body looks like valid JSON up to a point, then contains garbage from the
    next frame's headers/body.  We work backwards from the corruption point to
    find the last complete key-value pair and close the object there.
    """
    logger = logging.getLogger(__name__)
    pos = min(original_err.pos, len(cleaned)) if original_err.pos else len(cleaned)

    search_zone = cleaned[:pos]
    for cut in range(len(search_zone) - 1, 0, -1):
        if search_zone[cut] != ',':
            continue
        candidate = search_zone[:cut] + '}'
        try:
            obj = json.loads(candidate)
        except (JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or len(obj) < 2:
            continue
        logger.info(
            "Salvaged %d key(s) from corrupted realtime payload "
            "(corruption at char %d, truncated at char %d)",
            len(obj), pos, cut,
        )
        return obj

    return None


class WebBoilerParameter(dict):
    def __init__(self):
        self.update_callbacks = dict()

    def set_update_callback(self, update_callback, update_key="default"):
        if update_callback is None:
            if update_key in self.update_callbacks.keys():
                del self.update_callbacks[update_key]
        else:
            self.update_callbacks[update_key] = update_callback

    async def update(self, name, value, timestamp=None):
        self["name"] = name
        self["value"] = value
        self["timestamp"] = timestamp
        await self.notify_updated()

    async def notify_updated(self):
        for callback in list(self.update_callbacks.values()):
            await callback(self)


class WebBoilerDevice(dict):
    def __init__(self, username):
        self.logger = logging.getLogger(__name__)
        self.username = username
        self.log_account = redact_account(username)
        self["parameters"] = {}
        self["temperatures"] = {}
        self["info"] = {}
        self["weather"] = {}
        self["circuits"] = {}
        self["widgets"] = {}

    def has_parameter(self, name):
        return name in self["parameters"].keys()

    def create_parameter(self, name, value="?"):
        self["parameters"][name] = WebBoilerParameter()
        self["parameters"][name]["name"] = name
        self["parameters"][name]["value"] = value
        return self["parameters"][name]

    def get_parameter(self, name):
        if name not in self["parameters"].keys():
            self.logger.debug(
                "WebBoilerDevice::get_parameter parameter %s does not exist, creating one (%s)",
                name,
                self.log_account,
            )
            return self.create_parameter(name)
        return self["parameters"][name]

    def get_or_create_parameter(self, name):
        if name not in self["parameters"].keys():
            return self.create_parameter(name)
        return self["parameters"][name]

    def get_widget_by_template(self, template):
        for widget in self["widgets"].values():
            if widget["template"] == template:
                return widget
        return None

    async def update_parameter(self, name, value, timestamp=None) -> "WebBoilerParameter":
        normalized_timestamp = _normalize_timestamp(timestamp)
        parameter = self.get_or_create_parameter(name)
        await parameter.update(name, value, normalized_timestamp)
        return parameter


class WebBoilerDeviceCollection(dict):
    def __init__(self, username, on_update_callback=None, update_key="default"):
        self.logger = logging.getLogger(__name__)
        self.username = username
        self.log_account = redact_account(username)
        self.on_update_callbacks = dict()
        self.set_on_update_callback(on_update_callback, update_key)

    def set_on_update_callback(self, on_update_callback, update_key="default"):
        if on_update_callback is None:
            if update_key in self.on_update_callbacks.keys():
                del self.on_update_callbacks[update_key]
        else:
            self.on_update_callbacks[update_key] = on_update_callback

    async def notify_all_updated(self):
        for on_update_callback in list(self.on_update_callbacks.values()):
            for device in self.values():
                parameters = device["parameters"]
                for parameter in list(parameters.values()):
                    await on_update_callback(device, parameter, True)
                    await parameter.notify_updated()

    def get_device_by_id(self, id):
        for device in self.values():
            if str(id) == str(device["id"]):
                return device
        raise Exception(f"No device with id:{id}")

    def get_device_by_serial(self, serial):
        for device in self.values():
            if str(serial) == str(device["serial"]):
                return device
        raise Exception(f"No device with serial:{serial}")

    def parse_installations(self, installations: dict):
        for device in installations:
            serial = device["label"]
            self.logger.info("Creating device %s (%s)", serial, self.log_account)
            self[serial] = WebBoilerDevice(self.log_account)
            self[serial]["id"] = device["value"]
            self[serial]["serial"] = device["label"]
            self[serial]["place"] = device["place"]
            self[serial]["address"] = device["address"]
            self[serial]["type"] = device["type"]
            self[serial]["product"] = device["product"]

    async def parse_installation_statuses(self, installation_status_all: dict):
        for device_id, value in installation_status_all.items():
            device = self.get_device_by_id(device_id)
            for group, data in value.items():
                if group == "installation":
                    device["country"] = data["country"]
                    device["countryCode"] = data["countryCode"]
                elif group == "params":
                    for param_id, param_data in data.items():
                        await device.update_parameter(param_id, param_data.get("v"), param_data.get("ut"))
                else:
                    self.logger.warning(
                        "Unknown group in installation_status_all group:%s (%s) - skipping",
                        group,
                        self.log_account,
                    )

    def parse_parameter_lists(self, parameter_list):
        for serial, device_data in parameter_list.items():
            device = self.get_device_by_serial(serial)
            for data_id, data_value in device_data.items():
                if data_id == "city":
                    device["city"] = data_value
                elif data_id == "parameters":
                    for data_value_item in data_value:
                        group = data_value_item["group"]
                        if group == "Temperatures":
                            for list_item in data_value_item["list"]:
                                index = list_item["dbindex"]
                                device["temperatures"][index] = list_item
                        elif group == "Info":
                            for list_item in data_value_item["list"]:
                                index = list_item["installation_status"]
                                device["info"][index] = list_item
                        elif group == "Weather forecast":
                            for list_item in data_value_item["list"]:
                                index = list_item["naslov"]
                                device["weather"][index] = list_item
                        elif group == "Heating circuits":
                            for list_item in data_value_item["list"]:
                                index = list_item["naslov"]
                                device["circuits"][index] = list_item
                        else:
                            self.logger.warning(
                                "Unknown group in parameter_list group:%s (%s) - skipping",
                                group,
                                self.log_account,
                            )
                else:
                    self.logger.warning(
                        "Unknown data_id in parameter_list data_id:%s (%s) - skipping",
                        data_id,
                        self.log_account,
                    )

    def parse_grid(self, http_client):
        http_client.grid = json.loads(http_client.widgetgrid["grid"])
        if "widgets" in http_client.grid:
            for widget in http_client.grid["widgets"]:
                device = self.get_device_by_id(widget["data"]["installation"])
                device["widgets"][widget["id"]] = widget
        if "widgets2" in http_client.grid:
            for widget in http_client.grid["widgets2"]:
                device = self.get_device_by_id(widget["data"]["installation"])
                device["widgets"][widget["id"]] = widget

    async def _update_device_with_real_time_data(self, device, body):
        try:
            data = _decode_json_body(body)
        except (JSONDecodeError, ValueError) as err:
            self.logger.warning(
                "Skipping malformed realtime JSON payload for device %s (%s): %s body=%r",
                device.get("serial"),
                self.log_account,
                err,
                body[:300],
            )
            return
        for param_id, value in data.items():
            if device.has_parameter(param_id):
                parameter = await device.update_parameter(param_id, value)
                for on_update_callback in list(self.on_update_callbacks.values()):
                    await on_update_callback(device, parameter)

    async def parse_real_time_frame(self, stomp_frame):
        if "headers" in stomp_frame and "body" in stomp_frame:
            headers = stomp_frame["headers"]
            body = stomp_frame["body"]
            if "subscription" in headers and "destination" in headers:
                subscription = headers["subscription"]
                destination = headers["destination"]
                if subscription.startswith("sub-"):
                    if destination.startswith(WEB_BOILER_STOMP_DEVICE_TOPIC):
                        dotpos = destination.rfind(".")
                        serial = destination[dotpos + 1:]
                        try:
                            device = self.get_device_by_serial(serial)
                        except Exception:
                            self.logger.warning(
                                "Unexpected realtime message for unknown serial: %s (%s) - skipping",
                                serial,
                                self.log_account,
                            )
                            return
                        await self._update_device_with_real_time_data(device, body)
                    else:
                        self.logger.warning(
                            "Unexpected message for destination: %s (%s) - skipping",
                            destination,
                            self.log_account,
                        )
                elif subscription == WEB_BOILER_STOMP_NOTIFICATION_TOPIC:
                    self.logger.info("Notification received: %s (%s)", body, self.log_account)
                else:
                    self.logger.warning(
                        "Unexpected message for subscription: %s (%s) - skipping",
                        subscription,
                        self.log_account,
                    )
