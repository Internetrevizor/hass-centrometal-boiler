"""Guards on the PelTec II entity set, from a v3.03dL debug capture.

Three rules the capture established:

* A field the controller never publishes must not be an entity. `B_fan`,
  `B_fanB`, `B_fanO` and `B_rpm` appeared in none of the status responses and
  in no websocket frame across 8.5 hours, so the "Fan Speed" entity sat at a
  frozen 0 rpm — indistinguishable from a working sensor reading zero.
* The same physical device must not produce two entities. `B_P1`, `B_Pk1_k2`
  and `K1B_P` changed in the same millisecond on all seven switching cycles.
* Fields the manual defines and the controller does report are exposed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
)
from custom_components.centrometal_boiler.sensors.generic_sensors_peltec import (  # noqa: E402
    PELTEC2_GENERIC_SENSORS,
    PELTEC_GENERIC_SENSORS,
)
from custom_components.centrometal_boiler.sensors.WebBoilerGenericSensor import (  # noqa: E402
    WebBoilerGenericSensor,
)

_FAKE_HASS = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")))

# Every parameter the controller actually reported, plus the ones it never did.
REPORTED = ("B_P1", "B_Pk1_k2", "K1B_P", "B_gri", "B_doz", "B_pres", "B_KONF")
NEVER_REPORTED = ("B_fan", "B_fanB", "B_fanO", "B_rpm")


def _device(*parameters: str) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device["id"] = 7280
    device["serial"] = "SN1"
    device["type"] = "peltec2"
    device["product"] = "PelTec II Lambda"
    device["__client"] = None
    device["__system"] = None
    device["__prefix"] = ""
    device["__multi_device"] = False
    for name in parameters:
        device.create_parameter(name, "0")
    return device


def _created(device) -> set[str]:
    return {e._param_name for e in WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device)}


def test_unpublished_fan_fields_are_not_peltec2_entities() -> None:
    for name in NEVER_REPORTED:
        assert name not in PELTEC2_GENERIC_SENSORS, name
    # The older family, whose table was never in question, keeps them.
    assert "B_fan" in PELTEC_GENERIC_SENSORS


def test_p1_is_not_duplicated_when_the_circuit_reports_the_same_pump() -> None:
    assert "B_P1" not in _created(_device(*REPORTED))


def test_p1_is_still_created_without_a_k1_circuit() -> None:
    """Other configurations drive a diverter valve from P1; they keep it."""
    assert "B_P1" in _created(_device("B_P1", "B_KONF"))


def test_confirmed_fields_are_exposed() -> None:
    created = _created(_device(*REPORTED))
    for name in ("B_gri", "B_doz", "B_pres"):
        assert name in created, name


def test_the_new_binary_fields_render_as_text_not_raw_numbers() -> None:
    device = _device("B_pres", "B_doz")
    device.get_parameter("B_pres")["value"] = "1"
    device.get_parameter("B_doz")["value"] = "0"
    by_param = {e._param_name: e for e in WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device)}
    assert by_param["B_pres"].native_value == "On"
    assert by_param["B_doz"].native_value == "Off"
    # Text-returning sensors must not claim a numeric precision.
    assert by_param["B_pres"].suggested_display_precision is None
    assert by_param["B_doz"].suggested_display_precision is None
