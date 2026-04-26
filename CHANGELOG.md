# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0.1] - 2026-04-26

### Security

- TLS handling now defaults to `auto`: the client first attempts normal
  certificate verification, then falls back to an unverified retry only if the
  Centrometal endpoint presents a certificate-chain error on that host. Set
  `CENTROMETAL_VERIFY_SSL=1` for strict verification or
  `CENTROMETAL_VERIFY_SSL=0` to skip the initial verified attempt.

### Added

- HTTP refresh now actively pulls `installation-status-all` after sending
  REFRESH/RSTAT, and fires the parameter-update callback chain. Previously the
  client only sent control commands and waited for the websocket to deliver
  the new state — if the websocket lagged or dropped a frame, Home Assistant
  kept showing stale values. Refresh is now self-sufficient.
- Entity availability now follows fresh data, not raw websocket state. Each
  entity's `available` property reads `WebBoilerClient.has_fresh_data()`,
  which is `True` when the websocket is connected *or* an HTTP refresh has
  succeeded in the last 5 minutes. Transient WS gaps no longer flap entities
  in/out of unavailable, but a long-dead integration does eventually report
  unavailable per HA's official guidance.
- Tick loop keeps HTTP refresh running while the websocket reconnect loop is
  still within tolerance (3 × `WEB_BOILER_LOGIN_RETRY_INTERVAL`). Forces a
  full relogin only when the WS has been down longer than that.
- Telemetry timestamps on `WebBoilerClient`: `last_successful_http_refresh`,
  `last_websocket_message`, `disconnected_since`. Exposed via
  `has_recent_http_refresh()` and `websocket_disconnected_for()`.
- `_response_is_success()` parser for `turn` / `turn_circuit` responses.
  Accepts `{"status": "success"|"ok"|"done"}`, `{"success": True}`,
  `{"ok": True}`, the same shapes wrapped one level under `result` / `data`,
  and bare `True`. Deliberately does not deep-walk arbitrary structures —
  a buried success marker inside an explicit error response is still
  treated as failure.
- DHW / heating circuit switch attributes now expose `PVAL`, `PMIN`, `PMAX`
  diagnostics. Lets users paste the live triplet straight into a bug
  report when HA's switch state disagrees with the WebUI.
- Power-switch value parser now recognises `"1.0"` / `"0.0"` and uses
  `int(float(...))` for stringified-float values.

### Fixed

- Power switch no longer silently reports ON for unknown values. The
  parser returns `None` on values it doesn't recognise so the caller falls
  back to a secondary parameter; the previous `return str(v) != "OFF"`
  branch caused HA to flip switches the wrong way for some firmware
  variants.
- `aiohttp.ClientSession` is now created lazily on first use instead of in
  `HttpClient.__init__`. Modern aiohttp requires a running event loop in
  `ClientSession.__init__`, so the previous code only worked when
  `HttpClient` was constructed from inside an async context. Direct
  construction (tests, scripts, future synchronous callers) no longer
  raises `RuntimeError: no running event loop`.
- Websocket subscription IDs reset on each new connection. Previously they
  grew unbounded across reconnects within a single `start()` call.
- Heartbeat loop now wakes immediately on shutdown (waits on the stop
  event with a 30 s timeout instead of a fixed `asyncio.sleep(30)`).
- Heartbeat exceptions are logged at DEBUG with `exc_info=True` instead of
  silently swallowed by `except Exception: return`.
- `WebBoilerClient.turn` and `turn_circuit` now propagate
  `HttpClientAuthError` to the orchestrator instead of swallowing it. Auth
  errors during a control command now correctly trigger the existing
  relogin path; previously they returned `False` and the session stayed
  broken until the next refresh tick.
- `HttpClient.get_installations` no longer overwrites `self.installations`
  twice in succession (`self.installations = ...; self.installations =
  self.installations["installations"]`).
- `HttpClient` instance attributes (`installations`, `configuration`,
  `widgetgrid`, `widgetgrid_list`, `installation_status_all`, `csrf_token`,
  `grid`) are now declared in `__init__` with empty defaults instead of
  springing into existence on first call.
- Bare `Exception` raises replaced with specific built-in or domain types:
  `IndexError` from `HttpHelper.getDevice`, `HttpHelperLookupError`
  (`LookupError`) from helper lookups, `DeviceLookupError` (`LookupError`)
  from `WebBoilerDeviceCollection` lookups.
- `if name not in d.keys()` replaced with `if name not in d` throughout.

### Changed

- Dropped the `lxml` runtime dependency. The two pieces of HTML parsing
  the client actually needs (CSRF token extraction, post-login loading-div
  detection) are now done with the standard library `html.parser`.
  Removes a heavy C-extension and the install friction it caused on
  ARM-based Home Assistant hosts.
- Type hints applied uniformly across `HttpClient`, `HttpHelper`,
  `WebBoilerDeviceCollection`. Previously incorrect annotations corrected
  (e.g. `refresh_device(...) -> None` actually returned a dict).
- `TypedDict` schemas (`WebBoilerDeviceFields`, `WebBoilerParameterFields`)
  added to document the device / parameter dict shape for static analysis
  and IDE autocomplete. Runtime dict semantics unchanged so the
  sensor and switch consumers continue to work without edits.

### Tests

- Added 31 new unit tests across five files covering the previously
  untested critical paths: STOMP frame extraction, JSON salvage logic,
  HTML parser replacements, the new command-response success parser, and
  the entity-availability signal. **34 tests total, all passing.**

## [0.1.0.0] - 2026-04-26

- DHW switch fix.
