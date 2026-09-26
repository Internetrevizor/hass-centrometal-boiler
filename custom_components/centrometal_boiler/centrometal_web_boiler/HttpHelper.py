"""Convenience accessors over ``HttpClient.installations``.

The helper is intentionally a thin lookup layer. It does not own state — it
delegates to the live ``HttpClient.installations`` list so that subsequent
relogin calls that replace the list are reflected immediately.
"""

from __future__ import annotations

from typing import Any

from .HttpClient import HttpClient


class HttpHelperLookupError(LookupError):
    """Raised when a requested device cannot be found in the installations list."""


class HttpHelperIndexError(HttpHelperLookupError, IndexError):
    """Raised for an out-of-range device index.

    Subclasses both so every lookup failure in this class can be caught as
    ``HttpHelperLookupError`` while callers written against the previous
    ``IndexError`` keep working unchanged.
    """


class HttpHelper:
    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def get_device_count(self) -> int:
        return len(self.client.installations)

    def getDevice(self, index: int) -> dict[str, Any]:
        # Kept under the legacy camelCase name to preserve the public API.
        if 0 <= index < self.get_device_count():
            return self.client.installations[index]
        raise HttpHelperIndexError(
            f"HttpHelper.getDevice: invalid index {index} (have {self.get_device_count()} device(s))"
        )

    def get_device_by_id(self, id: str | int) -> dict[str, Any]:
        target = str(id)
        for device in self.client.installations:
            if str(device["value"]) == target:
                return device
        raise HttpHelperLookupError(f"No device with id {id!r}")

    def get_device_by_serial(self, serial: str) -> dict[str, Any]:
        for device in self.client.installations:
            if device["label"] == serial:
                return device
        raise HttpHelperLookupError(f"No device with serial {serial!r}")

    def get_all_devices_ids(self) -> list[Any]:
        return [device["value"] for device in self.client.installations]

    def get_all_devices_serials(self) -> list[str]:
        return [device["label"] for device in self.client.installations]
