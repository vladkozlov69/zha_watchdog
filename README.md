# ZHA Watchdog

Home Assistant custom component that provides a `zha_watchdog` sensor platform for monitoring ZHA devices. It checks device `last_seen` timestamps and reports devices that have not been seen within the configured delay.

## Installation

This component is intended to live in `custom_components/zha_watchdog` (for example as a git submodule in a Home Assistant configuration repository).

## Configuration

Add the sensor platform in your Home Assistant configuration:

```yaml
sensor:
  - platform: zha_watchdog
    max_delay: 120  # minutes (default: 120)
    device_delay:
      some_device_name: 180
```

- `max_delay` (optional): default maximum allowed delay in minutes before a non-coordinator device is considered missing/stale.
- `device_delay` (optional): mapping of device name to device-specific delay in minutes.

The sensor state reflects watchdog status (and may indicate a missing device name when detected), with additional device information exposed in attributes.
