"""Editable controller settings, written the way the portal writes them.

Captured from the portal's own request when the pencil on a settings row is
used::

    POST /api/inst/control/{id}    {"cmd-name": "PWR 67",  "cmd-value": 66}
    POST /api/inst/control/{id}    {"cmd-name": "PWR 71",  "cmd-value": 8}
    POST /api/inst/control/{id}    {"cmd-name": "PWR 291", "cmd-value": 54.8}

The value is the plain reading in every case. Slots 67 and 291 both hold
40..85 for 40..85 C; the tenth-resolution row sends the decimal itself rather
than a scaled integer.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
    WebBoilerDeviceCollection,
)
from custom_components.centrometal_boiler.number import SettingStoredData, WebBoilerSettingNumber  # noqa: E402
from custom_components.centrometal_boiler.sensors.generic_sensors_all import (  # noqa: E402
    get_generic_temperature_settings_sensors,
    is_editable_setting,
)

EDITABLE_ROW = {
    "naslov": "Buffer tank temperature",
    "dbindex": 67,
    "tip": "temperatura",
    "sufix": "°C",
    "admin": "rw",
    "serviser": "rw",
    "user": "rw",
    "showButton": True,
}
READ_ONLY_ROW = {**EDITABLE_ROW, "dbindex": 70, "user": "r", "naslov": "Read only"}
# The DHW rows the portal marks as tenth-resolution.
TENTH_ROW = {
    **EDITABLE_ROW,
    "dbindex": 291,
    "tip": "temperatura_0.1",
    "naslov": "DHW temperature (K1 circuit)",
}


class _Client:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple] = []
        self.refreshes = 0
        self.data = WebBoilerDeviceCollection("user@example.com")

    def has_fresh_data(self) -> bool:
        return True

    async def set_parameter_value(self, serial, dbindex, value):
        self.calls.append((serial, dbindex, value))
        return self.accepted

    async def refresh(self):
        self.refreshes += 1
        return True


def _device(client, slots: dict[str, str], rows=(EDITABLE_ROW,)) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device["id"] = 1001
    device["serial"] = "SN1"
    device["type"] = "peltec2"
    device["product"] = "PelTec II Lambda"
    device["__client"] = client
    device["__system"] = None
    device["__prefix"] = ""
    device["__multi_device"] = False
    device["temperatures"] = {str(r["dbindex"]): r for r in rows}
    for name, value in slots.items():
        device.create_parameter(name, value)
    return device


def _number(client, slots: dict[str, str], row=EDITABLE_ROW) -> WebBoilerSettingNumber:
    return WebBoilerSettingNumber(None, _device(client, slots, rows=(row,)), row)


TENTH_SLOT = {"PVAL_291_0": "50", "PMIN_291_0": "40", "PMAX_291_0": "85"}


FULL_SLOT = {"PVAL_67_0": "67", "PMIN_67_0": "40", "PMAX_67_0": "85", "PDEF_67_0": "80"}


def test_only_rows_the_portal_lets_this_account_edit_are_offered() -> None:
    assert is_editable_setting(EDITABLE_ROW) is True
    assert is_editable_setting(READ_ONLY_ROW) is False
    assert is_editable_setting({**EDITABLE_ROW, "showButton": False}) is False
    assert is_editable_setting({**EDITABLE_ROW, "tip": "parametar"}) is False
    assert is_editable_setting(None) is False


def test_bounds_come_from_the_controller_not_from_the_code() -> None:
    entity = _number(_Client(), FULL_SLOT)
    assert entity.native_value == 67
    assert entity.native_min_value == 40
    assert entity.native_max_value == 85
    assert entity.native_unit_of_measurement == "°C"
    assert entity.extra_state_attributes["Default"] == 80


def test_writing_sends_the_captured_command_shape() -> None:
    async def runner() -> None:
        client = _Client()
        entity = _number(client, FULL_SLOT)
        await entity.async_set_native_value(66)
        assert client.calls == [("SN1", 67, 66)]
        # Read back, so the entity shows what the controller accepted.
        assert client.refreshes == 1

    asyncio.run(runner())


def test_a_value_outside_the_controller_range_is_refused_before_sending() -> None:
    async def runner() -> None:
        client = _Client()
        entity = _number(client, FULL_SLOT)
        with pytest.raises(Exception, match="outside the range"):
            await entity.async_set_native_value(95)
        assert client.calls == []

    asyncio.run(runner())


def test_a_rejected_write_is_reported_not_swallowed() -> None:
    async def runner() -> None:
        client = _Client(accepted=False)
        entity = _number(client, FULL_SLOT)
        with pytest.raises(Exception, match="did not accept"):
            await entity.async_set_native_value(66)
        assert client.refreshes == 0

    asyncio.run(runner())


def test_a_one_degree_row_is_written_as_a_whole_number() -> None:
    """Boiler and buffer rows are whole degrees, which is what the portal
    sends and what the owner reports the controller accepts."""

    async def runner() -> None:
        client = _Client()
        entity = _number(client, FULL_SLOT)
        assert entity.native_step == 1
        await entity.async_set_native_value(66.4)
        assert client.calls == [("SN1", 67, 66)]

    asyncio.run(runner())


def test_a_tenth_resolution_row_keeps_its_decimal() -> None:
    """The DHW rows take tenths, and the portal sends the decimal itself --
    54.8 means 54.8 C, not 5.48 and not 548."""

    async def runner() -> None:
        client = _Client()
        entity = _number(client, TENTH_SLOT, row=TENTH_ROW)
        assert entity.native_step == 0.1
        await entity.async_set_native_value(54.8)
        assert client.calls == [("SN1", 291, 54.8)]

    asyncio.run(runner())


def test_a_tenth_resolution_row_is_still_bounded_by_the_controller() -> None:
    async def runner() -> None:
        client = _Client()
        entity = _number(client, TENTH_SLOT, row=TENTH_ROW)
        assert (entity.native_min_value, entity.native_max_value) == (40, 85)
        with pytest.raises(Exception, match="outside the range"):
            await entity.async_set_native_value(85.1)
        assert client.calls == []

    asyncio.run(runner())


def test_a_slot_without_bounds_is_unavailable_rather_than_writable() -> None:
    entity = _number(_Client(), {"PVAL_67_0": "67"})
    assert entity.available is False


STOP_BUFFER_ROW = {**EDITABLE_ROW, "dbindex": 71, "naslov": "Stop buffer tank temperature"}


def _watched_number(slots: dict[str, str], row=STOP_BUFFER_ROW, restored: dict | None = None):
    """A setting entity added to Home Assistant, with its state writes counted.

    ``restored`` is what the previous run saved for it, as Home Assistant hands
    it back after a restart.
    """
    from homeassistant.helpers.restore_state import RestoredExtraData

    client = _Client()
    device = _device(client, slots, rows=(row,))
    client.data[device["serial"]] = device
    entity = WebBoilerSettingNumber(None, device, row)
    writes: list[float | None] = []
    entity.async_write_ha_state = lambda: writes.append(entity.native_value)

    async def last_extra_data():
        return None if restored is None else RestoredExtraData(json.loads(json.dumps(restored)))

    entity.async_get_last_extra_data = last_extra_data
    return client, device, entity, writes


def test_a_slot_the_portal_reports_after_setup_fills_the_entity_in() -> None:
    """Seen on a PelTec II Lambda: slots 71, 291 and 292 were missing from the
    status snapshot after a restart and arrived only once the portal website
    was opened. The entity has to pick them up then, not at the next restart."""

    async def runner() -> None:
        client, _device_, entity, writes = _watched_number({})
        await entity.async_added_to_hass()
        assert entity.available is False

        status = {"PVAL_71_0": "8", "PMIN_71_0": "5", "PMAX_71_0": "20", "PDEF_71_0": "10"}
        await client.data.parse_installation_statuses(
            {"1001": {"params": {name: {"v": value, "ut": 1} for name, value in status.items()}}}
        )
        assert entity.available is True
        assert (entity.native_value, entity.native_min_value, entity.native_max_value) == (8, 5, 20)
        assert writes and writes[-1] == 8

    asyncio.run(runner())


def test_a_late_slot_keeps_updating_after_it_first_arrived() -> None:
    async def runner() -> None:
        client, device, entity, writes = _watched_number({})
        await entity.async_added_to_hass()
        await client.data._update_device_with_real_time_data(
            device, '{"PVAL_71_0": "8", "PMIN_71_0": "5", "PMAX_71_0": "20"}'
        )
        writes.clear()

        await client.data._update_device_with_real_time_data(device, '{"PVAL_71_0": "9"}')
        assert entity.native_value == 9
        # One write, from the slot's own listener; the late-arrival path only
        # acts on a parameter it has not hooked yet.
        assert writes == [9]

    asyncio.run(runner())


def test_another_slot_or_device_does_not_wake_the_entity() -> None:
    async def runner() -> None:
        client, device, entity, writes = _watched_number({})
        await entity.async_added_to_hass()
        other = _device(client, {}, rows=(STOP_BUFFER_ROW,))
        other["id"] = 1002
        other["serial"] = "SN2"
        client.data[other["serial"]] = other

        await client.data._update_device_with_real_time_data(device, '{"PVAL_67_0": "66"}')
        await client.data._update_device_with_real_time_data(other, '{"PVAL_71_0": "8"}')
        assert writes == []
        assert entity.available is False

    asyncio.run(runner())


def test_a_removed_entity_stops_listening() -> None:
    async def runner() -> None:
        client, device, entity, writes = _watched_number({"PVAL_71_0": "8", "PMIN_71_0": "5"})
        await entity.async_added_to_hass()
        await entity.async_will_remove_from_hass()

        await client.data._update_device_with_real_time_data(device, '{"PVAL_71_0": "9", "PMAX_71_0": "20"}')
        assert writes == []
        assert entity.unique_id not in client.data.on_update_callbacks

    asyncio.run(runner())


def test_an_editable_slot_does_not_also_become_a_read_only_sensor() -> None:
    """One entity per setting: the number platform owns the editable rows."""
    device = _device(_Client(), FULL_SLOT, rows=(EDITABLE_ROW, READ_ONLY_ROW))
    device.create_parameter("PVAL_70_0", "5")
    created = get_generic_temperature_settings_sensors(device)
    assert "PVAL_67_0" not in created
    # A row this account cannot edit keeps its read-only sensor.
    assert "PVAL_70_0" in created


def test_each_setting_gets_its_own_icon() -> None:
    """Keyed on the controller's parameter index, which is stable, rather than
    on the row title, which the portal localises."""
    from custom_components.centrometal_boiler.number import setting_icon

    assert setting_icon(67, "Buffer tank temperature") == "mdi:storage-tank"
    assert setting_icon(291, "DHW temperature (K1 circuit)") == "mdi:water-thermometer"
    assert setting_icon(71, "Stop buffer tank temperature") == "mdi:thermometer-off"
    # Distinct icons, so the list reads at a glance.
    rows = (576, 67, 68, 70, 71, 291, 292)
    assert len({setting_icon(i, "") for i in rows}) == len(rows)


def test_an_unknown_index_falls_back_to_the_title_in_either_language() -> None:
    assert setting_icon_for("PTV temperatura (K1 krug)") == "mdi:water-thermometer"
    assert setting_icon_for("DHW temperature") == "mdi:water-thermometer"
    assert setting_icon_for("Temperatura akumulacijskog spremnika") == "mdi:storage-tank"
    # Nothing recognisable: a plain settings icon, never a wrong one.
    assert setting_icon_for("Ceva complet necunoscut") == "mdi:thermometer-cog"


def setting_icon_for(title: str) -> str:
    from custom_components.centrometal_boiler.number import setting_icon

    return setting_icon(9999, title)


SAVED_STOP_BUFFER = {"value": 8.0, "minimum": 5.0, "maximum": 20.0, "default": 10.0, "timestamp": 1792771951}


def test_after_a_restart_a_setting_shows_its_last_known_value() -> None:
    """The portal may not report a slot after a restart until its settings page
    is opened. Meanwhile the entity shows what it last saw, and says so."""

    async def runner() -> None:
        _client, _device_, entity, _writes = _watched_number({}, restored=SAVED_STOP_BUFFER)
        await entity.async_added_to_hass()
        assert entity.available is True
        assert (entity.native_value, entity.native_min_value, entity.native_max_value) == (8, 5, 20)
        attributes = entity.extra_state_attributes
        assert attributes["Restored"] is True
        assert attributes["Default"] == 10

    asyncio.run(runner())


def test_a_value_from_the_portal_replaces_the_restored_one() -> None:
    async def runner() -> None:
        client, device, entity, writes = _watched_number({}, restored=SAVED_STOP_BUFFER)
        await entity.async_added_to_hass()
        await client.data._update_device_with_real_time_data(
            device, '{"PVAL_71_0": "9", "PMIN_71_0": "5", "PMAX_71_0": "20"}'
        )
        assert entity.native_value == 9
        assert "Restored" not in entity.extra_state_attributes
        assert writes and writes[-1] == 9

    asyncio.run(runner())


def test_a_slot_reported_at_setup_is_never_marked_restored() -> None:
    async def runner() -> None:
        _client, _device_, entity, _writes = _watched_number(
            {"PVAL_71_0": "7", "PMIN_71_0": "5", "PMAX_71_0": "20"}, restored=SAVED_STOP_BUFFER
        )
        await entity.async_added_to_hass()
        assert entity.native_value == 7
        assert "Restored" not in entity.extra_state_attributes

    asyncio.run(runner())


def test_what_is_saved_for_the_next_restart() -> None:
    async def runner() -> None:
        # Reported by the portal: saved as reported.
        _client, _device_, entity, _writes = _watched_number({"PVAL_71_0": "8", "PMIN_71_0": "5", "PMAX_71_0": "20"})
        await entity.async_added_to_hass()
        assert entity.extra_restore_state_data.as_dict() == {
            "value": 8.0,
            "minimum": 5.0,
            "maximum": 20.0,
            "default": None,
            "timestamp": None,
        }
        # Not reported since the restart: the restored values are saved again,
        # so a second restart before the portal reports the slot keeps them.
        _client, _device_, entity, _writes = _watched_number({}, restored=SAVED_STOP_BUFFER)
        await entity.async_added_to_hass()
        assert entity.extra_restore_state_data.as_dict() == SAVED_STOP_BUFFER

    asyncio.run(runner())


def test_saved_data_survives_the_json_round_trip() -> None:
    saved = SettingStoredData(value=54.8, minimum=40.0, maximum=85.0, default=50.0, timestamp=1792771951)
    assert SettingStoredData.from_dict(json.loads(json.dumps(saved.as_dict()))) == saved


def test_incomplete_or_malformed_saved_data_is_not_used() -> None:
    async def runner(restored: dict) -> bool:
        _client, _device_, entity, _writes = _watched_number({}, restored=restored)
        await entity.async_added_to_hass()
        return entity.available

    # Without bounds it was not writable when saved; text is not a number.
    assert asyncio.run(runner({**SAVED_STOP_BUFFER, "minimum": None})) is False
    assert asyncio.run(runner({**SAVED_STOP_BUFFER, "maximum": None})) is False
    assert asyncio.run(runner({**SAVED_STOP_BUFFER, "value": "8"})) is False
    assert asyncio.run(runner({"something": "else"})) is False


def test_a_restored_setting_is_still_bounded_when_written() -> None:
    async def runner() -> None:
        client, _device_, entity, _writes = _watched_number({}, restored=SAVED_STOP_BUFFER)
        await entity.async_added_to_hass()
        with pytest.raises(Exception, match="outside the range"):
            await entity.async_set_native_value(25)
        await entity.async_set_native_value(9)
        assert client.calls == [("SN1", 71, 9)]

    asyncio.run(runner())
