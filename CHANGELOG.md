# Changelog

## 0.2.0.20 — cleaning transition, and an end to redundant entity writes

- `B_start = 3` is decoded as `Cleaning`. Identified by the owner and corroborated by a debug capture: `B_specG` went to 4 ("shutdown because burner grate cleaning is required") in the same millisecond as `B_start = 2`, the boiler ran S7-1 → S7-2 → C0, `B_start` became 3 fifteen seconds into C0, and it returned to 1 in the same millisecond as `B_specG` returning to 0.
- A parameter whose value has not changed no longer triggers an entity state write. Replaying eight consecutive status responses from that capture: 880 entity notifications before, 238 after — 73% of them were for a reading that had not moved. The rule is applied to the realtime path too, so both behave the same.
- `Last updated` therefore now means the time the reading last changed, on every parameter. It previously showed the time of the last poll for live telemetry, because the portal bumps its own timestamp every poll regardless of the value — `B_KONF`, a configuration value that cannot change, had it advanced by exactly the poll interval eight times running. Editable settings already behaved this way and are unaffected.
- A refresh that recovers from a stale period re-renders every entity. Without this, a refresh in which nothing had changed would write no state at all and leave entities showing unavailable, since availability is time-based.
- Dropped the PelTec II "Fan Speed" entity. Across an 8.5-hour capture on v3.03dL the controller published `B_fan`, `B_fanB`, `B_fanO` and `B_rpm` in none of the status responses and in no websocket frame, so the entity sat at a frozen 0 rpm — indistinguishable from a working sensor reading zero. "Boiler Fan" (`B_fan01`) is reported reliably and covers the fan. The older PelTec family keeps its mapping.
- "P1 Pump" is no longer created when the device also reports a K1 circuit. `B_P1`, `B_Pk1_k2` and `K1B_P` changed in the same millisecond on all seven switching cycles of the capture — one pump, and "K1 Circuit Pump" already reports it. Configurations with no K1 circuit, where the manual has P1 drive a diverter valve, still get the entity.
- Added `B_doz` ("Pellet Feed", the *dozirni ventil*, observed switching on at state S2 as the ignition dose is fed) and `B_pres` ("Safety Pressure Switch", the *sigurnosni presostat* that forces OFF and raises E12 on an open boiler door). Both meanings come from the manufacturer's regulation manual for this firmware.
- Fixed the stub in `test_system_recovery.py`, which was missing the device collection and could never have passed. It had never run anywhere: CI did not install Home Assistant, so the module was silently uncollectable.
- Updated the entity-set guards for the circuit fields confirmed in 0.2.0.14 and for the two changes above.
- Editable controller settings are now editable from Home Assistant, on a new `number` platform. The portal writes them with a single command, captured from the portal itself: `POST /api/inst/control/{id}` with `{"cmd-name": "PWR 67", "cmd-value": 66}`, where 67 is the row's `dbindex`. The value is the plain reading — slot 67 holds 40..85 for 40..85 °C, so nothing is scaled.
- Resolution follows the row's own type rather than a fixed rule: boiler and buffer rows (`temperatura`) step by a whole degree, the DHW rows (`temperatura_0.1`) by a tenth. A tenth-resolution row sends the decimal itself, confirmed by capture — `{"cmd-name": "PWR 291", "cmd-value": 54.8}` sets 54.8 °C.
- Minimum and maximum come from the controller's own `PMIN`/`PMAX` slots, so Home Assistant refuses a value the controller would have rejected, and a firmware that widens a range is followed automatically.
- A settings row this account can edit now produces one entity, not two: the read-only sensor is no longer created for it, and its old registry entry is retired. Rows the portal marks read-only keep their sensor.
- Each editable setting carries its own icon rather than all seven sharing one, keyed on the controller's parameter index so it survives the portal being read in another language, with a keyword fallback for an index this build has not seen.
- The boiler and heating-circuit switches show what they drive instead of Home Assistant's generic toggle, and reflect their own state.
- Corrected `B_start`. It is the burner's commanded state, not a momentary transition: in the capture it read 1 across S0, S2, S3, S4 and SP1 *and* across D4, D5 and D6, so the old "Starting" label was shown while the boiler had been burning steadily for an hour. The values are now Stopped / Running / Stopping / Cleaning, and the entity is called "Burner Command" rather than "Start / Stop Transition". The detailed phase remains the "Operation State" entity's job. Friendly name only — the entity ID is unchanged.

