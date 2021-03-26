"""ZHA Watchdog Sensor"""
import logging
from datetime import datetime

import voluptuous as vol
# sensor:
#   - platform: zha_watchdog
#     max_delay: 60

from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import PLATFORM_SCHEMA

import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, ZHA_WD_SENSOR, DATA_ZHA, DATA_ZHA_GATEWAY
from .const import (
    ATTR_NAME,
    ATTR_LAST_SEEN,
    CONF_MAX_DELAY,
    DEFAULT_MAX_DELAY,
    ATTR_USER_GIVEN_NAME,
    ATTR_IEEE)

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_MAX_DELAY, default=DEFAULT_MAX_DELAY): cv.string,
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the sensors."""
    max_delay = config.get(CONF_MAX_DELAY)
    hass.data[DOMAIN] = {}
    sensor = ZhaWdSensor(hass, max_delay)
    hass.data[DOMAIN][ZHA_WD_SENSOR] = sensor
    async_add_entities([sensor], True)


class ZhaWdSensor(Entity):
    """Representation of a ZHA Watchdog sensor."""

    def __init__(self, hass, max_delay):
        """Initialization"""
        self._name = 'ZHA Watchdog'
        self._attributes = {}
        self._state = 'running'
        self._hass = hass
        self._max_delay = int(max_delay)

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the attributes of the entity."""
        return self._attributes

    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        if DATA_ZHA in self._hass.data:
            if DATA_ZHA_GATEWAY in self._hass.data[DATA_ZHA]:
                zha_gateway = self._hass.data[DATA_ZHA][DATA_ZHA_GATEWAY]
                devices = [device.zha_device_info
                           for device in zha_gateway.devices.values()]
                attrs = {}
                current_time = datetime.now()
                missing_devices = False
                for device in devices:
                    name = device[ATTR_NAME]
                    if (name != 'unk_manufacturer unk_model'):
                        user_given_name = device[ATTR_USER_GIVEN_NAME]
                        ieee = device[ATTR_IEEE]
                        last_seen = device[ATTR_LAST_SEEN]
                        last_seen_time = datetime.strptime(last_seen,
                                                           '%Y-%m-%dT%H:%M:%S')
                        delta = (current_time - last_seen_time).total_seconds()
                        _LOGGER.info(delta / 60)
                        if (user_given_name is None):
                            name = name + '_' + ieee
                        else:
                            name = user_given_name
                        if ((delta / 60) > self._max_delay):
                            self._state = name
                            missing_devices = True
                        attrs[name.replace(' ', '_')] = last_seen

                self._attributes.update(attrs)
                if (not missing_devices):
                    self._state = 'running'

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
