"""Portal-confirmed PelTec II value decoding helpers.

The rules in this module come from the authenticated Centrometal portal
JavaScript/templates captured on 2026-07-04.  Keeping the rules free of Home
Assistant imports makes them easy to unit test and reuse from sensor and binary
sensor entities.
"""

from __future__ import annotations

from math import isfinite
from typing import Any, NamedTuple

from .centrometal_web_boiler.parameter_filters import is_ignored_peltec2_parameter

__all__ = [
    "BUFFER_CONFIGURATIONS",
    "DHW_CONFIGURATIONS",
    "DHW_PRIORITY_CONFIGURATIONS",
    "DHW_RECIRCULATION_CONFIGURATIONS",
    "INTERNET_ACCESS",
    "PELTEC2_SCHEMES",
    "PelTec2Scheme",
    "START_TRANSITIONS",
    "STATUS_MARKS",
    "STATUS_MARK_DETAILS",
    "TANK_LEVELS",
    "configuration_has_buffer",
    "configuration_has_dhw",
    "configuration_has_dhw_priority",
    "configuration_has_dhw_recirculation",
    "decode_accessory_bitmask",
    "decode_input_bitmask",
    "decode_internet_access",
    "decode_start_transition",
    "decode_status_mark",
    "decode_status_mark_details",
    "decode_tank_level",
    "format_portal_hex",
    "is_ignored_peltec2_parameter",
    "parse_portal_hex",
    "peltec2_scheme",
    "portal_hex_bit_is_set",
    "relay_function",
    "valid_lambda",
    "valid_nonnegative_measurement",
    "valid_percentage",
    "valid_signal_db",
    "valid_temperature",
]


INTERNET_ACCESS = {
    1: "Supervision",
    2: "Supervision + control",
}

STATUS_MARKS = {
    0: "None",
    1: "R",
    2: "B",
    3: "T",
    4: "G",
    5: "F",
}

STATUS_MARK_DETAILS = {
    0: {
        "meaning": "No special shutdown activity",
        "category": "None",
        "temporary_shutdown": False,
        "documentation": "PelTec II Lambda controller manual",
    },
    1: {
        "meaning": "Shutdown after loss of flame during operation",
        "category": "Temporary shutdown reason",
        "temporary_shutdown": True,
        "documentation": "PelTec II Lambda controller manual",
    },
    2: {
        "meaning": "Shutdown after excessive pellet feed tube bimetal temperature",
        "category": "Temporary shutdown reason",
        "temporary_shutdown": True,
        "documentation": "PelTec II Lambda controller manual",
    },
    3: {
        "meaning": "Shutdown so the turbulator / flue passage cleaner can operate",
        "category": "Temporary shutdown reason",
        "temporary_shutdown": True,
        "documentation": "PelTec II Lambda controller manual",
    },
    4: {
        "meaning": "Shutdown because burner grate cleaning is required",
        "category": "Temporary shutdown reason",
        "temporary_shutdown": True,
        "documentation": "PelTec II Lambda controller manual",
    },
    5: {
        "meaning": "Shutdown associated with pellet tank filling or refilling",
        "category": "Temporary shutdown reason",
        "temporary_shutdown": True,
        "documentation": "Related official Centrometal controller manual",
    },
}

# B_start is the burner's commanded state, not a momentary transition. Every
# value below was read against B_STATE in a PelTec II Lambda capture
# (2026-09-26, v3.03dL):
#
#   0  B_STATE OFF
#   1  S0, S2, S3, S4, SP1 (ignition) and D4, D5, D6 (modulating) -- so it
#      stays 1 for the whole time the burner is lit, which is why "Starting"
#      was wrong: the boiler reported it while burning steadily
#   2  S7-1, S7-2, the shutdown sequence
#   3  C0, the cleaning phase. B_specG went to 4 ("shutdown because burner
#      grate cleaning is required") in the same millisecond as B_start = 2;
#      B_start became 3 fifteen seconds into C0 and returned to 1 in the same
#      millisecond as B_specG returning to 0. Labelled for the phase rather
#      than for the grate, since the same value presumably covers the
#      controller's other cleaning cycles.
#
# The detailed phase is the "Operation State" entity's job (B_STATE); this one
# answers whether the burner is meant to be running.
START_TRANSITIONS = {
    0: "Stopped",
    1: "Running",
    2: "Stopping",
    3: "Cleaning",
}

