# Centrometal Boiler System integration guide (PelTec II Lambda)

Status on 25.10.2026, version **1.1.2**: an independent project that began as a fork of `9a4gl/hass-centrometal-boiler` (Tihomir Heidelberg, Apache 2.0, credited in `README.md` and `NOTICE`).

This guide and `CLAUDE.md` are internal notes: they stay in the repository, but `.gitattributes` keeps them out of every release archive, and HACS installs only `custom_components/` anyway. The owner reads and writes in Romanian; replies to the owner are in Romanian, while everything in the repository is in English.

## 1. What it is

A Home Assistant integration (custom component, installed through HACS) for Centrometal boilers connected to the cloud portal through a CM WiFi-Box. It reads data over HTTP (polling) and WebSocket (STOMP, realtime) and sends commands (boiler on/off, circuits, editable settings).

- Domain: `centrometal_boiler`
- Code: `custom_components/centrometal_boiler/`
- Supported families: PelTec II (`peltec2`), PelTec (`peltec`), Compact, CM Pelet-set, BioTec, BioTec Plus. The details below are for **PelTec II**.

## 2. The owner's installation

| | |
|---|---|
| Boiler | PelTec II Lambda, controller firmware `v3.03dL` |
| Hydraulic scheme | **43** (`B_KONF` = 42): "CAS" buffer (upper/lower sensors) + circuit **K1 = DHW** |
| P1 | the **DHW pump** of circuit K1, the same pump as `K1B_P` (entity "DHW Pump (K1)"). `B_P1` has no entity of its own: in a capture, `B_P1` and `K1B_P` switched in the same millisecond on all seven cycles. |
| P2 | the **DHW recirculation pump** (K1), entity "P2 DHW Recirculation Pump (K1)" |
| P3, P4 | not used in scheme 43 (attribute `Function: Not used in this configuration`) |
| 4-way mixing valve | on the boiler circuit, automatic (`B_misP`, "4-Way Mixing Valve Position") |
| DHW sensor | not installed (the portal shows "-°C") |

Source for scheme 43: boiler manual, page 57.

## 3. Installing and updating

1. HACS → the Centrometal integration → ⋮ → **Update information** → install the new version (or manually, from the release archive).
2. Restart Home Assistant.
3. The first start after an update removes entities the integration no longer creates. The cleanup is skipped when the portal data looks incomplete.

Entity IDs do not change between versions (they follow the `unique_id`, `<serial>-<parameter>`). Some entities only change their displayed name.

## 4. Boiler State (`B_STATE`)

The texts follow the "Operation stages" table in the controller manual (pages 96–97). Automations that compare the text need the exact strings. The `Raw stage code` attribute holds the bare code (`S4`, `D6`, …) and is the safer choice for automations.

| Code | Text in Home Assistant | Changed in 0.2.0.21 |
|---|---|---|
| OFF | OFF: Switched off | |
| S0 | S0: Initial fan blowing, waiting for grate initial position | yes (was "Fan blowing / grate check") |
| S1 | S1: Not in use | yes (was "Not used") |
| S2 | S2: Initial pellet filling | |
| S3 | S3: Waiting for flame | |
| S3-1 | S3-1: Extended ignition / flame verification | |
| S3-2 | S3-2: Additional ignition fuel charge | |
| S4 | S4: Electric heater working after flame appears | yes (was "Electric heater igniting", which was wrong) |
| S5 | S5: Flame developing | |
| SP1…SP5 | SP1: Stabilising 1 … SP5: Stabilising 5 (the manual has only SP1–SP3) | |
| S6 | S6: Additional flame development | |
| D0…D6 | D0: Power D0 (min) … D6: Power D6 (max) | |
| S7 | S7: Shutdown stage | |
| S7-1 | S7-1: Shutdown 1, waiting for flame to disappear | yes (was "Shutting down") |
| S7-2 | S7-2: Shutdown 2, fan at maximum speed | yes (was "Final fan blowing") |
| S7-3 | S7-3: Standby, waiting for start request | yes (was "Standby") |
| PF0 | PF0: Power failure — electric heater on, waiting for flame | yes (was "heater starting") |
| PF1 | PF1: Power failure — flame appeared, electric heater off | yes (was "heater off") |
| PF2 | PF2: Power failure — flame developing | |
| PF3 | PF3: Power failure — waiting for flame to disappear | yes (was "waiting for flame off") |
| PF4 | PF4: Power failure — final fan blowing | yes (was "final blowing") |
| C0 | C0: Grate cleaning | |

