from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from .WebBoilerGenericSensor import WebBoilerGenericSensor


class WebBoilerConfigurationSensor(WebBoilerGenericSensor):
    @property
    def native_value(self):
        if self.device["type"] in ("peltec", "peltec2"):
            configurations = [
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
            try:
                idx = int(self.parameter["value"])
                if 0 <= idx < len(configurations):
                    return configurations[idx]
                if idx >= 0:
                    # B_KONF is zero-based and the labels above are written
                    # 1-based, matching the portal ("1. DHW" is B_KONF 0). The
                    # list only covers the PelTec schemes; PelTec II has many
                    # more. Reporting the raw index for those showed a number
                    # one below the one on the portal's own screen, so report
                    # the portal's number instead of the internal one.
                    return str(idx + 1)
            except Exception:
                pass
        return self.parameter["value"]

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