TANK_LEVELS = {
    0: "Empty",
    1: "Reserve",
    2: "Full",
}

class PelTec2Scheme(NamedTuple):
    """One PelTec II hydraulic configuration, as the boiler manual draws it.

    label          what the scheme contains, prefixed with its portal number
    buffer         "CAS", "CAS-B" (a buffer with an integrated DHW tank) or None
    dhw            how a separate DHW tank is loaded: by its own "pump", through
                   the "diverter" valve, straight off the "boiler" circuit, or
                   None when there is no separate DHW tank
    recirculation  whether the scheme has a DHW recirculation pump
    relays         what each of the P1..P4 relays drives; a relay missing here
                   is not used by the scheme
    """

    label: str
    buffer: str | None
    dhw: str | None
    recirculation: bool
    relays: dict[int, str]


# Every PelTec II configuration, keyed by the 1-based number the portal and the
# controller screen show. B_KONF is the same number minus one, so B_KONF 42 is
# scheme 43. Transcribed from "Technical instructions PelTec II Lambda" (boiler
# book, chapter 4.2.2 "Configuration / scheme", pages 23-58).
#
# This replaces a table taken from the older PelTec's fifteen-scheme list,
# which is numbered differently: it put a DHW tank in scheme 1 and a buffer in
# schemes 4-9, none of which have one on a PelTec II, and knew nothing of the
# buffer in schemes 11-42 and 44.
#
# Two independent checks agree with the transcription:
#   * the controller manual ("DHW priority", page 52) lists exactly the schemes
#     below whose DHW tank has its own pump or a diverter valve -- 2, 5, 6, 9,
#     10, 13-20, 25, 32, 35, 40, 43, 44 -- and its "Installation" table
#     (page 54) puts a buffer in exactly 11-44;
#   * a PelTec II Lambda v3.03dL capture on scheme 43 shows a buffer with both
#     sensors reporting and P1 switching in the same millisecond as K1B_P --
#     P1 is that scheme's DHW pump on K1, as page 57 draws it.
#
# The controller reports B_bup/B_PTV_PRI/B_REC/B_REO in every configuration,
# including ones with no buffer and no DHW tank, so their presence in a
# snapshot proves nothing; whether they mean anything comes from this table.
PELTEC2_SCHEMES: dict[int, PelTec2Scheme] = {
    1: PelTec2Scheme(
        "1. CRO + K1 mixing", buffer=None, dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump"},
    ),
    2: PelTec2Scheme(
        "2. CRO + K1 mixing + K2 DHW", buffer=None, dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Pump (K2)", 3: "DHW Recirculation Pump (K2)"},
    ),
    3: PelTec2Scheme(
        "3. CRO + K1 mixing + K2 direct", buffer=None, dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump"},
    ),
    4: PelTec2Scheme(
        "4. K1 direct", buffer=None, dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump"},
    ),
    5: PelTec2Scheme(
        "5. K1 direct + K2 DHW (diverter valve)", buffer=None, dhw="diverter", recirculation=True,
        relays={1: "K1 / DHW Pump (via Diverter Valve)", 2: "Diverter Valve", 3: "DHW Recirculation Pump (K2)"},
    ),
    6: PelTec2Scheme(
        "6. CRO + K1 direct + K2 DHW", buffer=None, dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Pump (K2)", 3: "DHW Recirculation Pump (K2)"},
    ),
    7: PelTec2Scheme(
        "7. CRO + K1 direct + K2 direct", buffer=None, dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump"},
    ),
    8: PelTec2Scheme(
        "8. K1 DHW (boiler circuit)", buffer=None, dhw="boiler", recirculation=True,
        relays={1: "DHW Recirculation Pump (K1)"},
    ),
    9: PelTec2Scheme(
        "9. CRO + K1 DHW", buffer=None, dhw="pump", recirculation=True,
        relays={1: "DHW Pump (K1)", 2: "DHW Recirculation Pump (K1)"},
    ),
    10: PelTec2Scheme(
        "10. CRO + K1 DHW + K2 DHW", buffer=None, dhw="pump", recirculation=True,
        relays={
            1: "DHW Pump (K1)",
            2: "DHW Pump (K2)",
            3: "DHW Recirculation Pump (K1)",
            4: "DHW Recirculation Pump (K2)",
        },
    ),
    11: PelTec2Scheme(
        "11. BUF", buffer="CAS", dhw=None, recirculation=False,
        relays={},
    ),
    12: PelTec2Scheme(
        "12. BUF with DHW", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "DHW Recirculation Pump"},
    ),
    13: PelTec2Scheme(
        "13. BUF + K1 DHW (diverter valve)", buffer="CAS", dhw="diverter", recirculation=True,
        relays={1: "Diverter Valve", 2: "DHW Recirculation Pump (K1)"},
    ),
    14: PelTec2Scheme(
        "14. BUF + K1 mixing + K2 DHW (diverter valve)", buffer="CAS", dhw="diverter", recirculation=True,
        relays={1: "Diverter Valve", 2: "K1 Circuit Pump", 3: "DHW Recirculation Pump (K2)"},
    ),
    15: PelTec2Scheme(
        "15. BUF + K1 direct + K2 DHW (diverter valve)", buffer="CAS", dhw="diverter", recirculation=True,
        relays={1: "Diverter Valve", 2: "K1 Circuit Pump", 3: "DHW Recirculation Pump (K2)"},
    ),
    16: PelTec2Scheme(
        "16. BUF + K1 DHW + K2 DHW (diverter valve)", buffer="CAS", dhw="diverter", recirculation=True,
        relays={
            1: "Diverter Valve",
            2: "DHW Pump (K2)",
            3: "DHW Recirculation Pump (K1)",
            4: "DHW Recirculation Pump (K2)",
        },
    ),
    17: PelTec2Scheme(
        "17. CRO + BUF + K1 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "Buffer Tank Pump", 2: "DHW Pump (K1)", 3: "DHW Recirculation Pump (K1)"},
    ),
    18: PelTec2Scheme(
        "18. CRO + BUF + K1 mixing + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "Buffer Tank Pump", 2: "DHW Pump (K2)", 3: "K1 Circuit Pump", 4: "DHW Recirculation Pump (K2)"},
    ),
    19: PelTec2Scheme(
        "19. CRO + BUF + K1 direct + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "Buffer Tank Pump", 2: "DHW Pump (K2)", 3: "K1 Circuit Pump", 4: "DHW Recirculation Pump (K2)"},
    ),
    20: PelTec2Scheme(
        "20. CRO + BUF + K1 DHW + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "Buffer Tank Pump", 2: "DHW Pump (K1)", 3: "DHW Pump (K2)", 4: "DHW Recirculation Pump (K1)"},
    ),
    21: PelTec2Scheme(
        "21. CRO + BUF + K1 mixing", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump"},
    ),
    22: PelTec2Scheme(
        "22. CRO + BUF with DHW + K1 mixing", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "DHW Recirculation Pump"},
    ),
    23: PelTec2Scheme(
        "23. CRO + BUF + K1 mixing + K2 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "K2 Circuit Pump"},
    ),
    24: PelTec2Scheme(
        "24. CRO + BUF with DHW + K1 mixing + K2 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "K2 Circuit Pump", 4: "DHW Recirculation Pump"},
    ),
    25: PelTec2Scheme(
        "25. CRO + BUF + K1 mixing + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "DHW Pump (K2)", 4: "DHW Recirculation Pump (K2)"},
    ),
    26: PelTec2Scheme(
        "26. CRO + BUF + K1 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump"},
    ),
    27: PelTec2Scheme(
        "27. CRO + BUF with DHW + K1 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "DHW Recirculation Pump"},
    ),
    28: PelTec2Scheme(
        "28. CRO + BUF + K1 mixing + K2 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K2 Circuit Pump", 2: "Buffer Tank Pump", 3: "K1 Circuit Pump"},
    ),
    29: PelTec2Scheme(
        "29. CRO + BUF with DHW + K1 mixing + K2 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K2 Circuit Pump", 2: "Buffer Tank Pump", 3: "K1 Circuit Pump", 4: "DHW Recirculation Pump"},
    ),
    30: PelTec2Scheme(
        "30. CRO + BUF + K1 direct + K2 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "K2 Circuit Pump"},
    ),
    31: PelTec2Scheme(
        "31. CRO + BUF with DHW + K1 direct + K2 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "K2 Circuit Pump", 4: "DHW Recirculation Pump"},
    ),
    32: PelTec2Scheme(
        "32. CRO + BUF + K1 direct + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "Buffer Tank Pump", 3: "DHW Pump (K2)", 4: "DHW Recirculation Pump (K2)"},
    ),
    33: PelTec2Scheme(
        "33. BUF + K1 mixing", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump"},
    ),
    34: PelTec2Scheme(
        "34. BUF with DHW + K1 mixing", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Recirculation Pump"},
    ),
    35: PelTec2Scheme(
        "35. BUF + K1 mixing + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Pump (K2)", 3: "DHW Recirculation Pump (K2)"},
    ),
    36: PelTec2Scheme(
        "36. BUF + K1 mixing + K2 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump"},
    ),
    37: PelTec2Scheme(
        "37. BUF with DHW + K1 mixing + K2 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump", 3: "DHW Recirculation Pump"},
    ),
    38: PelTec2Scheme(
        "38. BUF + K1 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump"},
    ),
    39: PelTec2Scheme(
        "39. BUF with DHW + K1 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Recirculation Pump"},
    ),
    40: PelTec2Scheme(
        "40. BUF + K1 direct + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "DHW Pump (K2)", 3: "DHW Recirculation Pump (K2)"},
    ),
    41: PelTec2Scheme(
        "41. BUF + K1 direct + K2 direct", buffer="CAS", dhw=None, recirculation=False,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump"},
    ),
    42: PelTec2Scheme(
        "42. BUF with DHW + K1 direct + K2 direct", buffer="CAS-B", dhw=None, recirculation=True,
        relays={1: "K1 Circuit Pump", 2: "K2 Circuit Pump", 3: "DHW Recirculation Pump"},
    ),
    43: PelTec2Scheme(
        "43. BUF + K1 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={1: "DHW Pump (K1)", 2: "DHW Recirculation Pump (K1)"},
    ),
    44: PelTec2Scheme(
        "44. BUF + K1 DHW + K2 DHW", buffer="CAS", dhw="pump", recirculation=True,
        relays={
            1: "DHW Pump (K1)",
            2: "DHW Pump (K2)",
            3: "DHW Recirculation Pump (K1)",
            4: "DHW Recirculation Pump (K2)",
        },
    ),
    45: PelTec2Scheme(
        "45. CRO (CM2K circuits only)", buffer=None, dhw=None, recirculation=False,
        relays={},
    ),
}

