from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError

from ..centrometal_web_boiler import HttpClientAuthError
from ..common import create_device_info, format_name, format_time
from .circuit_state import (
    circuit_state_fallback_name,
    state_from_circuit_parameter,
    state_from_slot,
)


class WebBoilerCircuitSwitch(SwitchEntity):
    def __init__(self, hass: HomeAssistant, device, naslov, dbindex) -> None:
        self.hass = hass
        self.web_boiler_client = device["__client"]
        self._system = device["__system"]
        self._device = device
        self._serial = device["serial"]
        self._name = format_name(hass, device, naslov)
        self._unique_id = f"{self._serial}_switch_{dbindex}"
        self._dbindex = dbindex
        self._table_key = f"table_{dbindex}_switch"
        self._param_name_def = f"PDEF_{dbindex}_0"
        self._param_name_state = f"PVAL_{dbindex}_0"
        self._param_name_off = f"PMIN_{dbindex}_0"
        self._param_name_on = f"PMAX_{dbindex}_0"
        self._param_def = self._device.get_parameter(self._param_name_def)
        self._param_state = self._device.get_parameter(self._param_name_state)
        self._param_off = self._device.get_parameter(self._param_name_off)
        self._param_on = self._device.get_parameter(self._param_name_on)
        self._param_def["used"] = True
        self._param_state["used"] = True
        self._param_off["used"] = True
        self._param_on["used"] = True
        self._fallback_name = circuit_state_fallback_name(naslov)
        self._fallback_callback_registered = False

    async def async_will_remove_from_hass(self) -> None:
        try:
            self._param_def.set_update_callback(None, self._table_key)
            self._param_state.set_update_callback(None, self._table_key)
            self._param_off.set_update_callback(None, self._table_key)
            self._param_on.set_update_callback(None, self._table_key)
            fallback = self._fallback_parameter()
            if fallback is not None:
                fallback.set_update_callback(None, self._table_key)
                self._fallback_callback_registered = False
        except Exception:
            pass

    async def async_added_to_hass(self):
        self.async_schedule_update_ha_state(False)
        self._param_def.set_update_callback(self.update_callback, self._table_key)
        self._param_state.set_update_callback(self.update_callback, self._table_key)
        self._param_off.set_update_callback(self.update_callback, self._table_key)
        self._param_on.set_update_callback(self.update_callback, self._table_key)
        self._register_fallback_callback()

    def _fallback_parameter(self):
        """Look the fallback parameter up on every read.

        Read through the parameters dict, never get_parameter(): this must not
        create a placeholder for a circuit the controller does not report. The
        lookup is repeated rather than cached in __init__ because a parameter
        that arrives after the entity was built would otherwise never be seen.
        """
        if not self._fallback_name:
            return None
        return self._device.get("parameters", {}).get(self._fallback_name)

    def _register_fallback_callback(self) -> None:
        if self._fallback_callback_registered:
            return
        fallback = self._fallback_parameter()
        if fallback is None:
            return
        fallback.set_update_callback(self.update_callback, self._table_key)
        self._fallback_callback_registered = True

    @property
    def should_poll(self) -> bool:
        return False

    async def update_callback(self, _device):
        # Cheap and idempotent: picks the fallback up if it only appeared after
        # the entity was created.
        self._register_fallback_callback()
        self.async_write_ha_state()

    @property
    def name(self) -> str:
        return self._name

    @property
    def unique_id(self) -> str:
        return self._unique_id

    def _state_from_pval(self) -> bool | None:
        return state_from_slot(
            self._param_state.get("value"),
            self._param_off.get("value"),
            self._param_on.get("value"),
        )

    def _state_from_circuit_parameter(self) -> bool | None:
        fallback = self._fallback_parameter()
        if fallback is None:
            return None
        return state_from_circuit_parameter(fallback.get("value"))

    @property
    def is_on(self) -> bool | None:
        """Return the circuit state, preferring the row's own PVAL slot.

        The portal does not send that slot in every status response, and while
        it is missing the switch used to sit at "unknown" indefinitely. The
        circuit's own on/off parameter carries the same state and is sent
        reliably, so it answers for the row until the slot comes back.
        """
        state = self._state_from_pval()
        if state is not None:
            return state
        return self._state_from_circuit_parameter()

    @property
    def icon(self) -> str:
        return "mdi:radiator" if self.is_on else "mdi:radiator-off"

    @property
    def available(self) -> bool:
        return self.web_boiler_client.has_fresh_data()

    def _compute_last_updated_str(self) -> str:
        try:
            raw_ts = self._param_state["timestamp"]
            if raw_ts is not None:
                return format_time(self.hass, int(raw_ts))
        except Exception:
            pass
        return "?"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Diagnostics: surface the raw triplet that drives is_on so users
        # who report "HA shows Off but WebUI shows On" bugs can paste the
        # values directly into an issue.
        attrs: dict[str, Any] = {"Last updated": self._compute_last_updated_str()}
        try:
            attrs["PVAL"] = self._param_state.get("value")
            attrs["PMIN"] = self._param_off.get("value") if self._param_off else None
            attrs["PMAX"] = self._param_on.get("value") if self._param_on else None
            fallback = self._fallback_parameter()
            attrs["State source"] = "PVAL" if self._state_from_pval() is not None else self._fallback_name
            if fallback is not None:
                attrs[self._fallback_name] = fallback.get("value")
        except Exception:
            pass
        return attrs

    async def turn_circuit_on_off(self, value: bool):
        try:
            accepted = await self.web_boiler_client.turn_circuit(self._device["serial"], self._dbindex, value)
        except HttpClientAuthError as err:
            await self._system.async_recover_http_session()
            raise HomeAssistantError(
                "The Centrometal session had expired, so the heating circuit command was not sent. "
                "Please try again."
            ) from err
        if not accepted:
            # A rejected command used to trigger a full relogin, which tears
            # down the websocket for every device on the account. The
            # controller refusing one circuit command says nothing about the
            # session; if the session really is gone, the branch above and the
            # periodic tick both handle it.
            raise HomeAssistantError("Failed to send the heating circuit command")
        try:
            refreshed = await self.web_boiler_client.refresh()
        except HttpClientAuthError as err:
            await self._system.async_recover_http_session()
            raise HomeAssistantError(
                "The heating circuit command was sent, but the Centrometal session expired before the "
                "state could be refreshed"
            ) from err
        if not refreshed:
            raise HomeAssistantError(
                "The heating circuit command was sent, but the integration could not refresh the latest state"
            )
        # refresh() already notified every updated parameter.

    async def async_turn_on(self, **kwargs) -> None:
        await self.turn_circuit_on_off(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.turn_circuit_on_off(False)

    @property
    def device_info(self) -> dict[str, Any]:
        return create_device_info(self._device)
