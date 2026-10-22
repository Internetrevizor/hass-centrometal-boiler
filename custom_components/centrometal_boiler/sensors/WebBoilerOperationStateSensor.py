from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant

from .WebBoilerGenericSensor import WebBoilerGenericSensor

# Stage texts follow the table "Operation stages (shown on the screen)" in
# "Technical instructions Controller PelTec II Lambda", pages 96-97. Home
# Assistant automations compare against these strings, so each one is only
# changed where it disagreed with the manual; tests/test_operation_stage_labels.py
# pins the full set.
_B_STATE_MAP: dict[str, str] = {
    "OFF": "OFF: Switched off",
    "S0": "S0: Initial fan blowing, waiting for grate initial position",
    "S1": "S1: Not in use",
    "S2": "S2: Initial pellet filling",
    "S3": "S3: Waiting for flame",
    "S3-1": "S3-1: Extended ignition / flame verification",
    "S3-2": "S3-2: Additional ignition fuel charge",
    # Wording from the stage table in "Technical instructions Controller PelTec
    # II Lambda", page 96. S4 follows S3 ("Waiting for flame to appear"): the
    # flame is already burning and the heater keeps working for a while. The
    # old "Electric heater igniting" described S3, not S4.
    "S4": "S4: Electric heater working after flame appears",
    "S5": "S5: Flame developing",
    "SP1": "SP1: Stabilising 1",
    "SP2": "SP2: Stabilising 2",
    "SP3": "SP3: Stabilising 3",
    "SP4": "SP4: Stabilising 4",
    "SP5": "SP5: Stabilising 5",
    "S6": "S6: Additional flame development",
    "D0": "D0: Power D0 (min)",
    "D1": "D1: Power D1",
    "D2": "D2: Power D2",
    "D3": "D3: Power D3",
    "D4": "D4: Power D4",
    "D5": "D5: Power D5",
    "D6": "D6: Power D6 (max)",
    "S7": "S7: Shutdown stage",
    "S7-1": "S7-1: Shutdown 1, waiting for flame to disappear",
    "S7-2": "S7-2: Shutdown 2, fan at maximum speed",
    "S7-3": "S7-3: Standby, waiting for start request",
    "PF0": "PF0: Power failure — electric heater on, waiting for flame",
    "PF1": "PF1: Power failure — flame appeared, electric heater off",
    "PF2": "PF2: Power failure — flame developing",
    "PF3": "PF3: Power failure — waiting for flame to disappear",
    "PF4": "PF4: Power failure — final fan blowing",
    "C0": "C0: Grate cleaning",
}


def _stage_details(code: str) -> dict[str, object]:
    description = _B_STATE_MAP.get(code, f"Unknown ({code})")
    if ": " in description:
        description = description.split(": ", 1)[1]

    power_level = int(code[1:]) if len(code) == 2 and code.startswith("D") and code[1:].isdigit() else None
    if code == "OFF":
        group = "off"
    elif code == "S7-3":
        group = "standby"
    elif code.startswith("S7"):
        group = "shutdown"
    elif code == "C0":
        group = "cleaning"
    elif code.startswith("PF"):
        group = "power_failure_recovery"
    elif power_level is not None:
        group = "modulation"
    elif code.startswith(("S", "SP")):
        group = "ignition_startup"
    else:
        group = "unknown"
    return {
        "raw_stage": code,
        "stage_group": group,
        "description": description,
        "power_level": power_level,
    }


class WebBoilerOperationStateSensor(WebBoilerGenericSensor):
    @property
    def native_value(self) -> str:
        raw = self.parameter.get("value")
        if raw is None:
            return "Unknown"
        key = str(raw).strip()
        return _B_STATE_MAP.get(key, f"Unknown ({key})")

    @property
    def extra_state_attributes(self) -> dict:
        base = super().extra_state_attributes or {}
        attrs = dict(base)
        raw = self.parameter.get("value")
        code = "" if raw is None else str(raw).strip()
        details = _stage_details(code)
        attrs["Raw stage code"] = raw
        attrs["Stage group"] = details["stage_group"]
        attrs["Description"] = details["description"]
        attrs["Power level"] = details["power_level"]
        return attrs

    @staticmethod
    def create_entities(hass: HomeAssistant, device) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        if not WebBoilerGenericSensor._device_has_parameter(device, "B_STATE"):
            return entities
        parameter = device.get_parameter("B_STATE")
        if parameter.get("used"):
            return entities
        entities.append(
            WebBoilerOperationStateSensor(
                hass,
                device,
                [None, "mdi:state-machine", None, "Boiler State"],
                parameter,
            )
        )
        return entities
