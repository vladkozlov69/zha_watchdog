"""ZHA Watchdog Sensor."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

try:
    from homeassistant.components.sensor import SensorEntity as SensorEntityBase
except Exception:  # noqa: BLE001
    SensorEntityBase = Entity

from .const import (
    ATTR_DEVICE_LAST_SEEN,
    ATTR_LAST_CHECKED,
    ATTR_OVERDUE_COUNT,
    ATTR_OVERDUE_DEVICES,
    CONF_DEVICE_DELAY,
    CONF_MAX_DELAY,
    DATA_ZHA,
    DEFAULT_MAX_DELAY,
    DEVICE_TYPE_COORDINATOR,
    DOMAIN,
    ZHA_WD_SENSOR,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_DELAY_SCHEMA = vol.Schema({cv.string: cv.positive_int})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_MAX_DELAY, default=DEFAULT_MAX_DELAY): cv.positive_int,
        vol.Optional(CONF_DEVICE_DELAY, default={}): DEVICE_DELAY_SCHEMA,
    }
)


def _normalize_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize platform config values."""
    config = dict(config or {})
    max_delay = config.get(CONF_MAX_DELAY, DEFAULT_MAX_DELAY)
    try:
        max_delay = int(max_delay)
    except (TypeError, ValueError):
        max_delay = DEFAULT_MAX_DELAY
    if max_delay <= 0:
        max_delay = DEFAULT_MAX_DELAY

    device_delay_raw = config.get(CONF_DEVICE_DELAY) or {}
    device_delay: dict[str, int] = {}
    if isinstance(device_delay_raw, dict):
        for key, value in device_delay_raw.items():
            try:
                delay = int(value)
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "Ignoring invalid zha_watchdog device_delay for %s: %s", key, value
                )
                continue
            if delay <= 0:
                _LOGGER.warning(
                    "Ignoring non-positive zha_watchdog device_delay for %s: %s", key, value
                )
                continue
            device_delay[str(key)] = delay
    else:
        _LOGGER.warning(
            "Ignoring invalid zha_watchdog device_delay mapping: %s", device_delay_raw
        )

    return {CONF_MAX_DELAY: max_delay, CONF_DEVICE_DELAY: device_delay}


def _normalize_match_text(value: Any) -> str | None:
    """Normalize text for flexible device-delay key matching."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    # Collapse whitespace and common IEEE separators for tolerant matching.
    text = " ".join(text.split())
    text = (
        text.replace(":", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace(".", " ")
    )
    return " ".join(text.split()) or None


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    """Set up the ZHA Watchdog sensor."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    normalized = _normalize_config(config)
    domain_data["platform_config"] = normalized

    # Ensure reload service is available even when domain async_setup was not invoked.
    try:
        from . import _register_reload_service

        _register_reload_service(hass)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not register zha_watchdog reload service from platform setup")

    existing = domain_data.get(ZHA_WD_SENSOR)
    if existing is not None:
        if hasattr(existing, "async_apply_platform_config"):
            await existing.async_apply_platform_config(normalized)
        else:
            existing.apply_platform_config(normalized)
            existing.async_schedule_update_ha_state(True)
        return

    sensor = ZhaWdSensor(hass, normalized)
    domain_data[ZHA_WD_SENSOR] = sensor
    async_add_entities([sensor], True)


def _get_attr_or_key(obj: Any, *names: str) -> Any:
    """Return first matching attribute or mapping key from object."""
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict) and name in obj:
            value = obj.get(name)
            if value is not None:
                return value
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return None


def _extract_device_info(device_obj: Any) -> Any:
    """Best-effort extraction of device info/container from ZHA device wrappers."""
    if device_obj is None:
        return None
    info = getattr(device_obj, "device_info", None)
    if info is not None:
        return info
    zha_device_info = getattr(device_obj, "zha_device_info", None)
    if zha_device_info is not None:
        return zha_device_info
    return device_obj


