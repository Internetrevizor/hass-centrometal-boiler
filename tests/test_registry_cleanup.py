"""Tests for the rule that decides whether a sensor registry entry is deleted.

Deleting a registry entry is irreversible and takes the entity_id, the user's
rename, the area assignment and the continuity of the entity's history with it.
Pruning entities that this build no longer creates is deliberate (it is what
keeps the PelTec II device page matching the strict allowlist), but it must
never run against a snapshot that is missing parameters for reasons that fix
themselves — a boiler that was offline while Home Assistant restarted, a
partial portal response.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.centrometal_boiler.centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
)
from custom_components.centrometal_boiler.sensor import (  # noqa: E402
    device_snapshot_is_complete,
    registry_entry_is_obsolete,
)


def _device(serial: str, *parameters: str) -> WebBoilerDevice:
    device = WebBoilerDevice("user@example.com")
    device["serial"] = serial
    device["type"] = "peltec2"
    device["product"] = "PelTec II Lambda"
    for name in parameters:
        device.create_parameter(name, 1)
    return device


def _devices(*devices: WebBoilerDevice) -> dict[str, WebBoilerDevice]:
    return {device["serial"]: device for device in devices}


def test_entry_for_a_currently_created_entity_is_kept() -> None:
    devices = _devices(_device("SN1", "B_VER", "B_Tk1"))
    assert registry_entry_is_obsolete("SN1-B_Tk1", {"SN1-B_Tk1"}, devices) is False


def test_entry_we_no_longer_create_is_removed() -> None:
    devices = _devices(_device("SN1", "B_VER", "B_Tk1"))
    assert registry_entry_is_obsolete("SN1-Weather_Forecast", set(), devices) is True


def test_nothing_is_removed_when_the_snapshot_is_degenerate() -> None:
    """No identity parameters means the portal did not really tell us anything.

    This is the case that used to wipe a device page: entities are not created
    from a snapshot that never arrived, and every one of their registry entries
    was then deleted as "obsolete".
    """
    devices = _devices(_device("SN1"))
    assert device_snapshot_is_complete(devices["SN1"]) is False
    assert registry_entry_is_obsolete("SN1-B_Tk1", set(), devices) is False
    assert registry_entry_is_obsolete("SN1-Weather_Forecast", set(), devices) is False


def test_snapshot_with_any_identity_parameter_is_usable() -> None:
    assert device_snapshot_is_complete(_device("SN1", "B_PRODNAME")) is True
    assert device_snapshot_is_complete(_device("SN1", "B_STATE")) is True


def test_entry_for_an_unknown_device_is_kept() -> None:
    devices = _devices(_device("SN1", "B_VER", "B_Tk1"))
    assert registry_entry_is_obsolete("SN9-B_Tk1", set(), devices) is False


def test_entry_that_is_not_serial_dash_parameter_is_kept() -> None:
    devices = _devices(_device("SN1", "B_VER"))
    assert registry_entry_is_obsolete("SN1", set(), devices) is False


def test_entry_for_a_mapped_parameter_missing_from_the_snapshot_is_kept() -> None:
    """Observed in the field: a PelTec II Lambda reported PVAL_582_0 in one
    poll and omitted it in the next, with the rest of the snapshot unchanged.
    The parameter is still in the build's table, so the gap is the
    controller's, not a removal."""
    device = _device("SN1", "B_VER", "B_Tk1")
    devices = _devices(device)
    assert registry_entry_is_obsolete("SN1-PVAL_582_0", set(), devices) is False
    assert registry_entry_is_obsolete("SN1-B_Tva1", set(), devices) is False
    assert registry_entry_is_obsolete("SN1-K1B_Tpol1", set(), devices) is False


def test_entry_for_a_retired_mapping_is_still_removed() -> None:
    """The cleanup still does its job: a name no table knows about is gone."""
    device = _device("SN1", "B_VER", "B_Tk1")
    assert registry_entry_is_obsolete("SN1-Weather_Forecast", set(), _devices(device)) is True


def test_settings_slot_entries_are_never_removed() -> None:
    """Editable-setting slots come from the parameter-list fetch, which the
    portal answers with a varying number of groups. A short answer is not an
    error, so "no entity was created for it" says nothing about whether the
    setting still exists."""
    device = _device("SN1", "B_VER", "B_Tk1")
    devices = _devices(device)
    for slot in ("PVAL_67_0", "PDEF_67_0", "PMIN_291_0", "PMAX_292_0", "PVAL_582_0"):
        assert registry_entry_is_obsolete(f"SN1-{slot}", set(), devices) is False, slot


def test_settings_slots_survive_an_empty_metadata_response() -> None:
    """The case that actually happened: the device came back with no
    temperatures metadata at all, so the slots were not even in the creatable
    set."""
    device = _device("SN1", "B_VER")
    device["temperatures"] = {}
    device["circuits"] = {}
    assert registry_entry_is_obsolete("SN1-PVAL_67_0", set(), _devices(device)) is False


def test_the_old_sensor_entry_for_a_now_editable_slot_is_removed() -> None:
    """The slot moved to the number platform, so its read-only sensor entry is
    a deliberate retirement rather than a gap in the snapshot."""
    device = _device("SN1", "B_VER", "PVAL_67_0")
    device["temperatures"] = {
        "67": {
            "naslov": "Buffer tank temperature",
            "dbindex": 67,
            "tip": "temperatura",
            "user": "rw",
            "showButton": True,
        }
    }
    assert registry_entry_is_obsolete("SN1-PVAL_67_0", set(), _devices(device)) is True


def test_a_read_only_slot_keeps_its_sensor_entry() -> None:
    device = _device("SN1", "B_VER", "PVAL_70_0")
    device["temperatures"] = {
        "70": {"naslov": "Minimal", "dbindex": 70, "tip": "temperatura", "user": "r", "showButton": True}
    }
    assert registry_entry_is_obsolete("SN1-PVAL_70_0", set(), _devices(device)) is False
