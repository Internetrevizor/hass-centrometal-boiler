"""The heating-circuit switch must not sit at "unknown" when the portal omits
the row's PVAL slot.

Verified against a PelTec II Lambda debug capture (2026-09-26, 17:42-18:14):
`PVAL_272_0` was absent from all eight consecutive installation-status
responses in that window while `K1B_onOff` was present in all eight. The switch
read only the PVAL slot, so it reported `unknown` for the whole session and
Home Assistant rendered it as two buttons instead of a toggle.

These tests import the decision logic directly, without Home Assistant, so they
run in any environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "centrometal_boiler" / "switches"))

from circuit_state import (  # noqa: E402
    circuit_state_fallback_name,
    coerce_bool,
    state_from_circuit_parameter,
    state_from_slot,
)


def test_fallback_name_is_derived_from_the_portal_row_title() -> None:
    assert circuit_state_fallback_name("K1 heating circuit (Off / On)") == "K1B_onOff"
    assert circuit_state_fallback_name("C2 heating circuit") == "C2B_onOff"
    assert circuit_state_fallback_name("k3 krug") == "K3B_onOff"
    # No prefix to derive: no fallback, rather than a guessed one.
    assert circuit_state_fallback_name("Something else") is None
    assert circuit_state_fallback_name(None) is None
    assert circuit_state_fallback_name("") is None


def test_slot_decides_when_the_portal_sends_it() -> None:
    assert state_from_slot("1", "0", "1") is True
    assert state_from_slot("0", "0", "1") is False
    # PMAX as a limit rather than the live ON value: anything off PMIN is ON.
    assert state_from_slot("3", "0", "1") is True
    # No PMIN: fall back to comparing against PMAX.
    assert state_from_slot("1", None, "1") is True
    assert state_from_slot("2", None, "1") is False
    # Neither bound: nonzero is ON.
    assert state_from_slot("5", None, None) is True
    assert state_from_slot("0", None, None) is False


def test_slot_is_unusable_when_the_portal_omits_it() -> None:
    assert state_from_slot(None) is None
    # "?" is the placeholder a parameter carries before it is ever reported.
    assert state_from_slot("?") is None
    assert state_from_slot("?", "0", "1") is None


def test_circuit_parameter_answers_the_captured_shape() -> None:
    """No PVAL slot in the snapshot, K1B_onOff = 1: the switch must read ON."""
    assert state_from_slot(None) is None
    assert state_from_circuit_parameter("1") is True
    assert state_from_circuit_parameter("0") is False
    assert state_from_circuit_parameter(1) is True


def test_nothing_reported_stays_unknown() -> None:
    """No invented default: unknown is the honest answer, per the rule that an
    unrecognised boolean never becomes True."""
    assert state_from_circuit_parameter(None) is None
    assert state_from_circuit_parameter("?") is None
    assert coerce_bool("maybe") is None
