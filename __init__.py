"""ZHA Watchdog integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

try:
    import voluptuous as vol
except Exception:  # noqa: BLE001
    vol = None  # type: ignore[assignment]

try:
    from homeassistant.helpers.service import async_register_admin_service
except Exception:  # noqa: BLE001
    async_register_admin_service = None  # type: ignore[assignment]

from .const import DOMAIN, SERVICE_RELOAD, ZHA_WD_SENSOR

_LOGGER = logging.getLogger(__name__)

if hasattr(cv, "config_entry_only_config_schema"):
    CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
elif hasattr(cv, "empty_config_schema") and vol is not None:
    CONFIG_SCHEMA = vol.Schema({DOMAIN: cv.empty_config_schema(DOMAIN)}, extra=vol.ALLOW_EXTRA)
elif vol is not None:
    CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({}, extra=vol.ALLOW_EXTRA)}, extra=vol.ALLOW_EXTRA)
else:  # pragma: no cover - fallback for unusual environments
    CONFIG_SCHEMA = {}


def _find_platform_config_from_loaded(loaded: Any) -> dict[str, Any] | None:
    """Extract zha_watchdog platform config from a loaded YAML structure."""
    if isinstance(loaded, list):
        for item in loaded:
            if isinstance(item, dict) and item.get("platform") == DOMAIN:
                return dict(item)
    elif isinstance(loaded, dict):
        if loaded.get("platform") == DOMAIN:
            return dict(loaded)
        sensor_section = loaded.get("sensor")
        if sensor_section is not None:
            found = _find_platform_config_from_loaded(sensor_section)
            if found is not None:
                return found
    return None


def _load_platform_config_from_yaml_files(hass: HomeAssistant) -> dict[str, Any] | None:
    """Load updated zha_watchdog platform config from YAML files (sync)."""
    load_yaml = None
    try:
        from homeassistant.util.yaml import load_yaml as ha_load_yaml  # type: ignore[attr-defined]

        load_yaml = ha_load_yaml
    except Exception:  # noqa: BLE001
        try:
            import yaml

            def load_yaml(path: str) -> Any:  # type: ignore[no-redef]
                with open(path, encoding="utf-8") as file_obj:
                    return yaml.safe_load(file_obj)
        except Exception:  # noqa: BLE001
            return None

    candidates = [
        hass.config.path("sensors.yaml"),
        hass.config.path("configuration.yaml"),
    ]
    for path in candidates:
        try:
            loaded = load_yaml(path)  # type: ignore[misc]
        except FileNotFoundError:
            continue
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Unable to read YAML config from %s: %s", path, err)
            continue
        platform_config = _find_platform_config_from_loaded(loaded)
        if platform_config is not None:
            return platform_config
    return None


async def async_get_updated_platform_config(
    hass: HomeAssistant, fallback: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Return refreshed platform config from YAML, or fallback if unavailable."""
    loaded = await hass.async_add_executor_job(_load_platform_config_from_yaml_files, hass)
    if loaded is not None:
        return loaded
    return fallback


def _register_reload_service(hass: HomeAssistant) -> None:
    """Register the zha_watchdog.reload service if not already present."""
    if hass.services.has_service(DOMAIN, SERVICE_RELOAD):
        return

    async def _handle_reload(_call: ServiceCall) -> None:
        domain_data = hass.data.get(DOMAIN, {})
        sensor_entity = domain_data.get(ZHA_WD_SENSOR)
        if sensor_entity is None:
            _LOGGER.warning("ZHA Watchdog reload requested but sensor is not set up")
            return
        fallback = domain_data.get("platform_config")
        new_config = await async_get_updated_platform_config(hass, fallback=fallback)
        if new_config is None:
            _LOGGER.warning(
                "ZHA Watchdog reload could not find updated YAML config; keeping current config"
            )
            return
        domain_data["platform_config"] = dict(new_config)
        if hasattr(sensor_entity, "async_apply_platform_config"):
            await sensor_entity.async_apply_platform_config(new_config)
        else:
            sensor_entity.apply_platform_config(new_config)
            if hasattr(sensor_entity, "async_schedule_update_ha_state"):
                sensor_entity.async_schedule_update_ha_state(True)

    if async_register_admin_service is not None:
        async_register_admin_service(hass, DOMAIN, SERVICE_RELOAD, _handle_reload)
    else:
        hass.services.async_register(DOMAIN, SERVICE_RELOAD, _handle_reload)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the ZHA Watchdog integration domain."""
    hass.data.setdefault(DOMAIN, {})
    _register_reload_service(hass)
    return True
