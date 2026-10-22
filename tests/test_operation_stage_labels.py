"""Pin the "Boiler State" texts.

Home Assistant automations compare against these strings, so any change to one
of them is a breaking change and has to be deliberate. The wording follows the
stage table in "Technical instructions Controller PelTec II Lambda", pages
96-97.
"""

from __future__ import annotations

from custom_components.centrometal_boiler.sensors.WebBoilerOperationStateSensor import (
    _B_STATE_MAP,
    _stage_details,
)

EXPECTED = {
    "OFF": "OFF: Switched off",
    "S0": "S0: Initial fan blowing, waiting for grate initial position",
    "S1": "S1: Not in use",
    "S2": "S2: Initial pellet filling",
    "S3": "S3: Waiting for flame",
    "S3-1": "S3-1: Extended ignition / flame verification",
    "S3-2": "S3-2: Additional ignition fuel charge",
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


def test_stage_texts_are_unchanged_except_where_deliberately_corrected() -> None:
    assert _B_STATE_MAP == EXPECTED


def test_s4_is_the_stage_after_the_flame_appears() -> None:
    """S4 used to read "Electric heater igniting", which is S3's job."""
    assert _B_STATE_MAP["S4"] == "S4: Electric heater working after flame appears"
    details = _stage_details("S4")
    assert details["description"] == "Electric heater working after flame appears"
    assert details["stage_group"] == "ignition_startup"