# Zero-based B_KONF values, derived from the table above.
BUFFER_CONFIGURATIONS = frozenset(number - 1 for number, scheme in PELTEC2_SCHEMES.items() if scheme.buffer)
# Any DHW tank, separate or integrated in a CAS-B buffer.
DHW_CONFIGURATIONS = frozenset(
    number - 1 for number, scheme in PELTEC2_SCHEMES.items() if scheme.dhw or scheme.buffer == "CAS-B"
)
# DHW priority stops the heating-circuit pumps while the DHW tank loads, so it
# only means something where the tank has its own pump or a diverter valve.
DHW_PRIORITY_CONFIGURATIONS = frozenset(
    number - 1 for number, scheme in PELTEC2_SCHEMES.items() if scheme.dhw in {"pump", "diverter"}
)
DHW_RECIRCULATION_CONFIGURATIONS = frozenset(
    number - 1 for number, scheme in PELTEC2_SCHEMES.items() if scheme.recirculation
)


def _as_int(value: Any, *, base: int = 10) -> int | None:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            return None
        return int(text, base)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return None


def parse_portal_hex(value: Any) -> int | None:
    """Decode values handled by the portal's ``parseInt(value, 16)`` filters."""
    if isinstance(value, int):
        # The server normally sends these as strings.  Preserve the portal's
        # semantics by treating an integer's decimal digits as a hex string.
        return _as_int(str(value), base=16)
    return _as_int(value, base=16)


