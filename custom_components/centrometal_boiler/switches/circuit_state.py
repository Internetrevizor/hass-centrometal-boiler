"""Circuit on/off decision logic, free of Home Assistant imports.

Kept separate so it can be tested anywhere, including where Home Assistant is
not installed. The switch entity in ``WebBoilerCircuitSwitch`` is the framework
glue; every rule about what "on" means for a circuit row lives here.
"""

from __future__ import annotations

import re
from typing import Any

# Circuit rows are titled after the circuit they control ("K1 heating circuit
# (Off / On)"), and that circuit's own on/off parameter is "<prefix>B_onOff".
_CIRCUIT_PREFIX = re.compile(r"^\s*([CK]\d)\b", re.IGNORECASE)

_TRUE_WORDS = ("1", "on", "true", "yes", "active", "enabled")
_FALSE_WORDS = ("0", "off", "false", "no", "inactive", "disabled")


def circuit_state_fallback_name(naslov: Any) -> str | None:
    """Return the circuit's own on/off parameter for a portal row title.

    The switch's primary state source is the row's PVAL slot, but the portal
    does not send that slot in every status response -- verified against a
    PelTec II Lambda capture in which ``PVAL_272_0`` was absent from eight
    consecutive status responses while ``K1B_onOff`` was present in all eight.
    Without a fallback the switch reports ``unknown`` for as long as the portal
    keeps omitting the slot, and Home Assistant renders it as two buttons
    rather than a toggle.
    """
    match = _CIRCUIT_PREFIX.match(str(naslov or ""))
    if match is None:
        return None
    return f"{match.group(1).upper()}B_onOff"


def coerce_number(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        return None


def coerce_bool(value: Any) -> bool | None:
    """Return the boolean a portal value denotes, or None when unrecognised.

    Never guesses: an unrecognised value must not become a default of True.
    """
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def state_from_slot(pval: Any, pmin: Any = None, pmax: Any = None) -> bool | None:
    """Circuit state from the row's own PVAL slot, or None if unusable.

    Some Centrometal circuit rows, especially DHW, do not report the live ON
    state as exactly PMAX. The command API still uses 1/0, while the parameter
    table may expose PMAX as a limit/option value instead of the current ON
    value. Treat anything different from PMIN/OFF as ON, and keep PMAX as a
    fallback for devices that do not expose PMIN.
    """
    if pval is None:
        return None

    state = coerce_bool(pval)
    if state is not None:
        return state

    number = coerce_number(pval)
    if number is None:
        # "?" -- the placeholder a parameter carries before the controller has
        # ever reported it.
        return None

    off_number = coerce_number(pmin)
    if off_number is not None:
        return number != off_number

    on_number = coerce_number(pmax)
    if on_number is not None:
        return number == on_number

    return number != 0


def state_from_circuit_parameter(value: Any) -> bool | None:
    """Circuit state from the circuit's own on/off parameter."""
    state = coerce_bool(value)
    if state is not None:
        return state
    number = coerce_number(value)
    return None if number is None else number != 0
