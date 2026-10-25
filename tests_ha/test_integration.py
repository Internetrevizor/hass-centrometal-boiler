"""The integration running in a real Home Assistant against the fake cloud."""

from __future__ import annotations

import copy

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import DOMAIN
from .fake_centrometal import BIOTEC_PLUS, EMAIL, PASSWORD, PELTEC2, wait_until


async def _setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


def _entity_id(hass, platform: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)


def _state(hass, platform: str, unique_id: str):
    entity_id = _entity_id(hass, platform, unique_id)
    assert entity_id is not None, unique_id
    return hass.states.get(entity_id)


# PelTec II, scheme 43


async def test_peltec2_scheme_43_entities(hass, entry):
    await _setup(hass, entry)

    configuration = _state(hass, "sensor", "PT2SERIAL-B_KONF")
    assert configuration.state == "43. BUF + K1 DHW"
    assert configuration.attributes["P1"] == "DHW Pump (K1)"
    assert configuration.attributes["P2"] == "DHW Recirculation Pump (K1)"

    assert _state(hass, "sensor", "PT2SERIAL-B_STATE").state == "OFF: Switched off"
    assert _state(hass, "sensor", "PT2SERIAL-B_P2").name == "PelTec II Lambda P2 DHW Recirculation Pump (K1)"
    assert _state(hass, "sensor", "PT2SERIAL-K1B_P").name == "PelTec II Lambda DHW Pump (K1)"
    # P1 is the DHW pump K1B_P already reports: no second entity for it.
    assert _entity_id(hass, "sensor", "PT2SERIAL-B_P1") is None
    # The pellet mode button is BioTec-Plus only.
    assert _entity_id(hass, "button", "PT2SERIAL_button_pellet_mode") is None
    # Scheme 43 has a buffer and a DHW tank with its own pump.
    assert _entity_id(hass, "sensor", "PT2SERIAL-B_bup") is not None
    assert _entity_id(hass, "sensor", "PT2SERIAL-B_PTV_PRI") is not None

    assert float(_state(hass, "number", "PT2SERIAL_setting_67").state) == 66
    assert _state(hass, "binary_sensor", "PT2SERIAL_websocket_status").state == "on"


async def test_realtime_update_reaches_the_boiler_state(hass, entry, broker):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "sensor", "PT2SERIAL-B_STATE")

    await broker.publish("peltec2", "PT2SERIAL", {"B_STATE": "S4"})
    await wait_until(lambda: hass.states.get(entity_id).state == "S4: Electric heater working after flame appears")


async def test_setting_a_number_sends_the_portal_command(hass, entry, website):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "number", "PT2SERIAL_setting_67")

    await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": 70}, blocking=True)
    assert {"cmd-name": "PWR 67", "cmd-value": 70} in website.commands_to(1001)


async def test_expired_session_is_recovered_after_a_failed_command(hass, entry, website):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "number", "PT2SERIAL_setting_67")

    website.session_expired = True
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": 70}, blocking=True)
    # The failed command logged in again; the next one goes through.
    assert website.session_expired is False
    await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": 71}, blocking=True)
    assert {"cmd-name": "PWR 67", "cmd-value": 71} in website.commands_to(1001)


# Slot 71 listed by parameter-list but missing from the status snapshot, as on
# the maintainer's boiler after a Home Assistant restart.
PELTEC2_LATE_SLOT = copy.deepcopy(PELTEC2)
PELTEC2_LATE_SLOT["parameter_list"]["parameters"][0]["list"].append(
    {
        "dbindex": 71,
        "naslov": "Stop buffer tank temperature",
        "tip": "temperatura",
        "user": "rw",
        "showButton": True,
        "sufix": "°C",
    }
)


@pytest.mark.parametrize("boilers", [[PELTEC2_LATE_SLOT]])
async def test_a_setting_reported_after_setup_fills_in(hass, entry, broker):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "number", "PT2SERIAL_setting_71")
    assert hass.states.get(entity_id).state == "unavailable"

    await broker.publish("peltec2", "PT2SERIAL", {"PVAL_71_0": "8", "PMIN_71_0": "5", "PMAX_71_0": "20"})
    await wait_until(lambda: hass.states.get(entity_id).state != "unavailable")
    state = hass.states.get(entity_id)
    assert float(state.state) == 8
    assert (state.attributes["min"], state.attributes["max"]) == (5, 20)


async def test_broker_restart_marks_the_connection_lost(hass, entry, broker):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "binary_sensor", "PT2SERIAL_websocket_status")

    await broker.drop_connections()
    await wait_until(lambda: hass.states.get(entity_id).state == "off")


# BioTec-Plus


@pytest.mark.parametrize("boilers", [[BIOTEC_PLUS]])
async def test_biotec_plus_tank_values_fill_in_when_reported(hass, entry, broker):
    await _setup(hass, entry)
    tank = _entity_id(hass, "sensor", "BIOSERIAL-B_razina")
    fuel = _entity_id(hass, "sensor", "BIOSERIAL-B_razP")
    # Not reported yet: present, but unavailable.
    assert hass.states.get(tank).state == "unavailable"
    assert hass.states.get(fuel).state == "unavailable"

    await broker.publish("biopl", "BIOSERIAL", {"B_razina": "2", "B_razP": "45"})
    await wait_until(lambda: hass.states.get(tank).state == "Full")
    await wait_until(lambda: hass.states.get(fuel).state not in ("unavailable", "unknown"))
    assert float(hass.states.get(fuel).state) == 45


@pytest.mark.parametrize("boilers", [[BIOTEC_PLUS]])
async def test_pellet_mode_button_sends_the_command(hass, entry, website):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "button", "BIOSERIAL_button_pellet_mode")
    assert hass.states.get(entity_id).name == "BioTec-Plus Pellet Mode"

    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    assert {"cmd-name": "SCCMD", "cmd-value": 1} in website.commands_to(4242)


# Naming option


@pytest.mark.parametrize("entry_options", [{"product_prefix": False}])
async def test_product_prefix_switched_off(hass, entry):
    await _setup(hass, entry)
    assert _state(hass, "sensor", "PT2SERIAL-B_P2").name == "P2 DHW Recirculation Pump (K1)"
    assert _state(hass, "sensor", "PT2SERIAL-K1B_P").name == "DHW Pump (K1)"


async def test_options_flow_switches_the_product_prefix_off(hass, entry):
    await _setup(hass, entry)
    entity_id = _entity_id(hass, "sensor", "PT2SERIAL-B_P2")

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"product_prefix": False, "refresh_interval": 240, "retry_base_interval": 60, "retry_max_interval": 1800},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options["product_prefix"] is False
    assert entry.state is ConfigEntryState.LOADED
    # Same entity, new display name.
    assert _entity_id(hass, "sensor", "PT2SERIAL-B_P2") == entity_id
    assert hass.states.get(entity_id).name == "P2 DHW Recirculation Pump (K1)"


# Setup paths


async def test_wrong_password_asks_for_reauthentication(hass, cloud):
    entry = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data={"email": EMAIL, "password": "wrong", "prefix": ""})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_portal_outage_retries_later(hass, entry, website):
    website.down = True
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_config_flow_creates_the_entry(hass, cloud):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"email": EMAIL, "password": PASSWORD, "prefix": ""}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"].startswith("PelTec II Lambda")
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state is ConfigEntryState.LOADED
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