`tests/test_operation_stage_labels.py` pins the full list, so none of them can change by accident.

Other PelTec II decoding:
- `B_start` ("Burner Command"): 0 Stopped, 1 Running, 2 Stopping, 3 Cleaning. With `B_STATE` = S7-3 it shows "Paused / standby".
- `B_specG` ("Status Mark"): 0 None, 1 R (flame lost), 2 B (pellet tube bimetal), 3 T (turbulators), 4 G (grate cleaning), 5 F.

## 5. PelTec II hydraulic schemes

`B_KONF` is the scheme number minus one (the portal and the controller screen show the real number). The full table of the 45 schemes is in `custom_components/centrometal_boiler/peltec2.py` (`PELTEC2_SCHEMES`), transcribed from the boiler manual, chapter 4.2.2 (pages 23–58). It is cross-checked against the controller manual: the "DHW priority" list (page 52) and the "Installation" table (page 54).

What the scheme decides:

| Entity | Created in schemes |
|---|---|
| Buffer Tank Heat Request (`B_bup`) | 11–44 |
| DHW Priority (`B_PTV_PRI`) | 2, 5, 6, 9, 10, 13–20, 25, 32, 35, 40, 43, 44 |
| DHW Recirculation Enabled / Pump (`B_REC`, `B_REO`) | every scheme with a DHW recirculation pump |

What relay P1 drives, according to the manual:

| P1's role | Schemes |
|---|---|
| K1 circuit pump (radiators / underfloor) | 1–4, 6, 7, 21–27, 30–42 |
| DHW pump on K1 | 9, 10, 43, 44 |
| 3-way diverter valve; the boiler pump P(PWM) moves the water | 13–16 |
| Buffer tank pump | 17–20 |
| K2 circuit pump | 28, 29 |
| DHW recirculation pump | 8, 12 |
| Shared K1 / DHW pump; the 3-way valve is on P2 | 5 |
| Not used | 11, 45 |

Relays P1–P4 are named after their role in the active scheme (for example "P2 DHW Recirculation Pump (K1)") and carry a `Function` attribute. Where P1 is the K1 circuit's own pump, no separate P1 entity is created (`K1B_P` already reports it). Where K1/K2 loads the DHW tank with its own pump, the circuit pump is named "DHW Pump (K1)" / "DHW Pump (K2)". A scheme the manual does not list (`B_KONF` ≥ 45) behaves as before.

The **Configuration** entity shows the scheme (for example `43. BUF + K1 DHW`) with the attributes Buffer tank, DHW tank, DHW recirculation and P1…P4.

The other parameters (temperatures, counters, K1 circuit, editable settings) are described in `PARAMETERS.md`.

## 5b. Community features (since 1.1.0)

Taken from the other forks of the original integration (see `NOTICE`):
- **BioTec-Plus:** "Tank Level" (`B_razina`) and "Fuel Level" (`B_razP`, %), unavailable until the controller first reports them. The **"Pellet Mode"** button sends `SCCMD = 1` (wood to pellets; there is no command back). Taken from AndroFlo; not tested here on a real boiler.
- **Option "Prefix entity names with the product name"** in *Configure*: on by default; off drops "PelTec II Lambda" from the front of the names. Entity IDs do not change.
- **Translations** of the setup screens: English, French, Romanian. Entity names stay in English.

Forks reviewed (22.10.2026): 9a4gl (the original, no changes since 03.2026), AndroFlo (active, BioTec-Plus only, its own external library), grigoras-cristinel (the base of our 0.1.0.0), TheCarpetMerchant / mgcd-jed (Compact, prefix option), ULazdins (pellet percentage), ravloony (no changes of its own). Not taken: the wood-fire relight prediction (AndroFlo, beta), the controller clock and the schedule tables.

## 6. Reference manuals

Both are published by Centrometal (centrometal.hr → downloads), in English. They are not in the repository: the repository is public and the manuals are the manufacturer's material.