def format_portal_hex(value: Any) -> str:
    parsed = parse_portal_hex(value)
    if parsed is None:
        return str(value)
    return f"0x{parsed:X}"


def portal_hex_bit_is_set(value: Any, bit: int) -> bool | None:
    parsed = parse_portal_hex(value)
    if parsed is None:
        return None
    return bool((parsed >> bit) & 1)


def decode_input_bitmask(value: Any) -> dict[str, Any]:
    parsed = parse_portal_hex(value)
    if parsed is None:
        return {
            "raw_hex": str(value),
            "decimal": None,
            "binary": None,
            "external_start": None,
        }
    return {
        "raw_hex": f"0x{parsed:X}",
        "decimal": parsed,
        "binary": f"{parsed:08b}",
        # Portal template uses zero-based bit 6.
        "external_start": bool((parsed >> 6) & 1),
    }


def decode_accessory_bitmask(value: Any) -> dict[str, Any]:
    parsed = parse_portal_hex(value)
    if parsed is None:
        return {
            "raw_hex": str(value),
            "decimal": None,
            "binary": None,
            "fuel_level_percentage_enabled": None,
        }
    return {
        "raw_hex": f"0x{parsed:X}",
        "decimal": parsed,
        "binary": f"{parsed:08b}",
        # Portal template shows B_razP only when bit 3 is set.
        "fuel_level_percentage_enabled": bool((parsed >> 3) & 1),
    }