## 0.2.0.19 — the heating-circuit switch no longer sits at "unknown"

- The heating-circuit switch reads the circuit's own on/off parameter when the portal omits the row's PVAL slot. Confirmed from a PelTec II Lambda debug capture: `PVAL_272_0` was absent from eight consecutive installation-status responses while `K1B_onOff` was present in all eight, so the switch reported `unknown` for the entire session and Home Assistant rendered it as two buttons rather than a toggle. The PVAL slot stays the primary source; the circuit parameter only answers while it is missing, and the `State source` attribute says which one is in use.
- The fallback parameter is looked up on every read instead of being captured when the entity is built, so one that only appears later is still picked up.
- Moved the circuit on/off decision logic into `switches/circuit_state.py`, which imports nothing from Home Assistant, so it is covered by tests that run in any environment.

## 0.2.0.18 — setup no longer fails on a constructor ordering mistake

- Fixed an AttributeError that failed setup outright: 0.2.0.17 read `self.refresh_interval` one line above the assignment that creates it.
- Added a static check that parses every `__init__` in the integration and fails when an attribute is read before it is assigned. It needs nothing but the standard library, so it runs everywhere — including where Home Assistant cannot be installed.
- CI now installs `homeassistant`. Ten tests import the integration package and were silently uncollectable, so the job reported success while the orchestration, entity and registry tests never ran. That gap is why 0.2.0.17 shipped broken.

## 0.2.0.17 — refresh cadence and availability window

- The periodic refresh now runs at the configured interval. The due check used a strict comparison against a tick that fires once a minute, so a 240 s interval actually refreshed every 300 s — landing exactly on the 300 s freshness window and leaving availability to depend on tick jitter.
- The freshness window follows the configured refresh interval instead of being fixed at 300 s. A longer interval used to guarantee that entities went unavailable between two refreshes whenever the websocket had nothing to send.
- A parameter the controller has not sent reads as `?` again, as it did before 0.2.0.12, so device names, model strings and attribute text are unchanged by the falsy-value fix.

## 0.2.0.16 — editable-setting sensors are no longer lost to a short parameter-list response

- Registry entries for the editable-setting slots (`PVAL_*`, `PDEF_*`, `PMIN_*`, `PMAX_*`) are never deleted by the obsolete-entity cleanup. These slots do not come from the status snapshot but from a separate parameter-list fetch that the portal answers with a varying number of groups; a response that omits a group is not an HTTP error, so the slot is simply absent, its sensor is not created, and the cleanup concluded the entity was obsolete. The 0.2.0.15 guard did not cover them, because it derived the protected slot list from the very metadata that was missing.
- A device that comes back with no editable-setting rows is now logged as a warning, instead of silently losing its setting sensors until the next metadata refresh.

## 0.2.0.15 — session fields out of diagnostics, entity cleanup follows the mapping

- The portal's `_token`, `_sign` and `_sync` fields are no longer stored as boiler parameters. They describe the transport, not the boiler, and two of them are credentials: a portal session token was being cached and written into the diagnostics download users attach to public issue reports. Dropped on ingestion, with a second guard in diagnostics.
- Obsolete-entity cleanup no longer deletes a registry entry for a parameter this build still maps. Observed in the field: a PelTec II Lambda reported `PVAL_582_0` in one poll and omitted it in the next, everything else unchanged — which was enough to permanently remove that entity's ID, name, area and history. Entries whose parameter is absent from the snapshot but present in the device's parameter table, circuit table or settings slots are kept; genuinely retired mappings are still removed.

## 0.2.0.14 — pump anti-blocking interval and the rest of the K1 circuit

