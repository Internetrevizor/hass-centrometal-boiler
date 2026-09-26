"""Parameter filters shared by HTTP and WebSocket ingestion."""

from __future__ import annotations


_PELTEC2_SCHEDULE_DBINDEXES = {"223", "224", "225", "226"}

# Transport fields the portal mixes into the realtime frames alongside real
# telemetry. They describe the message, not the boiler, and two of them are
# credentials: _token is a portal session token and _sign the request
# signature. Cached as parameters they ended up in the diagnostics download
# users attach to public issue reports, so they are dropped on ingestion
# rather than redacted afterwards -- nothing in the integration reads them.
_SESSION_PARAMETERS = frozenset({"_token", "_sign", "_sync"})


def is_session_parameter(name: str) -> bool:
    """Return whether a field carries session/transport data, not telemetry."""
    return name in _SESSION_PARAMETERS


def is_ignored_peltec2_parameter(name: str) -> bool:
    """Return whether a PelTec II parameter is schedule-only data.

    The Centrometal status snapshot and WebSocket stream include schedule
    selector/table values even when the client never opens the timetable UI.
    The integration intentionally does not store or expose those fields.
    """
    parts = name.split("_")
    return len(parts) >= 2 and parts[0] in {"PVAL", "PDEF", "PMIN", "PMAX"} and parts[1] in _PELTEC2_SCHEDULE_DBINDEXES
