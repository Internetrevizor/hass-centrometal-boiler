# PelTec II entity policy and parameter reference

Version 0.2.0.11 was checked against an authenticated Centrometal portal capture containing the status payload, portal templates, parameter definitions, controls, error history, and live WebSocket traffic. Version 0.2.0.21 was checked against the two Centrometal manuals for this boiler: *Technical instructions PelTec II Lambda* (boiler book, hydraulic schemes) and *Technical instructions Controller PelTec II Lambda* (controller book, operation stages).

## Entity policy

PelTec II uses a strict allowlist:

1. Create an entity only when the portal meaning and conversion are confirmed.
2. Use internal helper values only to decode a confirmed entity.
3. Do not create raw fallback entities for unknown controller fields.
4. Do not create weather, schedule, or notification entities.
5. Discard schedule values and weather groups during ingestion.

Examples of internal-only values include `B_addConf`, `B_Inp1`, and `B_cm2k`. `B_addConf` controls whether pellet percentage is meaningful, and bit 6 of `B_Inp1` is exposed as the decoded External Start Input binary sensor. The raw values themselves are not entities.

## Confirmed values

| Parameter | Home Assistant meaning | Rule |
|---|---|---|
| `B_SUP_TYPE` | Internet Access | `1` Supervision, `2` Supervision + control |
| `B_signal` | WiFi Signal | dB when reported; portal `0` maps to `---dB`; diagnostic sensor without long-term statistics |
| `B_specG` | Status Mark | `0` None, `1` R, `2` B, `3` T, `4` G, `5` F; descriptive shutdown attributes included |
| `B_start` | Burner Command | `0` Stopped, `1` Running, `2` Stopping, `3` Cleaning; `B_STATE=S7-3` is `Paused / standby` |
| `B_STATE` | Boiler State | operation stage text, see [Boiler State](#boiler-state) |
| `B_Oxy1` | Lambda Probe | entity is always created; every finite numeric portal value is displayed, including idle values such as `25.5` |
| `B_razina` | Fuel Level State | `0` Empty, `1` Reserve, `2` Full |
| `B_FotV` | Photocell Resistance | kΩ; `1001` represents the controller display `>1000 kΩ` |
| `B_misP` | 4-Way Mixing Valve Position | `0–100%` |
| `B_puz` | Feeder Screw | Off/On |
| `B_tur` | Turbulator Cleaner | Off/On |
| `B_resInd` + `B_resDir` + `B_resMax` | Burner Grate Position | signed position state with direction and semantic attributes |
| `B_razP` | Pellet Level | `0–100%`; created only when `B_addConf` bit 3 is set |
| `B_Tk1` | Boiler Temperature | portal-valid temperature |
| `B_Tkm1` | DHW Tank Temperature | portal-valid temperature |
| `B_Tak1_1` | Buffer Tank Temperature (Upper) | portal-valid temperature |
| `B_Tak2_1` | Buffer Tank Temperature (Lower) | portal-valid temperature |
| `B_Tdpl1` | Flue Gas Temperature | `-45 < value < 300`, excluding zero |
| `B_Tpov1` | Boiler Return Temperature | `-45 < value < 145`, excluding zero |
| `B_Ths1` | Hydraulic Crossover Temperature | invalid/sentinel values are unavailable |
| `B_Tva1` | Outside Temperature | `-45 < value < 145` |
| `K1B_Tpol1` | K1 Circuit Flow Measured Temperature | `-45 < value < 145` |
| `K1B_Tsob1` | K1 Circuit Room Measured Temperature | invalid/sentinel values are unavailable |
| `K1B_Tpol` | K1 Circuit Flow Target Temperature | setpoint; no measurement state class |
| `K1B_Tsob` | K1 Circuit Room Target Temperature | setpoint; no measurement state class |
| `K1B_onOff` | K1 Circuit Heating Circuit Enabled | Off/On |
| `K1B_zahP` | K1 Circuit Pump Demand | Off/On request, separate from actual pump state |
| `K1B_CircType`, `K1B_dayNight`, `K1B_kor`, `K1B_korN`, `K1B_korType`, `K1B_Prec`, `K1B_misC`, `K1B_misO` | K1 Circuit Heating Type, Day Night Mode, Room Target Correction, Night Correction, Correction Type, Recirculation, Valve Closing, Valve Opening | as on the portal's K1 circuit page |
| `B_Ppwm` | PWM Pump | Off/On |
| `B_fan01` | Boiler Fan | Off/On |
| `B_P1`…`B_P4` | P1…P4, named after what the relay drives | Off/On; see [Pump relays](#pump-relays) |
| `B_gri` | Electric Heater | Off/On |
| `B_zahPpwm` | PWM Pump Demand | Off/On demand signal, separate from pump state |
| `B_VAC_TUR` | Vacuum Turbine | Off/On |
| `B_fireS` | Flame State | Off/On |
| `K1B_P` | K1 Circuit Pump, or DHW Pump (K1) where K1 loads the DHW tank | Off/On |
| `B_PTV_PRI` | DHW Priority | Off/On; created only where the DHW tank has its own pump or a diverter valve |
| `B_bup` | Buffer Tank Heat Request | Off/On; created only in buffer configurations (11–44) |
| `B_REC` | DHW Recirculation Enabled | Off/On; created only in configurations with a DHW recirculation pump |
| `B_REO` | DHW Recirculation Pump | Off/On; created only in configurations with a DHW recirculation pump |
| `B_doz` | Pellet Feed | Off/On |
| `B_pres` | Safety Pressure Switch | Off/On; `On` is the healthy state, an open boiler door forces it off and raises E12 |
| `PVAL_582_0` | Pump Anti-Blocking Interval | hours of inactivity after which the pump is run briefly |
| `B_FILE` | Active File | controller file string |
| `B_KONF` | Configuration | zero-based; `42` is the portal's scheme `43. BUF + K1 DHW`. Attributes list the buffer, the DHW tank and what P1…P4 drive |

`CNT_0` is Boiler Work + Standby Time and `CNT_15` is Boiler Work Time. Both are cumulative minute counters; the remaining counter mappings are unchanged.

Editable controller settings (`PVAL_*` rows the account may change) are `number` entities, bounded by the controller's own `PMIN`/`PMAX`; read-only rows stay sensors. Fan speed (`B_fan`, `B_fanB`, `B_fanO`, `B_rpm`) is not exposed: the controller does not publish it to the portal, so the entity could only show a frozen zero.

## Other families

Older PelTec, Compact, CM Pelet-set, BioTec and BioTec Plus keep the mappings inherited from the original project (untested by the maintainer). A BioTec-Plus additionally gets:

| Parameter | Home Assistant entity | Rule |
|---|---|---|
| `B_razina` | Tank Level | `0` Empty, `1` Reserve, `2` Full; unavailable until first reported |
| `B_razP` | Fuel Level | `0–100%`; unavailable until first reported or when outside the range |
| — | Pellet Mode (button) | sends `SCCMD = 1`: wood to pellets; there is no command back to wood |

## Entity names

Names are `<product> <entity>` ("PelTec II Lambda Boiler Temperature"). With **Prefix entity names with the product name** switched off in the options they are `<entity>` alone. The optional entity-name prefix from setup and, on accounts with several boilers, the serial number still come first. Entity IDs do not change with either setting.

## Hydraulic configuration

`B_KONF` selects one of the 45 PelTec II schemes in chapter 4.2.2 of the boiler book; the portal and the controller screen show the same number plus one. The scheme decides which optional entities exist:

| Entity | Schemes |
|---|---|
| Buffer Tank Heat Request (`B_bup`) | 11–44 |
| DHW Priority (`B_PTV_PRI`) | 2, 5, 6, 9, 10, 13–20, 25, 32, 35, 40, 43, 44 — the list in the controller book's "DHW priority" section |
| DHW Recirculation Enabled / Pump (`B_REC`, `B_REO`) | every scheme with a DHW recirculation pump |

A `B_KONF` outside the 45 schemes keeps none of the three and shows the portal number as its state.

## Pump relays

What P1…P4 drive depends on the scheme, and each relay entity is named after it — on scheme 43, P1 is the DHW pump on K1 and P2 the DHW recirculation pump. A relay the scheme does not use keeps its plain `Pn Pump` name with a `Function: Not used in this configuration` attribute.

Where P1 is the K1 circuit's own pump, `K1B_P` already reports the same pump, so no separate P1 entity is created. On scheme 43 a capture showed `B_P1` and `K1B_P` switching in the same millisecond on all seven cycles.

## Boiler State

`B_STATE` texts follow the stage table in the controller book (pages 96–97). Automations that compare the state text need these exact strings; the `Raw stage code` attribute holds the bare code (`S4`, `D6`, …).

| Code | State text |
|---|---|
| `OFF` | OFF: Switched off |
| `S0` | S0: Initial fan blowing, waiting for grate initial position |
| `S1` | S1: Not in use |
| `S2` | S2: Initial pellet filling |
| `S3` | S3: Waiting for flame |
| `S3-1` | S3-1: Extended ignition / flame verification |
| `S3-2` | S3-2: Additional ignition fuel charge |
| `S4` | S4: Electric heater working after flame appears |
| `S5` | S5: Flame developing |
| `SP1`…`SP5` | SP1: Stabilising 1 … SP5: Stabilising 5 |
| `S6` | S6: Additional flame development |
| `D0`…`D6` | D0: Power D0 (min) … D6: Power D6 (max) |
| `S7` | S7: Shutdown stage |
| `S7-1` | S7-1: Shutdown 1, waiting for flame to disappear |
| `S7-2` | S7-2: Shutdown 2, fan at maximum speed |
| `S7-3` | S7-3: Standby, waiting for start request |
| `PF0` | PF0: Power failure — electric heater on, waiting for flame |
| `PF1` | PF1: Power failure — flame appeared, electric heater off |
| `PF2` | PF2: Power failure — flame developing |
| `PF3` | PF3: Power failure — waiting for flame to disappear |
| `PF4` | PF4: Power failure — final fan blowing |
| `C0` | C0: Grate cleaning |

## Data intentionally not exposed

- Schedule selectors and table values (`PVAL`, `PDEF`, `PMIN`, and `PMAX` for database indexes 223–226)
- Portal weather forecast data
- Raw protocol/timing fields such as `PING`, `B_Time`, `CMD_TIME`, `SE00`, `SE01`, `SE02`, and `wf_req`
- Raw encoded event markers (`IW1-1`, `IW1-2`); decoded event history is used instead
- Unknown or unverified controller telemetry such as the `B_Sts*`, `B_puz*`, and similar fields visible in raw diagnostics
- Duplicate metadata already represented by the Home Assistant device

These values may still exist in the server response, but they do not become stored PelTec II parameters or Home Assistant entities where an ingestion filter applies.