- Added the Pump Anti-Blocking Interval sensor (portal settings slot 582, in hours). The controller reports the value but the portal returns no parameter-list row for it, so it had no label and never became an entity. Created for PelTec II only, since settings-slot numbering is controller-specific.
- The K1 circuit now exposes the remaining portal fields, confirmed against the portal's circuit page: Heating Type, Day Night Mode, Room Target Correction, Night Correction, Correction Type, Recirculation, Valve Closing and Valve Opening. `_recSrc` and `_recType` stay hidden — no confirmed meaning.

## 0.2.0.13 — hydraulic scheme numbering

- The Configuration sensor now reports the same scheme number as the portal. `B_KONF` is zero-based while the portal numbers schemes from 1, and the labelled list only covers the fifteen PelTec schemes, so any PelTec II scheme past that was displayed one below the number on the controller's own screen (42 instead of 43). Labelled configurations are unchanged; unlabelled ones now show the portal's number.
- Scheme 43 (`B_KONF` 42) is registered as having both a buffer and a DHW tank, so DHW Priority, DHW Recirculation Enabled, DHW Recirculation Pump and Buffer Tank Heat Request are created for it. They were suppressed because the configuration was outside the known table, which the gate treated as "no such hardware".
- `countryCode` is redacted from diagnostics alongside `country`.

## 0.2.0.12 — outage handling, safer entity cleanup, and dependency cleanup

- Fixed the relogin path recording success before the websocket was actually back, which reset the exponential backoff on every attempt and turned a websocket-only outage into a full relogin every 60 seconds indefinitely.
- Kept the periodic HTTP refresh running for the whole duration of a websocket outage. Previously it stopped once the reconnect task had died, so every entity went unavailable after five minutes even though the data was still reachable over HTTP.
- A websocket that cannot be reached no longer fails setup: the integration loads and serves every entity from HTTP polling while it keeps retrying in the background.
- Entity availability now also considers how long a *connected* websocket has been silent, so a socket that stays open while the broker has stopped forwarding no longer keeps stale values marked as current.
- Obsolete-entity cleanup is skipped for any device whose parameter snapshot is missing the controller's identity fields, so an incomplete portal response can no longer delete a device page's worth of entity IDs, names, areas and history. Removals are logged at INFO.
- `valid_percentage` now rejects non-finite values. NaN compares False against both bounds, so it was being published as a real percentage.
- Control commands that hit an expired session now report a clear error and rebuild the session silently, instead of surfacing an internal exception as "Unknown error" with the session left broken.
- A rejected heating-circuit command no longer triggers a full relogin, which tore down the websocket for every device on the account.
- Removed the redundant `notify_all_updated()` after a switch command; the refresh it follows already notifies every updated parameter.
- Event History keeps the last 10 events in its attributes instead of 50. The attribute payload was rewritten to the recorder on every refresh; the full list is still in diagnostics.
- The hourly parameter-list refresh now reports the parameters it updated, so Default/Minimum/Maximum attribute changes re-render instead of being silently dropped.
- Device-level log lines now carry the same `account-` identifier as the rest of the integration; they were hashing an already-hashed value.
- Debug dumps of portal payloads are built only when debug logging is on, and installation address, place, city and serial are redacted from them.
- Attribute values of `0` are no longer displayed as "None", and entity properties no longer create placeholder parameters as a side effect of being read.
- Timestamps are formatted through the time zone core already resolved at startup, removing a blocking zoneinfo load from entity properties.
- Flow and room target temperatures (`_Tpol`, `_Tsob`, `_kor`, `_korN`) are excluded from long-term statistics on every controller family, not only PelTec II. Their measured counterparts (`_Tpol1`, `_Tsob1`) are unchanged. Editable `PVAL_*` settings are deliberately left as they are, so existing statistics are not dropped.
- Capped the STOMP reassembly buffer so a stream that never sends a frame terminator cannot grow without bound.
- Dropped the `certifi` requirement from the manifest: under Home Assistant the integration now reuses core's shared SSL context, and the standalone fallback treats `certifi` as optional. Verification is still always on.
- Replaced the deprecated `asyncio.TimeoutError` alias with the builtin, unquoted deferred annotations, and moved to `collections.abc` / builtin generics, so the code keeps working as those aliases are removed.
- Config entries are keyed by a normalized (lower-cased) account address; existing entries keep their original unique ID so reauthentication is unaffected.
- Widened the ruff configuration from syntax-level rules to `F`, `B`, `UP` and `ASYNC`, which is what catches this class of issue before release.
- Added tests for outage recovery, registry cleanup, websocket staleness, the STOMP buffer cap and non-finite percentages.

