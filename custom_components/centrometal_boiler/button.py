"""One-shot boiler commands.

Only the BioTec-Plus has one so far: switching from wood to pellets. The
command and the entity come from the AndroFlo BioTec-Plus fork
(https://github.com/AndroFlo/hass-centrometal-boiler), where they were
confirmed on a real boiler; the unique id is the same, so an entity created
there carries over.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .centrometal_web_boiler import HttpClientAuthError
from .common import create_device_info, format_name


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    client = config_entry.runtime_data.client
    entities = [
        WebBoilerPelletModeButton(hass, device) for device in client.data.values() if device.get("type") == "biopl"
    ]
    if entities:
        async_add_entities(entities)


class WebBoilerPelletModeButton(ButtonEntity):
    """Switch a BioTec-Plus from wood to pellets. There is no command back to wood."""

    _attr_icon = "mdi:grain"

    def __init__(self, hass: HomeAssistant, device) -> None:
        self.hass = hass
        self.web_boiler_client = device["__client"]
        self._system = device["__system"]
        self._device = device
        self._serial = device["serial"]
        self._attr_name = format_name(hass, device, f"{device['product']} Pellet Mode")
        self._attr_unique_id = f"{self._serial}_button_pellet_mode"

    @property
    def should_poll(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return self.web_boiler_client.has_fresh_data()

    @property
    def device_info(self):
        return create_device_info(self._device)

    async def async_press(self) -> None:
        try:
            accepted = await self.web_boiler_client.set_pellet_mode(self._serial)
        except HttpClientAuthError as err:
            await self._system.async_recover_http_session()
            raise HomeAssistantError(
                "The Centrometal session had expired, so the pellet mode command was not sent. Please try again."
            ) from err
        if not accepted:
            raise HomeAssistantError("The controller did not accept the pellet mode command")
        try:
            await self.web_boiler_client.refresh()
        except HttpClientAuthError:
            # The command itself went through; the next scheduled refresh reads
            # the new mode back once the session is recovered.
            await self._system.async_recover_http_session()
