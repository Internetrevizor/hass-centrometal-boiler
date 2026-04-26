# Centrometal Boiler System for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://www.hacs.xyz/)
![Version](https://img.shields.io/badge/version-0.1.0.0-blue.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.11%2B-blue.svg)
![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)

A Home Assistant custom integration for Centrometal Web Boiler cloud-connected heating systems using the CM WiFi-Box or the integrated new WiFi Module.

The integration connects Home Assistant to the Centrometal Web Boiler service and exposes supported boilers as sensors, binary sensors, and switches for monitoring, dashboards, and automations.

## Features

- Setup from the Home Assistant UI
- Cloud push updates over the Centrometal Web Boiler websocket endpoint
- Multi-device support for accounts with more than one boiler
- Sensors for boiler state, temperatures, counters, configuration, firmware, heating circuits, fire grid, and device type
- Binary sensors for on/off states and cloud connection status
- Switch entities for supported boiler power and heating circuit controls
- Re-authentication flow when credentials need to be updated
- Diagnostics support with sensitive values redacted
- Clean unload/reload handling for Home Assistant restarts and integration reloads

## Supported devices

Known compatible device families include:

- PelTec and PelTec II Lambda
- CentroPlus with CM Pelet-set
- BioTec-L
- BioTec-Plus
- EKO-CK P with CM Pelet-set
- Compact

Other Centrometal devices connected through the CM WiFi-Box may also work.

## Requirements

- Home Assistant `2024.11.0` or newer
- A Centrometal boiler connected through a CM WiFi-Box or the integrated WiFi Module.
- A working Centrometal Web Boiler account
- The boiler visible in the Centrometal web or mobile application

## Installation

### HACS custom repository

1. Open **HACS** in Home Assistant.
2. Open the menu in the top-right corner.
3. Select **Custom repositories**.
4. Add this repository URL:

   ```text
   https://github.com/Internetrevizor/hass-centrometal-boiler
   ```

5. Select **Integration** as the category.
6. Install **Centrometal Boiler System**.
7. Restart Home Assistant.

### Manual installation

1. Download the latest release ZIP from GitHub.
2. Copy `custom_components/centrometal_boiler` into your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration**.
5. Search for **Centrometal Boiler System** and complete setup.

## Configuration

The integration is configured entirely from the Home Assistant UI. YAML configuration is not required.

During setup, enter:

- The e-mail address for the Centrometal Web Boiler account
- The password for the Centrometal Web Boiler account
- An optional entity name prefix

The optional prefix is useful when one Home Assistant instance contains multiple boilers or when you want the generated entity names grouped by site or heating system.

## Diagnostics and privacy

Diagnostics redact credentials and account/location fields before export. When sharing logs publicly, review them first and remove account identifiers, device serial numbers, locations, or other private information.

## Debug logging

To collect detailed logs, add this to `configuration.yaml` and restart Home Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.centrometal_boiler: debug
```

Disable debug logging after troubleshooting.

## Development

Basic local validation:

```bash
python -m compileall custom_components
python -m pip install ruff
ruff check .
```

The included GitHub Actions run Python syntax checks, Ruff critical checks, HACS validation, and Hassfest validation.

## Support

Use the GitHub issue tracker for bug reports and feature requests:

```text
https://github.com/Internetrevizor/hass-centrometal-boiler/issues
```

Include the Home Assistant version, integration version, boiler model, and relevant redacted logs.

## Disclaimer

This integration is an independent community project and is not affiliated with, endorsed by, or supported by Centrometal d.o.o.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
