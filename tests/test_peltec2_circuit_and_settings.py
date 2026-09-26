"""Tests for the PelTec II circuit allowlist and the unlabelled settings slot.

Both were confirmed against a live PelTec II Lambda: the portal's K1 circuit
page for the circuit fields, and the owner for settings slot 582, which the
controller reports with no parameter-list row (hence no label, no
Default/Minimum/Maximum, and previously no entity at all).
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
from custom_components.centrometal_boiler.sensors.WebBoilerGenericSensor import (  # noqa: E402
    WebBoilerGenericSensor,
)
from custom_components.centrometal_boiler.sensors.WebBoilerHeatingCircuitSensor import (  # noqa: E402
    WebBoilerHeatingCircuitSensor,
)

_FAKE_HASS = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")))

# Every K1 field the controller reports, with the values from the capture.
K1_SNAPSHOT = {
    "K1B_CircType": "5",
    "K1B_P": "0",
    "K1B_Prec": "0",
    "K1B_Tpol": "50",
    "K1B_Tpol1": "35.6",
    "K1B_Tsob": "20",
    "K1B_Tsob1": "-55",
    "K1B_dayNight": "0",
    "K1B_kor": "-7",
    "K1B_korN": "-8",
    "K1B_korType": "0",
    "K1B_misC": "1",
    "K1B_misO": "0",
    "K1B_onOff": "1",
    "K1B_recSrc": "100",
    "K1B_recType": "0",
    "K1B_zahP": "1",
}


def _device(device_type: str, snapshot: dict[str, str]) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device["id"] = 1
    device["serial"] = "SN"
    device["type"] = device_type
    device["product"] = "PelTec II Lambda" if device_type == "peltec2" else "PelTec"
    device["__client"] = None
    device["__system"] = None
    device["__prefix"] = ""
    device["__multi_device"] = False
    for name, value in snapshot.items():
        device.create_parameter(name, value)
    return device


def _created(entities) -> set[str]:
    return {e._param_name for e in entities}


def test_peltec2_circuit_exposes_every_confirmed_field() -> None:
    device = _device("peltec2", K1_SNAPSHOT)
    created = _created(WebBoilerHeatingCircuitSensor.create_heating_circuits_entities(_FAKE_HASS, device))

    for name in (
        "K1B_CircType",
        "K1B_Prec",
        "K1B_dayNight",
        "K1B_kor",
        "K1B_korN",
        "K1B_korType",
        "K1B_misC",
        "K1B_misO",
    ):
        assert name in created, name
    # Still allowlist-only: no confirmed meaning, no entity.
    assert "K1B_recSrc" not in created
    assert "K1B_recType" not in created


def test_pump_anti_blocking_interval_is_created_for_peltec2() -> None:
    device = _device("peltec2", {"PVAL_582_0": "240", "B_KONF": "42"})
    entities = WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device)
    by_param = {e._param_name: e for e in entities}

    assert "PVAL_582_0" in by_param
    entity = by_param["PVAL_582_0"]
    assert entity.native_value == 240
    assert entity.suggested_display_precision == 0
    # A setting, not a measurement: no long-term statistics.
    assert entity.state_class is None


def test_pump_anti_blocking_interval_is_not_created_for_peltec() -> None:
    """Settings-slot numbering is controller-specific and only 582 on PelTec II
    is confirmed, so the mapping must not leak onto the older family."""
    device = _device("peltec", {"PVAL_582_0": "240"})
    created = _created(WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device))
    assert "PVAL_582_0" not in created
