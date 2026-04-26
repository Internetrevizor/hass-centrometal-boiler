import logging

from homeassistant.core import HomeAssistant

from .sensors.WebBoilerDeviceTypeSensor import WebBoilerDeviceTypeSensor
from .sensors.WebBoilerGenericSensor import WebBoilerGenericSensor
from .sensors.WebBoilerConfigurationSensor import WebBoilerConfigurationSensor
from .sensors.WebBoilerWorkingTableSensor import WebBoilerWorkingTableSensor
from .sensors.WebBoilerFireGridSensor import WebBoilerFireGridSensor
from .sensors.WebBoilerOperationStateSensor import WebBoilerOperationStateSensor
from .sensors.WebBoilerHeatingCircuitSensor import WebBoilerHeatingCircuitSensor
from .sensors.WebBoilerBinaryOnOffSensor import create_binary_state_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    all_entities = []
    web_boiler_client = config_entry.runtime_data.client
    for device in web_boiler_client.data.values():
        all_entities.extend(create_binary_state_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_common_entities(hass, device))
        all_entities.extend(WebBoilerConfigurationSensor.create_entities(hass, device))
        all_entities.extend(WebBoilerWorkingTableSensor.create_entities(hass, device))
        all_entities.extend(WebBoilerDeviceTypeSensor.create_entities(hass, device))
        all_entities.extend(WebBoilerHeatingCircuitSensor.create_heating_circuits_entities(hass, device))
        if device["type"] in ("peltec", "peltec2"):
            all_entities.extend(WebBoilerFireGridSensor.create_entities(hass, device))
        if device["type"] == "peltec2":
            all_entities.extend(WebBoilerOperationStateSensor.create_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_conf_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_temperatures_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_unknown_entities(hass, device))

    deduped_entities = []
    seen_ids = set()
    for entity in all_entities:
        uid = getattr(entity, "unique_id", None)
        if uid is None or uid not in seen_ids:
            if uid is not None:
                seen_ids.add(uid)
            deduped_entities.append(entity)
        else:
            _LOGGER.debug("Skipping duplicate entity with unique_id %s (%s)", uid, getattr(entity, "name", "<no name>"))

    async_add_entities(deduped_entities, True)
