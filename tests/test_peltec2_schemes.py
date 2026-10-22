"""The PelTec II hydraulic scheme table against the manuals it was taken from.

Boiler book "Technical instructions PelTec II Lambda", chapter 4.2.2, pages
23-58; controller book "Technical instructions Controller PelTec II Lambda",
"DHW priority" (page 52) and "Installation" (page 54).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler import peltec2  # noqa: E402
from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
)
from custom_components.centrometal_boiler.sensors.WebBoilerConfigurationSensor import (  # noqa: E402
    WebBoilerConfigurationSensor,
)
from custom_components.centrometal_boiler.sensors.WebBoilerGenericSensor import (  # noqa: E402
    WebBoilerGenericSensor,
)
from custom_components.centrometal_boiler.sensors.WebBoilerHeatingCircuitSensor import (  # noqa: E402
    WebBoilerHeatingCircuitSensor,
)

_FAKE_HASS = SimpleNamespace(config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")))


def _device(konf, *parameters: str) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device.update(
        {
            "id": 1001,
            "serial": "SN1",
            "type": "peltec2",
            "product": "PelTec II Lambda",
            "__client": None,
            "__system": None,
            "__prefix": "",
            "__multi_device": False,
        }
    )
    if konf is not None:
        device.create_parameter("B_KONF", str(konf))
    for name in parameters:
        device.create_parameter(name, "0")
    return device


def _conf_entities(device) -> dict:
    return {e._param_name: e for e in WebBoilerGenericSensor.create_conf_entities(_FAKE_HASS, device)}


def test_the_table_covers_the_45_schemes_of_the_manual() -> None:
    assert sorted(peltec2.PELTEC2_SCHEMES) == list(range(1, 46))
    for number, scheme in peltec2.PELTEC2_SCHEMES.items():
        assert scheme.label.startswith(f"{number}. ")


def test_dhw_priority_schemes_match_the_controller_manual() -> None:
    """Page 52 lists every scheme whose DHW tank has its own pump or valve."""
    listed = {5, 13, 14, 15, 16} | {2, 6, 9, 10, 17, 18, 19, 20, 25, 32, 35, 40, 43, 44}
    assert {konf + 1 for konf in peltec2.DHW_PRIORITY_CONFIGURATIONS} == listed


def test_buffer_schemes_match_the_controller_manual() -> None:
    """Page 54: schemes 11-44 have an accumulation (buffer) tank."""
    assert {konf + 1 for konf in peltec2.BUFFER_CONFIGURATIONS} == set(range(11, 45))


def test_scheme_43_is_buffer_plus_dhw_on_k1() -> None:
    """Boiler book page 57: P1 - DHW (K1), P2 - Recirculation DHW (K1)."""
    scheme = peltec2.peltec2_scheme(42)
    assert scheme.label == "43. BUF + K1 DHW"
    assert scheme.relays == {1: "DHW Pump (K1)", 2: "DHW Recirculation Pump (K1)"}
    assert peltec2.configuration_has_buffer(42)
    assert peltec2.configuration_has_dhw_priority(42)
    assert peltec2.configuration_has_dhw_recirculation(42)


def test_scheme_43_keeps_one_entity_for_the_dhw_pump() -> None:
    """P1 and K1B_P are the same pump on scheme 43; only one entity for it."""
    device = _device(42, "B_P1", "B_P2", "B_P3", "B_P4", "K1B_P")
    created = _conf_entities(device)
    assert "B_P1" not in created
    assert created["B_P2"].name.endswith("P2 DHW Recirculation Pump (K1)")
    assert created["B_P2"].extra_state_attributes["Function"] == "DHW Recirculation Pump (K1)"
    # Relays the scheme does not use keep their plain name.
    assert created["B_P3"].name.endswith("P3 Pump")
    assert created["B_P3"].extra_state_attributes["Function"] == "Not used in this configuration"

    circuit = {
        e._param_name: e
        for e in WebBoilerHeatingCircuitSensor.create_heating_circuits_entities(_FAKE_HASS, device)
    }
    assert circuit["K1B_P"].name.endswith("DHW Pump (K1)")


def test_p1_keeps_its_entity_where_it_is_not_the_k1_pump() -> None:
    """Scheme 17: P1 is the buffer pump, K1's DHW pump is P2."""
    created = _conf_entities(_device(16, "B_P1", "K1B_P"))
    assert created["B_P1"].name.endswith("P1 Buffer Tank Pump")


def test_unknown_scheme_keeps_the_previous_behaviour() -> None:
    created = _conf_entities(_device(None, "B_P1", "B_P2", "K1B_P"))
    assert "B_P1" not in created
    assert created["B_P2"].name.endswith("P2 Pump")
    assert "Function" not in created["B_P2"].extra_state_attributes

    circuit = {
        e._param_name: e
        for e in WebBoilerHeatingCircuitSensor.create_heating_circuits_entities(_FAKE_HASS, _device(None, "K1B_P"))
    }
    assert circuit["K1B_P"].name.endswith("K1 Circuit Pump")


def test_configuration_sensor_shows_the_scheme_and_its_relays() -> None:
    entity = WebBoilerConfigurationSensor.create_entities(_FAKE_HASS, _device(42))[0]
    assert entity.native_value == "43. BUF + K1 DHW"
    attrs = entity.extra_state_attributes
    assert attrs["Buffer tank"] == "CAS"
    assert attrs["DHW tank"] == "Own pump"
    assert attrs["DHW recirculation"] is True
    assert attrs["P1"] == "DHW Pump (K1)"
    assert attrs["P2"] == "DHW Recirculation Pump (K1)"
    assert attrs["P3"] == "Not used"
    assert attrs["P4"] == "Not used"


def test_buffer_and_dhw_entities_follow_the_scheme() -> None:
    optional = ("B_bup", "B_PTV_PRI", "B_REC", "B_REO")
    # Scheme 43: buffer, DHW tank with its own pump, recirculation.
    assert set(optional) <= set(_conf_entities(_device(42, *optional)))
    # Scheme 1: hydraulic crossover and a K1 mixing circuit, nothing else.
    assert set(optional).isdisjoint(_conf_entities(_device(0, *optional)))
    # Scheme 12: buffer with an integrated DHW tank -- recirculation, no priority.
    created = set(_conf_entities(_device(11, *optional)))
    assert {"B_bup", "B_REC", "B_REO"} <= created
    assert "B_PTV_PRI" not in created
