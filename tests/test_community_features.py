"""Features brought over from the other forks of the original integration.

* BioTec-Plus tank level and fuel level (original integration, AndroFlo fork).
* The "prefix entity names with the product name" option (original, #20).
* The BioTec-Plus "Pellet Mode" button (AndroFlo fork).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeassistant.exceptions import HomeAssistantError  # noqa: E402

from custom_components.centrometal_boiler import button as button_platform  # noqa: E402
from custom_components.centrometal_boiler.centrometal_web_boiler import HttpClientAuthError  # noqa: E402
from custom_components.centrometal_boiler.centrometal_web_boiler.HttpClient import HttpClient  # noqa: E402
from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
)
from custom_components.centrometal_boiler.common import format_name  # noqa: E402
from custom_components.centrometal_boiler.sensors.WebBoilerGenericSensor import (  # noqa: E402
    WebBoilerGenericSensor,
)

_FAKE_HASS = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")))


class _FakeClient:
    def __init__(self) -> None:
        self.pellet_mode_calls: list[str] = []
        self.accept = True
        self.raise_auth = False
        self.refreshes = 0

    def has_fresh_data(self) -> bool:
        return True

    async def set_pellet_mode(self, serial) -> bool:
        if self.raise_auth:
            raise HttpClientAuthError("session expired")
        self.pellet_mode_calls.append(serial)
        return self.accept

    async def refresh(self) -> bool:
        self.refreshes += 1
        return True


class _FakeSystem:
    def __init__(self) -> None:
        self.recovered = 0

    async def async_recover_http_session(self) -> None:
        self.recovered += 1


def _device(device_type: str, product: str, parameters: dict | None = None, **flags) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device.update(
        {
            "id": 4242,
            "serial": "ABC123",
            "type": device_type,
            "product": product,
            "__client": _FakeClient(),
            "__system": _FakeSystem(),
            "__prefix": "",
            "__multi_device": False,
            **flags,
        }
    )
    for name, value in (parameters or {}).items():
        device.create_parameter(name, value)
    return device


def _conf_entities(device) -> dict:
    return {e._param_name: e for e in WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device)}


# BioTec-Plus tank level and fuel level


def test_biotec_plus_tank_and_fuel_level_exist_before_the_first_value() -> None:
    created = _conf_entities(_device("biopl", "BioTec-Plus"))
    assert created["B_razina"].name == "BioTec-Plus Tank Level"
    assert created["B_razP"].name == "BioTec-Plus Fuel Level"
    # No value yet: unavailable, not a made-up reading.
    assert created["B_razina"].available is False
    assert created["B_razP"].available is False
    assert created["B_razina"].native_value is None
    assert created["B_razP"].native_value is None


def test_biotec_plus_tank_and_fuel_level_decode_once_reported() -> None:
    device = _device("biopl", "BioTec-Plus")
    created = _conf_entities(device)
    device.get_parameter("B_razina")["value"] = "2"
    device.get_parameter("B_razP")["value"] = "45"
    assert created["B_razina"].native_value == "Full"
    assert created["B_razina"].available is True
    assert created["B_razP"].native_value == 45.0
    assert created["B_razP"].native_unit_of_measurement == "%"
    assert created["B_razP"].suggested_display_precision == 0
    # A reading outside 0-100 is not a percentage.
    device.get_parameter("B_razP")["value"] = "250"
    assert created["B_razP"].available is False


def test_biotec_plus_unique_ids_match_the_original_integration() -> None:
    created = _conf_entities(_device("biopl", "BioTec-Plus"))
    assert created["B_razina"].unique_id == "ABC123-B_razina"
    assert created["B_razP"].unique_id == "ABC123-B_razP"


def test_other_families_get_no_placeholder_tank_parameters() -> None:
    device = _device("peltec2", "PelTec II Lambda", {"B_KONF": "42"})
    _conf_entities(device)
    assert not device.has_parameter("B_razina")
    assert not device.has_parameter("B_razP")


# Product name prefix option


def test_product_prefix_is_kept_by_default() -> None:
    device = _device("peltec2", "PelTec II Lambda")
    assert format_name(_FAKE_HASS, device, "PelTec II Lambda Boiler Temperature") == "PelTec II Lambda Boiler Temperature"


def test_product_prefix_can_be_switched_off() -> None:
    device = _device("peltec2", "PelTec II Lambda", __product_prefix=False)
    assert format_name(_FAKE_HASS, device, "PelTec II Lambda Boiler Temperature") == "Boiler Temperature"
    # Names that never carried the product are left alone.
    assert format_name(_FAKE_HASS, device, "Centrometal Boiler System connection") == (
        "Centrometal Boiler System connection"
    )


def test_product_prefix_off_keeps_the_user_prefix_and_the_serial() -> None:
    device = _device("peltec2", "PelTec II Lambda", __product_prefix=False, __prefix="Home ", __multi_device=True)
    assert format_name(_FAKE_HASS, device, "PelTec II Lambda Boiler Temperature") == "Home ABC123 Boiler Temperature"


def test_product_prefix_option_reaches_generic_entities() -> None:
    device = _device("peltec2", "PelTec II Lambda", {"B_Tk1": "60"}, __product_prefix=False)
    created = _conf_entities(device)
    assert created["B_Tk1"].name == "Boiler Temperature"


def test_options_win_over_entry_data_for_the_product_prefix() -> None:
    from custom_components.centrometal_boiler import WebBoilerSystem

    def system(options, data):
        entry = SimpleNamespace(options=options, data=data)
        return WebBoilerSystem(None, entry=entry, username="user@example.com", password="x", prefix="")

    assert system({}, {}).product_prefix is True
    # An entry from the original integration that switched it off stays off.
    assert system({}, {"product_prefix": False}).product_prefix is False
    assert system({"product_prefix": True}, {"product_prefix": False}).product_prefix is True


# BioTec-Plus Pellet Mode button


def test_pellet_mode_command_payload() -> None:
    client = HttpClient("user@example.com", "secret")
    sent: list = []

    async def fake_control(id, data):
        sent.append((id, data))
        return {"status": "success"}

    client._control = fake_control
    asyncio.run(client.set_pellet_mode_by_id(4242))
    assert sent == [(4242, {"cmd-name": "SCCMD", "cmd-value": 1})]


def _buttons(*devices):
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(client=SimpleNamespace(data={d["serial"]: d for d in devices}))
    )
    added: list = []
    asyncio.run(button_platform.async_setup_entry(None, entry, added.extend))
    return added


def test_pellet_mode_button_only_for_biotec_plus() -> None:
    biopl = _device("biopl", "BioTec-Plus")
    peltec2 = _device("peltec2", "PelTec II Lambda")
    peltec2["serial"] = "PEL999"
    buttons = _buttons(biopl, peltec2)
    assert len(buttons) == 1
    assert buttons[0].unique_id == "ABC123_button_pellet_mode"
    assert buttons[0].name == "BioTec-Plus Pellet Mode"


def test_pellet_mode_press_sends_the_command_and_reads_back() -> None:
    device = _device("biopl", "BioTec-Plus")
    button = _buttons(device)[0]
    asyncio.run(button.async_press())
    assert device["__client"].pellet_mode_calls == ["ABC123"]
    assert device["__client"].refreshes == 1


def test_pellet_mode_press_reports_a_rejected_command() -> None:
    device = _device("biopl", "BioTec-Plus")
    device["__client"].accept = False
    button = _buttons(device)[0]
    with pytest.raises(HomeAssistantError):
        asyncio.run(button.async_press())


def test_pellet_mode_press_recovers_an_expired_session() -> None:
    device = _device("biopl", "BioTec-Plus")
    device["__client"].raise_auth = True
    button = _buttons(device)[0]
    with pytest.raises(HomeAssistantError):
        asyncio.run(button.async_press())
    assert device["__system"].recovered == 1


def test_translations_cover_the_same_keys() -> None:
    base = ROOT / "custom_components" / "centrometal_boiler" / "translations"

    def keys(d, prefix=""):
        out = set()
        for k, v in d.items():
            out |= keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k}
        return out

    english = {k for k in keys(json.loads((base / "en.json").read_text())) if not k.startswith("entity.")}
    for code in ("fr", "ro"):
        assert keys(json.loads((base / f"{code}.json").read_text())) == english, code