**"Technical instructions Controller PelTec II Lambda"** (file `PelTec-II-Lambda-12-48-regulation-ENG.pdf`, 100 pages):
- p. 52: DHW priority (the schemes with a DHW tank);
- p. 54: Installation (which schemes have a buffer and which circuits);
- pp. 55–58: Manual test (P(PWM), P1–P4, valves);
- pp. 81–86: errors and warnings (E12 safety pressure switch, E18 no flame in the ignition stage, E19, E23, E24, W2, I1–I19);
- pp. 96–97: Operation stages (the S0…C0 and PF0–PF4 table);
- pp. 97–98: the R, T, G and B marks.

**"Technical instructions PelTec II Lambda"** (file `PelTec-II-Lambda-12-48-boiler-ENG.pdf`, 96 pages):
- chapter 4.2.2, pp. 23–58: the 45 configurations, with the pump and sensor legends;
- p. 57: configuration 43 (the owner's installation).

## 7. Publishing a version

The owner's rule (since 23.10.2026): **approved** changes go straight to `main`, without a pull request. Work happens on the `claude/git-release-commit-f8oo83` branch; the checks are run, the branch is pushed, then `main` is fast-forwarded to it (`git push origin HEAD:main`). A pull request only when the owner asks for one.

**Releases are automatic** (`.github/workflows/release.yml`):
1. A new version changes `custom_components/centrometal_boiler/manifest.json` (`version`), the badge and heading in `README.md`, `tests/test_repository_layout.py` (the expected version) and adds a `## X.Y.Z — ...` section to `CHANGELOG.md`.
2. On a push to `main`, the workflow sees that `vX.Y.Z` does not exist yet, runs Validate, Hassfest and HACS, then creates the tag and the release with the notes from that CHANGELOG section. Without a CHANGELOG section there is no release.
3. A push to `main` without a version change creates nothing.
4. A version with a suffix (for example `1.2.0b1`) is published as a pre-release.
5. In Home Assistant: HACS → Update information → install → restart (or manually, from the release archive).

Claude sessions cannot create releases or tags themselves (GitHub refuses them for this session type); the workflow creates them with the repository's own token.

History:
- **0.2.0.11**: old release from `main`.
- **0.2.0.20**: imported from a zip, pull request #1 merged into `main`, release published on 26.09.2026.
- **0.2.0.21**: on the branch only, never released on its own; part of 1.0.0.
- **1.0.0**: independent release (credits, `NOTICE`, internal files kept out of releases), no entity changes compared with 0.2.0.21. Merged into `main` through pull request #2.
- **1.1.0**: features from the other forks (BioTec-Plus, prefix option, fr/ro translations, `tests_ha/`), the `websockets` fix, the HACS documentation. Pull request #3, released by hand on 22.10.2026; re-published by the release workflow on 24.10.2026 after the history rewrite (section 11).
- **1.1.1** (25.10.2026): editable settings the portal reports late fill in without a restart (section 9, item 7). First version committed straight to `main` and released by the workflow. Its CHANGELOG section also records the automatic releases and the history rewrite.
- **1.1.2** (25.10.2026): editable settings keep their last value across a restart (restore-state store, `Restored: true` attribute) until the portal reports them; the owner chose this over capturing the portal's read request (section 9, item 7).

## 8. Development and tests

- The tests need Home Assistant installed. Without it, ten test modules cannot be imported and are silently skipped.
- Locally: Python 3.13 + `pip install homeassistant aiohttp pytest pytest-asyncio ruff "websockets>=13.1" "certifi>=2024.7.4" voluptuous`, then `ruff check .` and `pytest`.
- **Tests in a real Home Assistant** (`tests_ha/`): the integration runs in Home Assistant (pytest-homeassistant-custom-component) against a fake Centrometal cloud (`tests_ha/fake_centrometal.py`: website + STOMP broker; it can push realtime values and simulate an outage or an expired session). In a separate environment: `pip install -r tests_ha/requirements.txt`, then `pytest -c tests_ha/pytest.ini tests_ha`.
- CI (`.github/workflows/validate.yml`): the `python` job (Python 3.14, unit tests) and the `home-assistant` job (Python 3.13, `tests_ha/`).
- Fixtures: `tests/fixtures/peltec2_lambda_real_snapshot.json` and `..._http_snapshot.json` (both with `B_KONF` 12, i.e. scheme 13). Their origin is unclear: the owner does not recognise them, and the owner's installation is on scheme 43.

## 9. Open items

1. **`B_REO` ("DHW Recirculation Pump") versus P2**: on a PelTec II the recirculation pump is always wired to a P relay (the manual puts it on one of P1–P4 in every scheme that has one), so `B_REO` probably duplicates "P2 DHW Recirculation Pump (K1)". The owner leaned towards "only the `B_P` pumps, not `B_RE`". The change was drafted (drop `B_REO` from the PelTec II table; the older PelTec keeps it; `B_REC` stays) and then stopped: **not applied, to be discussed**.
2. Check 1.1.0 on the real Home Assistant: the pump names, the Configuration entity, a full burn S0 → D → S7.
3. Update the automations that compare the old stage texts (the table in section 4).
4. The fixtures with `B_KONF` 12, of unclear origin.
5. Inclusion in the HACS default list (section 10): to be submitted by the owner.
6. Ask GitHub Support to purge the old commits still reachable through pull requests #1–#3 (section 11).
7. **Settings 71, 291 and 292 after a restart.** The owner's diagnostics of 25.10.2026: for sixteen hours after the Home Assistant restart of 24.10 the portal's status snapshot carried settings 576, 67, 68 and 70 but nothing for 71, 291 and 292, although parameter-list listed all seven rows (291 and 292 with `ask: funcParametersPeltec2`). The owner confirmed they appear once the settings page is opened on the portal website. 1.1.1 fills them in whenever they arrive; before it, the entities stayed unavailable until the next restart. 1.1.2 keeps the last known values across restarts, marked `Restored: true`, so the page no longer has to be opened after each restart (only once after installing 1.1.2, if the portal does not report them at that first start). Not done, by the owner's choice: having the integration ask for them itself, which would need the request the portal page sends (browser DevTools → Network, the payload without cookies); neither the original client library nor the AndroFlo one has a confirmed request for it (both carry an unused `PRD … VAL/ALV` table read).

## 10. Inclusion in the HACS default list

The list is the `hacs/default` repository; the owner submits the request from their own account (the "owner" check requires the pull request author to own the repository).

Status on 22.10.2026:
- The technical requirements are met: public repository, description and topics, issues enabled, HACS action without `ignore`, Hassfest, a published release. No separate PyPI library is required (that rule applies only to Home Assistant core integrations).
- **The original `9a4gl/hass-centrometal-boiler` is already listed, with the same `centrometal_boiler` domain.** The automatic HACS checks do not block this (they only check for a conflict with Home Assistant core integrations); the reviewers decide. Say so openly in the request.

Steps:
1. A new release published **after** the HACS and Hassfest actions passed on that commit.
2. Fork `https://github.com/hacs/default` and create a new branch from `master`.
3. In the `integration` file, add `"Internetrevizor/hass-centrometal-boiler",` in alphabetical order (case-insensitive): between `"intelliThings-official/home-assistant-intellithings",` and `"InTheDaylight14/nginx-proxy-manager-switches",`.
4. Open a pull request to `hacs/default` with their template filled in (links to the release and to successful HACS and Hassfest runs), with "Allow edits by maintainers" on. Do not request reviews: the template says the pull request is closed if you do.

## 11. Personal data

Nothing that identifies the owner belongs in the repository: no e-mail addresses, serial numbers, portal installation ids, real locations, file names or credentials. Tests and fixtures use placeholders (`SN000001`, id `1001`, "Example City", `USR:PelTec II - Example`).

On 24.10.2026, at the owner's request:
- the code was cleaned (the fixtures' controller file name, a controller serial and the portal installation id used across the tests, an invented city in the fake cloud);
- the git history was rewritten to remove the same values from every past commit and to replace the owner's personal e-mail in commit metadata with their GitHub `noreply` address; `main` was force-pushed once for this, with the owner's explicit approval;
- the old releases and tags were deleted by the owner and v1.1.0 was recreated by the release workflow on the rewritten history.

GitHub keeps the old commits reachable through the pull-request pages (#1–#3) until GitHub Support removes them. For new commits the owner enables *Settings → Emails → Keep my email addresses private* and *Block command line pushes that expose my email*.