## 0.2.0.11 — controller targets, requests, recirculation, and Wi-Fi RSSI correction

- Added K1 heating-circuit enabled state, pump demand, flow target temperature, and room target temperature while preserving the existing measured-temperature and pump entities.
- Kept target temperatures out of long-term measurement statistics because they are setpoints rather than measured values.
- Added DHW priority, conditional buffer-tank heat request, DHW recirculation enabled, and DHW recirculation pump states only for controller configurations containing the corresponding DHW or buffer component.
- Corrected `CNT_0` to Boiler Work + Standby Time and `CNT_15` to Boiler Work Time; both runtime values use minutes.
- Corrected Wi-Fi signal handling to match the controller display: the entity uses dB and portal value `0` is treated as the unavailable `---dB` sentinel. Nonzero readings become available automatically, without creating long-term RSSI statistics.
- Preserved all existing unique IDs and left unverified mode, safety, valve-direction, and auxiliary-output parameters hidden.

## 0.2.0.10 — restore Lambda and Wi-Fi readings

- Restored the v1-compatible Lambda behavior: finite controller values such as `0`, `25.4`, and `25.5` are displayed instead of forcing the entity unavailable.
- Restored Wi-Fi signal to the portal percentage unit and preserved `0` as a valid reading.
- Kept the Lambda placeholder entity so it still appears when the controller temporarily omits the parameter and recovers automatically when a value returns.
- Added diagnostic attributes for Lambda measurement activity, boiler state, flame detection, raw values, and portal connection context without changing entity IDs.
- Left all other 0.2.0.9 mappings and entities unchanged.

## 0.2.0.9 — documented PelTec II telemetry and resilient Lambda entity

- Added documented PelTec II operation stages `S3-1`, `S3-2`, and `S7` without changing existing stage values.
- Added operation-stage group, description, raw-code, and modulation-level attributes.
- Added descriptive attributes for `R`, `B`, `T`, `G`, and `F` temporary shutdown marks while preserving their existing entity states.
- Exposed photocell resistance, fan speed, 4-way mixing-valve position, feeder-screw activity, turbulator-cleaner activity, and burner-grate position.
- Kept the Lambda Probe entity present when the controller omits the value while not firing; it becomes available automatically when a valid reading returns.
- Corrected the PelTec II display names for rated boiler power and DHW tank temperature, and added the kW unit to rated power.
- Left uncertain safety, recirculation, auxiliary-output, and ambiguous counter mappings unchanged.

## 0.2.0.8 — final PelTec II cleanup

- Rebuilt PelTec II entity creation around a strict portal-confirmed allowlist.
- Removed raw, hidden, duplicated, and unverified PelTec II fallback entities.
- Removed weather, schedule, and notification entities and their loading paths.
- Discarded PelTec II schedule values during HTTP and WebSocket ingestion.
- Discarded portal weather groups during parameter-list parsing.
- Added automatic removal of obsolete sensor registry entries from earlier builds.
- Corrected internet-access, Wi-Fi dB, status-mark, transition-state, fuel-level, lambda, and temperature decoding.
- Decoded the external-start input from the controller bitmask without exposing the raw input value.
- Corrected pump, heater, demand, configuration, and active-file names.
- Kept invalid portal sentinel values unavailable instead of presenting them as measurements.
- Retained decoded portal error history and confirmed editable settings.
- Added portal-capture regression tests and Home Assistant runtime smoke validation.
