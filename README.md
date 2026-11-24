# ZHA Watchdog

Home Assistant custom integration that provides a `zha_watchdog` sensor platform for monitoring ZHA device `last_seen` timestamps.

## Installation

Place this component in `custom_components/zha_watchdog` (for example, as a git submodule in a Home Assistant configuration repository).

## Configuration

Add the sensor platform in your Home Assistant configuration (for example in `sensors.yaml`):

```yaml
- platform: zha_watchdog
  max_delay: 190  # minutes (default: 120)
  device_delay:
    Bathroom Water Sink: 360
    Kitchen Water Sink: 360
    "00:11:22:33:44:55:66:77": 720
```

- `max_delay` (optional, default `120`): maximum allowed delay in minutes before a non-coordinator device is considered overdue.
- `device_delay` (optional): mapping of device identifier/name to a device-specific delay in minutes. Matching is attempted against IEEE, user-given name, device name, and generated display name; prefer stable identifiers (IEEE) where possible.

The existing `sensor:` platform YAML format is preserved for compatibility.

## Behavior

- **State:** `running` when no monitored devices are overdue; otherwise the name of one overdue device (sorted deterministically when multiple devices are overdue). This preserves compatibility with automations that trigger when the state leaves `running`.
- **Attributes:** refreshed on every update and include:
  - `overdue_devices`: list of all overdue device names
  - `overdue_count`: number of overdue devices
  - `last_checked`: UTC timestamp of the last evaluation
  - `device_last_seen`: mapping of device identifiers/keys to last-seen values
  - `max_delay`, `device_delay`, `checked_devices`, and `zha_available`
  - per-device last-seen entries for backward-compatible attribute access
- **Unavailable/missing data:** devices with missing or unparseable `last_seen` timestamps are skipped for overdue evaluation. If ZHA/gateway data is unavailable, the sensor reports `zha_available: false` in attributes without forcing a false overdue state.

## Reload without restart

After editing YAML configuration, reload the watchdog without restarting Home Assistant by calling the `zha_watchdog.reload` service (Developer Tools → Services). The service re-reads the `zha_watchdog` sensor platform configuration from `sensors.yaml` / `configuration.yaml` (best effort for common include layouts) and reapplies `max_delay`/`device_delay` to the running entity.

## Notes

- This integration depends on ZHA runtime data and accesses ZHA structures defensively, but behavior may still vary across Home Assistant/ZHA versions. Validate on your target environment.
- Renaming devices can affect name-based `device_delay` overrides; IEEE-based overrides are more stable.