def decode_internet_access(value: Any) -> str:
    parsed = _as_int(value)
    if parsed is None:
        return str(value)
    return INTERNET_ACCESS.get(parsed, f"Unknown ({parsed})")


def decode_status_mark(value: Any) -> str:
    parsed = _as_int(value)
    if parsed is None:
        return str(value)
    return STATUS_MARKS.get(parsed, f"Unknown ({parsed})")


def decode_status_mark_details(value: Any) -> dict[str, Any]:
    """Return the documented meaning for a PelTec II status mark."""
    parsed = _as_int(value)
    if parsed is None:
        return {
            "raw_value": value,
            "code": str(value),
            "meaning": "Unknown status mark",
            "category": "Unknown",
            "temporary_shutdown": None,
            "documentation": None,
        }
    details = STATUS_MARK_DETAILS.get(parsed)
    if details is None:
        return {
            "raw_value": parsed,
            "code": f"Unknown ({parsed})",
            "meaning": "Unknown status mark",
            "category": "Unknown",
            "temporary_shutdown": None,
            "documentation": None,
        }
    return {
        "raw_value": parsed,
        "code": STATUS_MARKS[parsed],
        **details,
    }


def decode_start_transition(value: Any, boiler_state: Any = None) -> str:
    if str(boiler_state).strip() == "S7-3":
        return "Paused / standby"
    parsed = _as_int(value)
    if parsed is None:
        return str(value)
    return START_TRANSITIONS.get(parsed, f"Unknown ({parsed})")


