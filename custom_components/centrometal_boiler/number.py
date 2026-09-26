"""Editable controller settings, exposed as Home Assistant number entities.

The portal renders a pencil on every row of the parameter-list "Temperatures"
group and writes the new value with a single command, captured from the portal
itself::

    POST /api/inst/control/{id}
    {"cmd-name": "PWR 67", "cmd-value": 66}

where 67 is the row's ``dbindex`` and 66 is the value in the row's own unit --
slot 67 holds 40..85 for 40..85 C, so nothing is scaled.

Bounds come from the controller's own ``PMIN``/``PMAX`` slots rather than from
anything hard-coded here, so Home Assistant refuses a value the controller
would have rejected, and a firmware that widens a range is followed
automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .centrometal_web_boiler import HttpClientAuthError
from .common import create_device_info, format_name, format_time
from .sensors.generic_sensors_all import is_editable_setting

_LOGGER = logging.getLogger(__name__)

# Resolution per row type, and with it the encoding, both captured from the
# portal's own requests:
#
#   {"cmd-name": "PWR 67",  "cmd-value": 66}    tip "temperatura"      -> 66 C
#   {"cmd-name": "PWR 291", "cmd-value": 54.8}  tip "temperatura_0.1"  -> 54.8 C
#
# The value is the plain reading in both cases: a tenth-resolution row sends
# the decimal itself rather than a scaled integer, and slot 291 holds 40..85
# for 40..85 C exactly as slot 67 does.
_STEP_BY_TYPE = {"temperatura": 1, "temperatura_0.1": 0.1}
_DEFAULT_STEP = 1

# Icons are keyed on the controller's own parameter index, which is stable
# across firmwares, rather than on the row title, which the portal localises.
_ICON_BY_DBINDEX = {
    576: "mdi:water-boiler",  # Boiler difference
    67: "mdi:storage-tank",  # Buffer tank temperature
    68: "mdi:swap-vertical",  # Buffer tank temperature differential
    70: "mdi:thermometer-low",  # Minimal buffer tank temperature
    71: "mdi:thermometer-off",  # Stop buffer tank temperature
    291: "mdi:water-thermometer",  # DHW temperature (K1 circuit)
    292: "mdi:water-sync",  # DHW difference (K1 circuit)
}

# Fallback for an index this build has not seen, in the portal's two languages.
_ICON_BY_KEYWORD = (
    (("dhw", "ptv"), "mdi:water-thermometer"),
    (("buffer", "aku", "spremnik"), "mdi:storage-tank"),
    (("stop",), "mdi:thermometer-off"),
    (("minimal", "minimum", "min.", "minimalna"), "mdi:thermometer-low"),
    (("differential", "difference", "razlika"), "mdi:swap-vertical"),
    (("boiler", "kotao", "kotla"), "mdi:water-boiler"),
)
_DEFAULT_ICON = "mdi:thermometer-cog"


def setting_icon(dbindex, naslov) -> str:
    """Pick an icon for a settings row, by index first and title second."""
    try:
        known = _ICON_BY_DBINDEX.get(int(dbindex))
    except (TypeError, ValueError):
        known = None
    if known:
        return known
    title = str(naslov or "").casefold()
    for keywords, icon in _ICON_BY_KEYWORD:
        if any(word in title for word in keywords):
            return icon
    return _DEFAULT_ICON


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    entities: list[NumberEntity] = []
    client = config_entry.runtime_data.client
    for device in client.data.values():
        for row in device.get("temperatures", {}).values():
            if not is_editable_setting(row):
                continue
            entities.append(WebBoilerSettingNumber(hass, device, row))
    if entities:
        async_add_entities(entities, True)


class WebBoilerSettingNumber(NumberEntity):
    """One editable controller setting."""

    _attr_mode = NumberMode.BOX

    def __init__(self, hass: HomeAssistant, device, row: dict[str, Any]) -> None:
        self.hass = hass
        self.web_boiler_client = device["__client"]
        self._system = device["__system"]
        self._device = device
        self._dbindex = row["dbindex"]
        self._row = row
        self._serial = device["serial"]
        self._name = format_name(hass, device, f"{device['product']} {row.get('naslov', self._dbindex)}")
        # Distinct from the read-only sensor's "<serial>-PVAL_<dbindex>_0", and
        # in the same shape as the circuit switch's id.
        self._unique_id = f"{self._serial}_setting_{self._dbindex}"
        self._callback_key = f"setting_{self._dbindex}"
        self._unit = row.get("sufix") or None
        self._param_names = {
            "value": f"PVAL_{self._dbindex}_0",
            "default": f"PDEF_{self._dbindex}_0",
            "minimum": f"PMIN_{self._dbindex}_0",
            "maximum": f"PMAX_{self._dbindex}_0",
        }

    def _parameter(self, role: str):
        """Read a slot parameter without creating a placeholder for it."""
        return self._device.get("parameters", {}).get(self._param_names[role])

    def _number(self, role: str) -> float | None:
        parameter = self._parameter(role)
        if parameter is None:
            return None
        try:
            return float(str(parameter.get("value")).strip().replace(",", "."))
        except (TypeError, ValueError):
            # "?" -- the placeholder a slot carries before it is ever reported.
            return None

    async def async_added_to_hass(self) -> None:
        for name in self._param_names.values():
            parameter = self._device.get("parameters", {}).get(name)
            if parameter is not None:
                parameter.set_update_callback(self.update_callback, self._callback_key)

    async def async_will_remove_from_hass(self) -> None:
        for name in self._param_names.values():
            parameter = self._device.get("parameters", {}).get(name)
            if parameter is not None:
                parameter.set_update_callback(None, self._callback_key)

    async def update_callback(self, _parameter) -> None:
        self.async_write_ha_state()

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def icon(self) -> str:
        return setting_icon(self._dbindex, self._row.get("naslov"))

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self._unit

    @property
    def native_step(self) -> float:
        return _STEP_BY_TYPE.get(self._row.get("tip"), _DEFAULT_STEP)

    @property
    def native_min_value(self) -> float:
        minimum = self._number("minimum")
        # Falling back to the current reading rather than to 0 keeps Home
        # Assistant from offering a range the controller never advertised.
        return minimum if minimum is not None else (self.native_value or 0)

    @property
    def native_max_value(self) -> float:
        maximum = self._number("maximum")
        return maximum if maximum is not None else (self.native_value or 0)

    @property
    def native_value(self) -> float | None:
        return self._number("value")

    @property
    def available(self) -> bool:
        if not self.web_boiler_client.has_fresh_data():
            return False
        # Writing needs bounds; without them the portal would be the only thing
        # standing between a typo and the controller.
        return self._number("value") is not None and self._number("minimum") is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"Setting index": self._dbindex}
        default = self._number("default")
        if default is not None:
            attrs["Default"] = default
        parameter = self._parameter("value")
        if parameter is not None and parameter.get("timestamp") is not None:
            try:
                attrs["Last updated"] = format_time(self.hass, int(parameter["timestamp"]))
            except Exception:
                pass
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        minimum = self._number("minimum")
        maximum = self._number("maximum")
        if minimum is not None and maximum is not None and not (minimum <= value <= maximum):
            raise HomeAssistantError(
                f"{value:g} is outside the range the controller reports for this setting "
                f"({minimum:g} to {maximum:g})"
            )
        # Send what native_step advertises: a whole number for a 1-degree row,
        # one decimal for a tenth-resolution one. int() for the former so the
        # payload carries 66 rather than 66.0.
        step = self.native_step
        to_send = int(round(value)) if step >= 1 else round(value, 1)
        try:
            accepted = await self.web_boiler_client.set_parameter_value(self._serial, self._dbindex, to_send)
        except HttpClientAuthError as err:
            await self._system.async_recover_http_session()
            raise HomeAssistantError(
                "The Centrometal session had expired, so the setting was not changed. Please try again."
            ) from err
        if not accepted:
            raise HomeAssistantError("The controller did not accept the new value")
        try:
            refreshed = await self.web_boiler_client.refresh()
        except HttpClientAuthError as err:
            await self._system.async_recover_http_session()
            raise HomeAssistantError(
                "The setting was sent, but the Centrometal session expired before it could be read back"
            ) from err
        if not refreshed:
            raise HomeAssistantError("The setting was sent, but the integration could not read it back")

    @property
    def device_info(self):
        return create_device_info(self._device)
