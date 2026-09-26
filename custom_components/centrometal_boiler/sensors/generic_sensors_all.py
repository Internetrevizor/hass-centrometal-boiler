from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfTemperature

GENERIC_SENSORS_COMMON = {
    "B_CMD": [None, "mdi:state-machine", None, "Command Active"],
    "B_BRAND": [None, "mdi:information", None, "Brand"],
    "B_INST": [None, "mdi:information", None, "Installation"],
    "B_PRODNAME": [None, "mdi:information", None, "Product Name"],
    "B_VER": [None, "mdi:information", None, "Firmware Version"],
    "B_sng": [None, "mdi:information", None, "Nominal Power"],
    "B_WifiVER": [None, "mdi:wifi", None, "Wifi Box Version"],
}


def is_editable_setting(row) -> bool:
    """Whether the portal offers this settings row for editing.

    Kept here, beside the read-only table, so the two platforms cannot both
    claim the same slot: number.py uses the same predicate.
    """
    return (
        isinstance(row, dict)
        and row.get("dbindex") is not None
        and row.get("tip") in {"temperatura", "temperatura_0.1"}
        and row.get("user") == "rw"
        and bool(row.get("showButton"))
    )


def _device_really_has_parameter(device, param_name: str) -> bool:
    return (
        isinstance(device, dict)
        and "parameters" in device
        and isinstance(device["parameters"], dict)
        and param_name in device["parameters"]
    )


def get_generic_temperature_settings_sensors(device):
    """Read-only sensors for the controller's settings slots.

    A slot the portal lets this account edit gets a number entity instead, on
    the number platform -- one entity per setting, not a read-only sensor
    beside an editable one.
    """
    temperature_settings: dict[str, list] = {}
    for value in device.get("temperatures", {}).values():
        if is_editable_setting(value):
            continue
        dbindex = value["dbindex"]
        value_param_name = f"PVAL_{dbindex}_0"
        default_param_name = f"PDEF_{dbindex}_0"
        min_param_name = f"PMIN_{dbindex}_0"
        max_param_name = f"PMAX_{dbindex}_0"

        if not _device_really_has_parameter(device, value_param_name):
            continue

        attributes: dict[str, str] = {}
        if _device_really_has_parameter(device, default_param_name):
            attributes[default_param_name] = "Default"
        if _device_really_has_parameter(device, min_param_name):
            attributes[min_param_name] = "Minimum"
        if _device_really_has_parameter(device, max_param_name):
            attributes[max_param_name] = "Maximum"

        temperature_settings[value_param_name] = [
            UnitOfTemperature.CELSIUS,
            "mdi:thermometer",
            SensorDeviceClass.TEMPERATURE,
            value["naslov"],
            attributes,
        ]
    return temperature_settings