def decode_tank_level(value: Any) -> str:
    parsed = _as_int(value)
    if parsed is None:
        return str(value)
    return TANK_LEVELS.get(parsed, f"Unknown ({parsed})")


def peltec2_scheme(value: Any) -> PelTec2Scheme | None:
    """Return the manual's description of a zero-based B_KONF value."""
    parsed = _as_int(value)
    return PELTEC2_SCHEMES.get(parsed + 1) if parsed is not None else None


def configuration_has_dhw(value: Any) -> bool:
    """Return whether the controller configuration contains a DHW tank."""
    parsed = _as_int(value)
    return parsed in DHW_CONFIGURATIONS if parsed is not None else False


def configuration_has_dhw_priority(value: Any) -> bool:
    """Return whether DHW priority means anything in this configuration."""
    parsed = _as_int(value)
    return parsed in DHW_PRIORITY_CONFIGURATIONS if parsed is not None else False


def configuration_has_dhw_recirculation(value: Any) -> bool:
    """Return whether the configuration has a DHW recirculation pump."""
    parsed = _as_int(value)
    return parsed in DHW_RECIRCULATION_CONFIGURATIONS if parsed is not None else False


def configuration_has_buffer(value: Any) -> bool:
    """Return whether the controller configuration contains a buffer tank."""
    parsed = _as_int(value)
    return parsed in BUFFER_CONFIGURATIONS if parsed is not None else False


def relay_function(value: Any, relay: int) -> str | None:
    """Return what relay P<relay> drives in this configuration, per the manual.

    ``None`` when the configuration is not in the table or does not use the
    relay at all.
    """
    scheme = peltec2_scheme(value)
    return scheme.relays.get(relay) if scheme is not None else None


def valid_temperature(parameter: str, value: Any) -> float | None:
    """Return a portal-valid PelTec II temperature, otherwise ``None``.

    The portal uses -45/145 for water, room, buffer and outside temperatures,
    while flue gas is allowed up to 300.  These are strict bounds in the
    portal templates.
    """
    numeric = _as_float(value)
    if numeric is None:
        return None
    upper = 300.0 if parameter == "B_Tdpl1" else 145.0
    if not (-45.0 < numeric < upper):
        return None
    if parameter in {"B_Tdpl1", "B_Tpov1"} and numeric == 0:
        return None
    return numeric


def valid_lambda(value: Any) -> float | None:
    """Return the numeric Lambda/O2 value supplied by the controller portal.

    Older releases passed this value through unchanged.  Do not treat 0, 25.4
    or 25.5 as Home Assistant availability sentinels: the controller may publish
    those values while combustion is inactive and later replace them with a live
    measurement.  Only missing or non-finite values are unavailable.
    """
    numeric = _as_float(value)
    if numeric is None or not isfinite(numeric):
        return None
    return numeric


def valid_signal_db(value: Any) -> float | None:
    """Return a numeric Wi-Fi signal reading, or ``None`` when not reported.

    The controller's local Software Info screen labels this value in dB and
    displays ``---dB`` when no RSSI is available.  The portal represents that
    missing reading as zero, so zero must not be exposed as a real signal.
    """
    numeric = _as_float(value)
    if numeric is None or not isfinite(numeric) or numeric == 0:
        return None
    return numeric


def valid_percentage(value: Any) -> float | None:
    """Return a 0-100 percentage, or ``None`` when the portal value is not one.

    The ``isfinite`` check is not redundant with the range check: NaN compares
    False against both bounds, so without it a NaN would be handed to Home
    Assistant as a real reading.
    """
    numeric = _as_float(value)
    if numeric is None or not isfinite(numeric) or numeric < 0 or numeric > 100:
        return None
    return numeric


def valid_nonnegative_measurement(value: Any, *, maximum: float | None = None) -> float | None:
    """Return a finite non-negative numeric measurement within an optional maximum."""
    numeric = _as_float(value)
    if numeric is None or not isfinite(numeric) or numeric < 0:
        return None
    if maximum is not None and numeric > maximum:
        return None
    return numeric
