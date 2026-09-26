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
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
)
from custom_components.centrometal_boiler.number import WebBoilerSettingNumber  # noqa: E402
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
    device["id"] = 7280
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
