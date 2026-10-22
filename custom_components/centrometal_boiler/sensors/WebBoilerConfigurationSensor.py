from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from ..peltec2 import peltec2_scheme
from .WebBoilerGenericSensor import WebBoilerGenericSensor

# The older PelTec's scheme list. PelTec II numbers its schemes differently and
# has 45 of them; those labels come from peltec2.PELTEC2_SCHEMES instead.
PELTEC_CONFIGURATIONS = [
    "1. DHW",
    "2. DHC",
    "3. DHW || DHC",
    "4. BUF",
    "5. DHW || BUF",
    "6. BUF -- IHC",
    "7. DHW || BUF -- IHC",
    "8. BUF -- DHW",
    "9. BUF -- IHC || DHW",
    "10. CRO",
    "11. CRO / BUF",
    "12. DHC || DHW(2)",
    "13. DHC 2X",
    "14. BUF--IHCX2",
    "15. CRO -- DHW",
]


class WebBoilerConfigurationSensor(WebBoilerGenericSensor):
    @property
    def native_value(self):
        value = self.parameter["value"]
        if self.device["type"] == "peltec2":
            scheme = peltec2_scheme(value)
            if scheme is not None:
                return scheme.label
        if self.device["type"] in ("peltec", "peltec2"):
            try:
                idx = int(value)
                if self.device["type"] == "peltec" and 0 <= idx < len(PELTEC_CONFIGURATIONS):
                    return PELTEC_CONFIGURATIONS[idx]
                if idx >= 0:
                    # B_KONF is zero-based and the portal numbers schemes from
                    # 1. Reporting the raw index for a scheme without a label
                    # showed a number one below the one on the portal's own
                    # screen, so report the portal's number instead.
                    return str(idx + 1)
            except Exception:
                pass
        return value

    @property
    def extra_state_attributes(self):
        attrs = dict(super().extra_state_attributes or {})
        if self.device["type"] != "peltec2":
            return attrs
        scheme = peltec2_scheme(self.parameter.get("value"))
        if scheme is None:
            return attrs
        attrs["Buffer tank"] = scheme.buffer or "None"
        attrs["DHW tank"] = {
            "pump": "Own pump",
            "diverter": "Diverter valve",
            "boiler": "On the boiler circuit",
        }.get(scheme.dhw, "Integrated in the buffer" if scheme.buffer == "CAS-B" else "None")
        attrs["DHW recirculation"] = scheme.recirculation
        for relay in range(1, 5):
            attrs[f"P{relay}"] = scheme.relays.get(relay, "Not used")
        return attrs

    @staticmethod
    def create_entities(hass: HomeAssistant, device) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        if WebBoilerGenericSensor._device_has_parameter(device, "B_KONF"):
            parameter = device.get_parameter("B_KONF")
            if not parameter.get("used"):
                entities.append(
                    WebBoilerConfigurationSensor(
                        hass,
                        device,
                        [None, "mdi:state-machine", None, "Configuration"],
                        parameter,
                    )
                )
        return entities
