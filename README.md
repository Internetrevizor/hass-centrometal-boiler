# Centrometal Boiler System for Home Assistant

![Version](https://img.shields.io/badge/version-0.2.0.20-blue.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)

A Home Assistant custom integration for Centrometal Web Boiler cloud-connected heating systems using the CM WiFi-Box.

## PelTec II behavior in 0.2.0.20

PelTec II entities are created from a strict allowlist verified against an authenticated portal HTTP and WebSocket capture. Raw, hidden, duplicated, or unverified controller fields are not created as Home Assistant entities.

Editable settings are written with the portal's own command, and Home Assistant refuses a value outside the range the controller reports for that setting. Each setting keeps the resolution the portal gives it: whole degrees for the boiler and buffer rows, tenths for the DHW rows.

The integration does not create or load schedule, weather, or notification entities. Schedule values received inside the main boiler status stream are discarded before they enter the device parameter cache. Weather groups from the parameter-list response are discarded. There is no option to enable either feature.

Exposed PelTec II data includes:

- Boiler power and operating state
- Portal-visible temperatures with invalid-value filtering
- Heating-circuit enabled state, pump demand, pump state, target temperatures, and measured temperatures
- Pump, fan, heater, flame, vacuum, fuel-level, lambda, and Wi-Fi states where the portal meaning is confirmed. Fan speed itself is not exposed: this controller does not publish it to the portal, and an entity for it could only show a frozen zero. A pump reported both by the boiler and by its heating circuit produces one entity, not two.
- Photocell resistance, fan speed, 4-way mixing-valve position, feeder-screw activity, turbulator-cleaner activity, and burner-grate position
- Descriptive attributes for temporary shutdown marks and operation-stage groups
- Working counters, including corrected total/active boiler runtime labels
- Portal temperature settings, editable from Home Assistant when the account may change them, bounded by the controller's own minimum and maximum; read-only rows keep a plain sensor. Plus the K1 circuit switch
- Controller configuration, product, software version, active file, and event history
- Cloud/WebSocket connectivity and the decoded external-start input

The Lambda Probe entity is created even when the controller omits the reading while the boiler is not firing. Any finite numeric value supplied by the controller, including idle values such as `25.5`, is displayed; a later live combustion value updates normally without reloading the integration. The Wi-Fi signal entity follows the controller display: nonzero values are shown in dB, while portal value `0` represents the unavailable `---dB` state and recovers automatically when RSSI is reported.

Older PelTec and other supported Centrometal families retain their established mappings.

## Installation

### Manual installation

1. Copy the `centrometal_boiler` folder into `config/custom_components/`.
2. Remove or replace the existing `config/custom_components/centrometal_boiler` folder first.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration** and select **Centrometal Boiler System**.

On the first restart, obsolete sensor registry entries created by earlier builds are removed automatically. The cleanup is skipped for any boiler whose parameter snapshot looks incomplete, so an outage on the Centrometal side cannot delete working entities.

### HACS custom repository

Add the repository as a custom HACS integration, install it, and restart Home Assistant.

## Configuration

Configuration is through the Home Assistant UI. Enter the Centrometal account e-mail, password, and optional entity-name prefix.

The integration options only control HTTP refresh and reconnect timing. There are no schedule or weather switches.

## "Last updated"

The `Last updated` attribute is the time the reading itself last changed, not the time of the last poll. The portal re-reports every parameter on every poll with a fresh timestamp even when the value is identical, so using that would show the same number on every entity and say nothing.

## Diagnostics

The Home Assistant diagnostics download includes the current parsed boiler data with credentials and location fields redacted, plus the connection health used to decide entity availability (websocket state, age of the last realtime message, time since the last successful HTTP refresh).

## Debug logging

```yaml
logger:
  default: info
  logs:
    custom_components.centrometal_boiler: debug
```

## TLS

HTTPS and WebSocket certificate verification is always enabled and cannot be turned off.

Under Home Assistant the integration reuses core's own shared SSL context, which is built from `certifi` (or from `REQUESTS_CA_BUNDLE` when one is configured) once per process. Outside Home Assistant the client falls back to its own `certifi`-based context, and to the interpreter's default trust store if `certifi` is not installed.

## License

Apache License 2.0. This is an independent community project and is not affiliated with Centrometal d.o.o.
