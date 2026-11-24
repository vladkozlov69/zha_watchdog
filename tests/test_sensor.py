# Copyright (c) 2026 Vladimir Kozlov <vkozloff@gmail.com>
# SPDX-License-Identifier: MIT

"""Tests for the ZHA Watchdog sensor and reload behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.util import dt as dt_util

from zha_watchdog import async_setup as async_setup_domain
from zha_watchdog import _find_platform_config_from_loaded
from zha_watchdog.const import (
    ATTR_DEVICE_LAST_SEEN,
    ATTR_OVERDUE_COUNT,
    ATTR_OVERDUE_DEVICES,
    CONF_DEVICE_DELAY,
    CONF_MAX_DELAY,
    DATA_ZHA,
    DOMAIN,
    SERVICE_RELOAD,
    ZHA_WD_SENSOR,
)
from zha_watchdog.sensor import ZhaWdSensor, _normalize_config, async_setup_platform


class FakeDevice:
    """Simple fake ZHA device wrapper for tests."""

    def __init__(
        self,
        ieee,
        name,
        last_seen,
        device_type="EndDevice",
        user_given_name=None,
        *,
        use_device_info=True,
    ):
        self.ieee = ieee
        self.name = name
        self.last_seen = last_seen
        self.device_type = device_type
        self.user_given_name = user_given_name
        if use_device_info:
            self.device_info = SimpleNamespace(
                ieee=ieee,
                name=name,
                last_seen=last_seen,
                device_type=device_type,
                user_given_name=user_given_name,
            )


class FakeGateway:
    """Fake ZHA gateway exposing devices."""

    def __init__(self, devices):
        self.devices = devices


def _set_gateway(hass, devices):
    hass.data[DATA_ZHA] = SimpleNamespace(gateway=FakeGateway(devices))


@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_normalize_config_filters_invalid_device_delay():
    config = {
        CONF_MAX_DELAY: 60,
        CONF_DEVICE_DELAY: {
            "valid_name": 120,
            "valid_ieee": "180",
            "bad_value": "oops",
            "non_positive": 0,
        },
    }

    normalized = _normalize_config(config)

    assert normalized[CONF_MAX_DELAY] == 60
    assert normalized[CONF_DEVICE_DELAY] == {"valid_name": 120, "valid_ieee": 180}


def test_find_platform_config_from_sensors_list():
    loaded = [
        {"platform": "template", "sensors": {}},
        {"platform": DOMAIN, CONF_MAX_DELAY: 190, CONF_DEVICE_DELAY: {"A": 300}},
    ]

    found = _find_platform_config_from_loaded(loaded)

    assert found is not None
    assert found[CONF_MAX_DELAY] == 190
    assert found[CONF_DEVICE_DELAY] == {"A": 300}


def test_update_without_zha_reports_unavailable_info(hass, fixed_now):
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 60, CONF_DEVICE_DELAY: {}})
    hass.data.pop(DATA_ZHA, None)

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "running"
    assert sensor.available is True
    assert sensor.extra_state_attributes["zha_available"] is False
    assert sensor.extra_state_attributes[ATTR_OVERDUE_DEVICES] == []
    assert sensor.extra_state_attributes[ATTR_OVERDUE_COUNT] == 0


def test_overdue_device_sets_state_and_attributes(hass, fixed_now):
    stale = (fixed_now - timedelta(minutes=30)).isoformat()
    fresh = (fixed_now - timedelta(minutes=5)).isoformat()
    devices = {
        "dev1": FakeDevice("00:11:22:33:44:55:66:77", "Sensor One", stale, user_given_name="Kitchen Sensor"),
        "dev2": FakeDevice("00:11:22:33:44:55:66:88", "Sensor Two", fresh, user_given_name="Hall Sensor"),
    }
    _set_gateway(hass, devices)
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}})

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "Kitchen Sensor"
    assert sensor.extra_state_attributes[ATTR_OVERDUE_DEVICES] == ["Kitchen Sensor"]
    assert sensor.extra_state_attributes[ATTR_OVERDUE_COUNT] == 1
    assert sensor.extra_state_attributes["zha_available"] is True
    assert ATTR_DEVICE_LAST_SEEN not in sensor.extra_state_attributes
    assert "Kitchen_Sensor" in sensor.extra_state_attributes
    assert "00_11_22_33_44_55_66_77" not in sensor.extra_state_attributes
    assert "00 11 22 33 44 55 66 77" not in sensor.extra_state_attributes


def test_multiple_overdue_devices_are_deterministic(hass, fixed_now):
    stale = (fixed_now - timedelta(minutes=30)).isoformat()
    devices = {
        "b": FakeDevice("11:11:11:11:11:11:11:11", "B", stale, user_given_name="Beta"),
        "a": FakeDevice("22:22:22:22:22:22:22:22", "A", stale, user_given_name="Alpha"),
    }
    _set_gateway(hass, devices)
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}})

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "Alpha"
    assert sensor.extra_state_attributes[ATTR_OVERDUE_DEVICES] == ["Alpha", "Beta"]
    assert sensor.extra_state_attributes[ATTR_OVERDUE_COUNT] == 2


def test_device_delay_override_applies(hass, fixed_now):
    # 20 minutes old: overdue for default 10, but allowed by per-device override of 30.
    last_seen = (fixed_now - timedelta(minutes=20)).isoformat()
    devices = {
        "dev1": FakeDevice(
            "00:aa:bb:cc:dd:ee:ff:00",
            "Device",
            last_seen,
            user_given_name="Special Device",
        )
    }
    _set_gateway(hass, devices)
    sensor = ZhaWdSensor(
        hass,
        {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {"Special Device": 30}},
    )

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "running"
    assert sensor.extra_state_attributes[ATTR_OVERDUE_DEVICES] == []


def test_missing_or_unparseable_last_seen_is_skipped(hass, fixed_now):
    devices = {
        "none": FakeDevice("00:00:00:00:00:00:00:01", "NoSeen", None, user_given_name="No Seen"),
        "bad": FakeDevice(
            "00:00:00:00:00:00:00:02",
            "BadSeen",
            "not-a-timestamp",
            user_given_name="Bad Seen",
        ),
    }
    _set_gateway(hass, devices)
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}})

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "running"
    assert sensor.extra_state_attributes[ATTR_OVERDUE_COUNT] == 0
    assert "zha_available" in sensor.extra_state_attributes


def test_attributes_are_refreshed_each_update(hass, fixed_now):
    stale = (fixed_now - timedelta(minutes=30)).isoformat()
    devices_first = {
        "dev1": FakeDevice("00:11:22:33:44:55:66:77", "Sensor One", stale, user_given_name="Kitchen Sensor"),
    }
    devices_second = {}
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}})

    _set_gateway(hass, devices_first)
    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()
    assert sensor.state == "Kitchen Sensor"
    assert ATTR_DEVICE_LAST_SEEN not in sensor.extra_state_attributes
    assert "Kitchen_Sensor" in sensor.extra_state_attributes

    _set_gateway(hass, devices_second)
    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now + timedelta(minutes=1)):
        sensor.update()

    assert sensor.state == "running"
    assert sensor.extra_state_attributes[ATTR_OVERDUE_COUNT] == 0
    assert ATTR_DEVICE_LAST_SEEN not in sensor.extra_state_attributes
    # No stale per-device key should remain from previous run.
    assert "Kitchen_Sensor" not in sensor.extra_state_attributes
    assert "00:11:22:33:44:55:66:77" not in sensor.extra_state_attributes
    assert "00_11_22_33_44_55_66_77" not in sensor.extra_state_attributes


async def test_async_apply_platform_config_updates_thresholds(hass, fixed_now):
    last_seen = (fixed_now - timedelta(minutes=20)).isoformat()
    devices = {
        "dev1": FakeDevice(
            "00:aa:bb:cc:dd:ee:ff:00",
            "Device",
            last_seen,
            user_given_name="Special Device",
        )
    }
    _set_gateway(hass, devices)
    sensor = ZhaWdSensor(hass, {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}})
    hass.data.setdefault(DOMAIN, {})[ZHA_WD_SENSOR] = sensor

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()
    assert sensor.state == "Special Device"

    sensor.async_schedule_update_ha_state = lambda force_refresh=False: None  # type: ignore[assignment]
    await sensor.async_apply_platform_config(
        {CONF_MAX_DELAY: 30, CONF_DEVICE_DELAY: {}}
    )
    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()

    assert sensor.state == "running"
    assert sensor.extra_state_attributes["max_delay"] == 30


async def test_reload_service_applies_updated_yaml_config(hass, fixed_now):
    last_seen = (fixed_now - timedelta(minutes=20)).isoformat()
    devices = {
        "dev1": FakeDevice(
            "00:aa:bb:cc:dd:ee:ff:00",
            "Device",
            last_seen,
            user_given_name="Special Device",
        )
    }
    _set_gateway(hass, devices)

    assert await async_setup_domain(hass, {})
    await async_setup_platform(
        hass,
        {CONF_MAX_DELAY: 10, CONF_DEVICE_DELAY: {}},
        lambda entities, update_before_add=False: None,
    )
    sensor = hass.data[DOMAIN][ZHA_WD_SENSOR]

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now):
        sensor.update()
    assert sensor.state == "Special Device"

    new_config = {"platform": DOMAIN, CONF_MAX_DELAY: 30, CONF_DEVICE_DELAY: {}}
    sensor.async_schedule_update_ha_state = lambda force_refresh=False: sensor.update()  # type: ignore[assignment]

    with patch("zha_watchdog.sensor.dt_util.utcnow", return_value=fixed_now), patch(
        "zha_watchdog.async_get_updated_platform_config", AsyncMock(return_value=new_config)
    ):
        await hass.services.async_call(DOMAIN, SERVICE_RELOAD, blocking=True)

    assert sensor.state == "running"
    assert hass.data[DOMAIN]["platform_config"][CONF_MAX_DELAY] == 30
