"""The portal mixes session fields into the realtime frames.

`_token` is a portal session token and `_sign` a request signature. Cached as
boiler parameters they were written into the diagnostics download, which is the
file users attach to public issue reports.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "centrometal_boiler"))

from centrometal_web_boiler.parameter_filters import is_session_parameter  # noqa: E402
from centrometal_web_boiler.WebBoilerDeviceCollection import (  # noqa: E402
    WebBoilerDevice,
    WebBoilerDeviceCollection,
)


def test_session_fields_are_recognised() -> None:
    assert is_session_parameter("_token") is True
    assert is_session_parameter("_sign") is True
    assert is_session_parameter("_sync") is True
    # Message bookkeeping that carries no credential stays: it is useful when
    # debugging the realtime stream.
    assert is_session_parameter("PING") is False
    assert is_session_parameter("clMsgId") is False
    assert is_session_parameter("B_Tk1") is False


def test_session_fields_never_enter_the_parameter_cache() -> None:
    async def runner() -> None:
        collection = WebBoilerDeviceCollection("user@example.com")
        device = WebBoilerDevice("user@example.com")
        device["serial"] = "SN1"
        device["type"] = "peltec2"
        collection["SN1"] = device

        frame = {
            "headers": {"subscription": "sub-0", "destination": "/topic/cm.inst.peltec2.SN1"},
            "body": '{"B_Tk1": "45.1", "_token": "1mAKMcIQeI0Ox4kLdNtq", "_sign": "87241b80", "_sync": "id"}',
        }
        await collection.parse_real_time_frame(frame)

        assert device.has_parameter("B_Tk1")
        for name in ("_token", "_sign", "_sync"):
            assert not device.has_parameter(name), name

    asyncio.run(runner())
