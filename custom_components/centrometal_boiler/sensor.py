import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .sensors.WebBoilerBinaryOnOffSensor import create_binary_state_entities
from .sensors.WebBoilerConfigurationSensor import WebBoilerConfigurationSensor
from .sensors.WebBoilerDeviceTypeSensor import WebBoilerDeviceTypeSensor
from .sensors.WebBoilerErrorsSensor import WebBoilerErrorsSensor
from .sensors.WebBoilerFireGridSensor import WebBoilerFireGridSensor
from .sensors.generic_sensors_all import is_editable_setting
from .sensors.WebBoilerGenericSensor import WebBoilerGenericSensor
from .sensors.WebBoilerHeatingCircuitSensor import (
    CIRCUIT_PARAMETER_NAMES,
    WebBoilerHeatingCircuitSensor,
)
from .sensors.WebBoilerOperationStateSensor import WebBoilerOperationStateSensor

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry, async_add_entities):
    all_entities = []
    web_boiler_client = config_entry.runtime_data.client
    devices = list(web_boiler_client.data.values())

    for device in devices:
        all_entities.extend(create_binary_state_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_common_entities(hass, device))
        all_entities.extend(WebBoilerConfigurationSensor.create_entities(hass, device))

        # The synthetic device-type sensor is redundant for PelTec II because
        # the actual product is already exposed and is part of device metadata.
        if device.get("type") != "peltec2":
            all_entities.extend(WebBoilerDeviceTypeSensor.create_entities(hass, device))

        all_entities.extend(WebBoilerHeatingCircuitSensor.create_heating_circuits_entities(hass, device))

        # The controller manual exposes burner-grate position and movement.
        # Keep the existing entity implementation and unique ID for both
        # PelTec generations.
        if device.get("type") in {"peltec", "peltec2"}:
            all_entities.extend(WebBoilerFireGridSensor.create_entities(hass, device))

        if device.get("type") == "peltec2":
            all_entities.extend(WebBoilerOperationStateSensor.create_entities(hass, device))

        all_entities.extend(WebBoilerGenericSensor.create_conf_entities(hass, device))
        all_entities.extend(WebBoilerGenericSensor.create_temperatures_entities(hass, device))
        all_entities.extend(WebBoilerErrorsSensor.create_entities(hass, device))

        # Unknown raw entities are intentionally not created for PelTec II.
        # Other boiler families retain the previous diagnostic fallback.
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
            _LOGGER.debug(
                "Skipping duplicate entity with unique_id %s (%s)",
                uid,
                getattr(entity, "name", "<no name>"),
            )

    _async_remove_obsolete_sensors(hass, config_entry, devices, deduped_entities)

    async_add_entities(deduped_entities, True)


def _async_remove_obsolete_sensors(hass: HomeAssistant, config_entry, devices, entities) -> None:
    """Drop registry entries this build deliberately no longer creates.

    Deleting a registry entry is irreversible: it takes the entity_id, the
    user's rename, the area assignment and the continuity of its history with
    it. The decision is therefore made against a snapshot that is checked for
    completeness first — see device_snapshot_is_complete().
    """
    registry = er.async_get(hass)
    current_unique_ids = {
        entity.unique_id for entity in entities if getattr(entity, "unique_id", None) is not None
    }
    devices_by_serial = {str(device["serial"]): device for device in devices}

    for serial, device in devices_by_serial.items():
        if not device_snapshot_is_complete(device):
            _LOGGER.warning(
                "Centrometal device %s reported an incomplete parameter snapshot; skipping cleanup of "
                "obsolete entities so a temporary portal or boiler outage cannot delete working entities",
                serial,
            )

    for registry_entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if not registry_entry.entity_id.startswith("sensor."):
            continue
        if not registry_entry_is_obsolete(registry_entry.unique_id, current_unique_ids, devices_by_serial):
            continue
        # Removing an entity is destructive and permanent, so it is logged at
        # INFO: if this ever fires in bulk, the log should say so without the
        # user having to turn on debug first.
        _LOGGER.info(
            "Removing obsolete Centrometal sensor registry entry %s (%s)",
            registry_entry.entity_id,
            registry_entry.unique_id,
        )
        registry.async_remove(registry_entry.entity_id)