def _parse_last_seen(value: Any) -> datetime | None:
    """Parse last_seen into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            parsed = dt_util.utc_from_timestamp(float(value))
        except (OverflowError, OSError, ValueError, TypeError):
            return None
        return parsed
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = dt_util.parse_datetime(text)
        if parsed is None:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        # Treat naive timestamps as UTC for consistent watchdog comparisons.
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return dt_util.as_utc(parsed)


def _sanitize_attr_key(name: str) -> str:
    """Create a safe-ish attribute key while preserving readability."""
    sanitized = []
    for char in name:
        if char.isalnum() or char in ("_", "-"):
            sanitized.append(char)
        elif char.isspace():
            sanitized.append("_")
        else:
            sanitized.append("_")
    key = "".join(sanitized).strip("_")
    return key or "device"


class ZhaWdSensor(SensorEntityBase):
    """Representation of a ZHA Watchdog sensor."""

    _attr_should_poll = True
    _attr_icon = "mdi:lan-connect"

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        """Initialize the watchdog sensor."""
        self.hass = hass
        self._attr_name = "ZHA Watchdog"
        self._attr_unique_id = f"{DOMAIN}_sensor"
        self._state: str = "running"
        self._attributes: dict[str, Any] = {}
        self._available = True
        self._max_delay = DEFAULT_MAX_DELAY
        self._device_delay: dict[str, int] = {}
        self._device_delay_normalized: dict[str, tuple[str, int]] = {}
        self._unmatched_delay_keys: set[str] | None = None
        self.apply_platform_config(config)

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._attr_name

    @property
    def unique_id(self) -> str | None:
        """Return unique ID for the entity."""
        return self._attr_unique_id

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self._available

    @property
    def native_value(self) -> str:
        """Return sensor state."""
        return self._state

    @property
    def state(self) -> str:  # type: ignore[override]
        """Return the state for compatibility with older HA/entity APIs."""
        return self._state

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return state attributes."""
        return self._attributes

    def apply_platform_config(self, config: dict[str, Any] | None) -> None:
        """Apply normalized platform config."""
        normalized = _normalize_config(config)
        self._max_delay = normalized[CONF_MAX_DELAY]
        self._device_delay = normalized[CONF_DEVICE_DELAY]
        self._device_delay_normalized = {}
        for key, delay in self._device_delay.items():
            norm = _normalize_match_text(key)
            if norm and norm not in self._device_delay_normalized:
                self._device_delay_normalized[norm] = (key, delay)
        self._unmatched_delay_keys = set(self._device_delay.keys())
        _LOGGER.debug(
            "ZHA Watchdog config applied: max_delay=%s, device_delay=%s",
            self._max_delay,
            self._device_delay,
        )

    async def async_apply_platform_config(self, config: dict[str, Any] | None) -> None:
        """Apply config and refresh state."""
        self.apply_platform_config(config)
        self.async_schedule_update_ha_state(True)

    def _resolve_gateway(self) -> Any | None:
        """Resolve ZHA gateway/gateway-like object from hass.data."""
        zha_data = self.hass.data.get(DATA_ZHA)
        if zha_data is None:
            return None

        # Common patterns across HA/ZHA versions
        for candidate in (
            zha_data,
            getattr(zha_data, "gateway", None),
            getattr(zha_data, "gateway_proxy", None),
        ):
            if candidate is None:
                continue
            gateway = getattr(candidate, "gateway", None)
            if gateway is not None and getattr(gateway, "devices", None) is not None:
                return gateway
            if getattr(candidate, "devices", None) is not None:
                return candidate
            proxy = getattr(candidate, "gateway_proxy", None)
            if proxy is not None:
                gateway = getattr(proxy, "gateway", None)
                if gateway is not None and getattr(gateway, "devices", None) is not None:
                    return gateway

        # Sometimes hass.data[DATA_ZHA] is a dict-like container
        if isinstance(zha_data, dict):
            for key in ("gateway", "zha_gateway", "gateway_proxy"):
                candidate = zha_data.get(key)
                if candidate is None:
                    continue
                gateway = getattr(candidate, "gateway", None)
                if gateway is not None and getattr(gateway, "devices", None) is not None:
                    return gateway
                if getattr(candidate, "devices", None) is not None:
                    return candidate
        return None

    def _iter_devices(self, gateway: Any) -> list[Any]:
        """Return iterable device objects from a gateway."""
        devices = getattr(gateway, "devices", None)
        if devices is None:
            return []
        if isinstance(devices, dict):
            return list(devices.values())
        try:
            return list(devices)
        except TypeError:
            return []

    def _get_gateway_proxy(self, gateway: Any) -> Any | None:
        """Best-effort access to ZHA gateway proxy (legacy API compatibility)."""
        zha_data = self.hass.data.get(DATA_ZHA)
        for candidate in (
            getattr(zha_data, "gateway_proxy", None) if zha_data is not None else None,
            getattr(gateway, "gateway_proxy", None),
            getattr(getattr(gateway, "application_controller", None), "gateway_proxy", None),
        ):
            if candidate is not None:
                return candidate
        if isinstance(zha_data, dict):
            for key in ("gateway_proxy", "proxy"):
                if zha_data.get(key) is not None:
                    return zha_data.get(key)
        return None

    def _get_user_given_name(self, gateway: Any, device_obj: Any, ieee: Any) -> str | None:
        """Get user-given name using legacy ZHA proxy path first for compatibility."""
        proxy = self._get_gateway_proxy(gateway)
        if proxy is not None and ieee is not None:
            try:
                get_device_proxy = getattr(proxy, "get_device_proxy", None)
                if callable(get_device_proxy):
                    device_proxy = get_device_proxy(ieee)
                else:
                    device_proxy = None
                if device_proxy is not None:
                    zha_info = getattr(device_proxy, "zha_device_info", None)
                    if isinstance(zha_info, dict):
                        value = zha_info.get("user_given_name")
                        if value not in (None, ""):
                            return str(value)
            except Exception:  # noqa: BLE001
                pass
        info = _extract_device_info(device_obj)
        value = _get_attr_or_key(device_obj, "user_given_name", "name_by_user") or _get_attr_or_key(
            info, "user_given_name", "name_by_user"
        )
        if value in (None, ""):
            return None
        return str(value)

    def _resolve_expected_delay(self, legacy_name: str) -> tuple[int, str | None]:
        """Resolve expected delay using the same name-matching logic as before change."""
        if self._device_delay and legacy_name in self._device_delay:
            return self._device_delay[legacy_name], legacy_name
        return self._max_delay, None

    def update(self) -> None:
        """Fetch new state data for the sensor."""
        now = dt_util.utcnow()
        gateway = self._resolve_gateway()
        if gateway is None:
            # Keep entity available with compatibility-oriented state; report unavailable ZHA in attributes.
            self._available = True
            attrs: dict[str, Any] = {
                ATTR_LAST_CHECKED: now.isoformat(),
                ATTR_OVERDUE_DEVICES: [],
                ATTR_OVERDUE_COUNT: 0,
                "zha_available": False,
            }
            if self._device_delay:
                attrs["unmatched_device_delay_keys"] = sorted(self._device_delay.keys())
            self._attributes = attrs
            self._state = "running"
            return

        self._available = True
        devices = self._iter_devices(gateway)
        device_attrs: dict[str, Any] = {}
        overdue_devices: list[str] = []
        checked_count = 0
        matched_delay_keys: set[str] = set()

        for device_obj in devices:
            try:
                info = _extract_device_info(device_obj)
                ieee = _get_attr_or_key(info, "ieee") or _get_attr_or_key(device_obj, "ieee")
                ieee_str = str(ieee) if ieee is not None else None

                device_name = _get_attr_or_key(info, "name") or _get_attr_or_key(device_obj, "name")
                device_name_str = str(device_name) if device_name is not None else None

                # Skip clearly unknown placeholders if no stable identity is available (as before).
                if device_name_str == "unk_manufacturer unk_model":
                    continue

                user_given_name_str = self._get_user_given_name(gateway, device_obj, ieee)
                device_type = _get_attr_or_key(info, "device_type") or _get_attr_or_key(
                    device_obj, "device_type"
                )
                device_type_str = str(device_type) if device_type is not None else None

                raw_last_seen = _get_attr_or_key(info, "last_seen") or _get_attr_or_key(
                    device_obj, "last_seen"
                )
                last_seen_dt = _parse_last_seen(raw_last_seen)

                # Legacy naming/matching behavior (pre-change): use user_given_name if set,
                # otherwise "<device.name>_<ieee>".
                if user_given_name_str is None:
                    legacy_name = f"{device_name_str}_{ieee_str}" if (device_name_str and ieee_str) else (device_name_str or ieee_str)
                else:
                    legacy_name = user_given_name_str
                if not legacy_name:
                    continue

                display_name = legacy_name

                # Normalize last_seen value for attributes.
                if raw_last_seen is None:
                    normalized_last_seen: Any = None
                elif isinstance(raw_last_seen, (str, int, float)):
                    normalized_last_seen = raw_last_seen
                elif isinstance(raw_last_seen, datetime):
                    normalized_last_seen = dt_util.as_utc(
                        raw_last_seen if raw_last_seen.tzinfo else raw_last_seen.replace(tzinfo=dt_util.UTC)
                    ).isoformat()
                else:
                    normalized_last_seen = str(raw_last_seen)

                # Expose per-device last_seen only under friendly/user-given legacy name
                # (avoid MAC/IEEE-only attributes and aggregate device_last_seen map).
                if user_given_name_str:
                    legacy_attr_key = legacy_name.replace(" ", "_")
                    if legacy_attr_key:
                        device_attrs[legacy_attr_key] = normalized_last_seen

                checked_count += 1

                # Coordinator is not evaluated for overdue (same as before), but keep last_seen.
                if device_type_str == DEVICE_TYPE_COORDINATOR:
                    continue
                if last_seen_dt is None:
                    continue

                expected_delay_minutes, matched_key = self._resolve_expected_delay(legacy_name)
                if matched_key:
                    matched_delay_keys.add(matched_key)

                age_seconds = (now - last_seen_dt).total_seconds()
                if age_seconds < 0:
                    # Clock skew or future timestamp; treat as just seen.
                    age_seconds = 0
                if (age_seconds / 60) > expected_delay_minutes:
                    overdue_devices.append(display_name)
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Error evaluating ZHA watchdog device %s: %s", device_obj, err)
                continue

        overdue_devices_sorted = sorted(set(overdue_devices))
        attrs: dict[str, Any] = {
            ATTR_LAST_CHECKED: now.isoformat(),
            ATTR_OVERDUE_DEVICES: overdue_devices_sorted,
            ATTR_OVERDUE_COUNT: len(overdue_devices_sorted),
            "checked_devices": checked_count,
            "max_delay": self._max_delay,
            "device_delay": dict(self._device_delay),
            "zha_available": True,
        }

        # Backward-compatible per-device attributes for friendly/user-given names only.
        for key, value in device_attrs.items():
            if key not in attrs:
                attrs[key] = value

        unmatched_delay_keys = sorted(set(self._device_delay.keys()) - matched_delay_keys)
        self._unmatched_delay_keys = set(unmatched_delay_keys)
        if unmatched_delay_keys:
            attrs["unmatched_device_delay_keys"] = unmatched_delay_keys

        self._attributes = attrs
        self._state = overdue_devices_sorted[0] if overdue_devices_sorted else "running"
