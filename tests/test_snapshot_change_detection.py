"""The status snapshot repeats every parameter on every poll.

Measured by replaying a PelTec II Lambda debug capture (2026-09-26, eight
consecutive status responses) through this module: 880 entity notifications
before the change, 238 after — 73% of them were for a reading that had not
moved. Skipping them means a refresh can legitimately write no state at all,
so recovery from a stale period is handled explicitly in WebBoilerClient.

The portal's own "ut" cannot be used to decide this: for a settings slot it is
the time the setting was last changed, but for live telemetry it is just the
time of the poll.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "centrometal_boiler"))

from centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
    WebBoilerDeviceCollection,
)


def _collection() -> tuple[WebBoilerDeviceCollection, WebBoilerDevice, list]:
    collection = WebBoilerDeviceCollection("user@example.com")
    device = WebBoilerDevice("user@example.com")
    device["id"] = 7280
    device["serial"] = "SN1"
    device["type"] = "peltec2"
    collection["SN1"] = device
    notified: list[str] = []

    async def on_update(_device, parameter, _create=False):
        notified.append(parameter["name"])

    collection.set_on_update_callback(on_update)
    return collection, device, notified


def _status(params: dict[str, tuple[object, int]]) -> dict:
    return {"7280": {"params": {k: {"v": v, "ut": ut} for k, (v, ut) in params.items()}}}


def test_first_snapshot_notifies_everything() -> None:
    async def runner() -> None:
        collection, device, notified = _collection()
        await collection.parse_installation_statuses(_status({"B_Tk1": ("45.1", 100), "B_Tva1": ("10", 100)}))
        assert sorted(notified) == ["B_Tk1", "B_Tva1"]
        assert device.get_parameter("B_Tk1")["value"] == "45.1"

    asyncio.run(runner())


def test_repeating_the_same_snapshot_notifies_nothing() -> None:
    async def runner() -> None:
        collection, _device, notified = _collection()
        snapshot = _status({"B_Tk1": ("45.1", 100), "B_Tva1": ("10", 100)})
        await collection.parse_installation_statuses(snapshot)
        notified.clear()
        await collection.parse_installation_statuses(snapshot)
        assert notified == []

    asyncio.run(runner())


def test_only_the_parameters_that_moved_are_notified() -> None:
    async def runner() -> None:
        collection, device, notified = _collection()
        await collection.parse_installation_statuses(_status({"B_Tk1": ("45.1", 100), "B_Tva1": ("10", 100)}))
        notified.clear()
        await collection.parse_installation_statuses(_status({"B_Tk1": ("46.0", 160), "B_Tva1": ("10", 100)}))
        assert notified == ["B_Tk1"]
        assert device.get_parameter("B_Tk1")["value"] == "46.0"
        # The untouched one keeps its value, it was simply not re-announced.
        assert device.get_parameter("B_Tva1")["value"] == "10"

    asyncio.run(runner())


def test_a_bumped_portal_timestamp_alone_does_not_notify() -> None:
    """The portal bumps "ut" every poll for live telemetry even when the
    reading is identical — B_KONF, which cannot change, had its "ut" advanced
    by exactly the poll interval eight times running. Treating that as an
    update would write every entity on every refresh and make "Last updated"
    read as the poll time everywhere."""

    async def runner() -> None:
        collection, device, notified = _collection()
        await collection.parse_installation_statuses(_status({"B_Tk1": ("45.1", 100)}))
        notified.clear()
        await collection.parse_installation_statuses(_status({"B_Tk1": ("45.1", 900)}))
        assert notified == []
        # "Last updated" keeps the time the reading actually changed.
        assert device.get_parameter("B_Tk1")["timestamp"] == 100

    asyncio.run(runner())


def test_realtime_frames_follow_the_same_rule() -> None:
    """So "Last updated" means the same thing whichever path delivered it."""

    async def runner() -> None:
        collection, device, notified = _collection()
        frame = {
            "headers": {"subscription": "sub-0", "destination": "/topic/cm.inst.peltec2.SN1"},
            "body": '{"B_Tk1": "45.1"}',
        }
        await collection.parse_real_time_frame(frame)
        assert notified == ["B_Tk1"]
        first_seen = device.get_parameter("B_Tk1")["timestamp"]
        notified.clear()
        await collection.parse_real_time_frame(frame)
        assert notified == []
        assert device.get_parameter("B_Tk1")["timestamp"] == first_seen

    asyncio.run(runner())


def test_notify_all_updated_still_forces_every_entity() -> None:
    """The escape hatch used on websocket connect and on recovery from a stale
    period, which must not be affected by the change detection above."""

    async def runner() -> None:
        collection, _device, notified = _collection()
        snapshot = _status({"B_Tk1": ("45.1", 100), "B_Tva1": ("10", 100)})
        await collection.parse_installation_statuses(snapshot)
        notified.clear()
        await collection.parse_installation_statuses(snapshot)
        assert notified == []
        await collection.notify_all_updated()
        assert sorted(notified) == ["B_Tk1", "B_Tva1"]

    asyncio.run(runner())