# A complete controller snapshot always carries the controller's own identity
# fields. When none of them are there, the portal returned something
# degenerate — a partial response, or a boiler that has been offline long
# enough for the cloud to drop fields — and nothing in it is solid enough to
# delete a user's entities over.
SNAPSHOT_IDENTITY_PARAMETERS = ("B_VER", "B_PRODNAME", "B_KONF", "B_sng", "B_STATE")


def device_snapshot_is_complete(device) -> bool:
    """Whether this device's parameters look like a real controller snapshot."""
    return any(device.has_parameter(name) for name in SNAPSHOT_IDENTITY_PARAMETERS)


# Editable-setting slots. Unlike everything else, these do not come from the
# status snapshot: they arrive from a separate parameter-list fetch that the
# portal answers with a varying number of groups. A response that omits a group
# is not an error, so nothing upstream notices -- the slot simply is not there
# that time, the entity is not created, and cleanup used to conclude it was
# obsolete. Their registry entries are never deleted for that reason.
SETTINGS_SLOT_PREFIXES = ("PVAL_", "PDEF_", "PMIN_", "PMAX_")


def _slot_moved_to_the_number_platform(param_name: str, device) -> bool:
    """Whether this settings slot is now served by an editable number entity."""
    _family, _sep, rest = param_name.partition("_")
    dbindex = rest.partition("_")[0]
    for row in device.get("temperatures", {}).values():
        if str(row.get("dbindex")) == dbindex:
            return is_editable_setting(row)
    return False


def creatable_parameter_names(device) -> set[str]:
    """Parameter names this build would expose if the controller reported them.

    Anything in here is a parameter the integration still knows about, so its
    absence from one snapshot is a gap, not a removal. Observed in the field:
    a PelTec II Lambda reported PVAL_582_0 in one poll and omitted it in the
    next, with everything else unchanged.
    """
    names = set(WebBoilerGenericSensor.generic_map_for_device(device))
    names.update(CIRCUIT_PARAMETER_NAMES)
    for dbindex in device.get("temperatures", {}):
        names.add(f"PVAL_{dbindex}_0")
    for circuit in device.get("circuits", {}).values():
        names.add(f"PVAL_{circuit.get('dbindex')}_0")
    return names


def registry_entry_is_obsolete(unique_id: str, current_unique_ids: set[str], devices_by_serial: dict) -> bool:
    """Decide whether a registry entry is safe to delete.

    Kept a pure function so the rule can be tested directly — it is the part
    that decides whether a user loses an entity_id and its history.
    """
    if unique_id in current_unique_ids:
        return False
    serial, separator, param_name = unique_id.partition("-")
    if not separator:
        # Not the "<serial>-<PARAM>" shape this integration creates; something
        # else owns it, or an older scheme did. Leave it alone.
        return False
    device = devices_by_serial.get(serial)
    if device is None:
        # A device that is not in this account's data right now says nothing
        # about whether its entities are obsolete.
        return False
    if not device_snapshot_is_complete(device):
        return False
    if param_name.startswith(SETTINGS_SLOT_PREFIXES):
        # A slot that became an editable number entity no longer has a
        # read-only sensor, and that is a decision rather than a gap, so its
        # old sensor entry is genuinely obsolete.
        return _slot_moved_to_the_number_platform(param_name, device)
    if param_name in creatable_parameter_names(device) and not device.has_parameter(param_name):
        # The build still maps this parameter; the controller just did not send
        # it in the snapshot this setup ran against. Deleting the entry here
        # would cost the entity_id, the rename, the area and the history for a
        # gap that closes itself on the next poll.
        return False
    return True
