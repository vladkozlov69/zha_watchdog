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
    CONF_DEVICE_DELAY,
    DEFAULT_MAX_DELAY,
    ATTR_USER_GIVEN_NAME,
    ATTR_IEEE,
    ATTR_DEVICE_TYPE,
    DEVICE_TYPE_COORDINATOR)

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_MAX_DELAY, default=DEFAULT_MAX_DELAY): cv.positive_int,
    vol.Optional(CONF_DEVICE_DELAY): vol.Any(dict),
})


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the sensors."""
    max_delay = config.get(CONF_MAX_DELAY)
    device_delay = config.get(CONF_DEVICE_DELAY)
    _LOGGER.info('ZHA Watchdog device delay: %s', device_delay)
    #for key, value in device_delay.items():
        #_LOGGER.info('ZHA Watchdog device [%s] delay [%s]', key, value)
    hass.data[DOMAIN] = {}
    sensor = ZhaWdSensor(hass, max_delay, device_delay)
    hass.data[DOMAIN][ZHA_WD_SENSOR] = sensor
    async_add_entities([sensor], True)


class ZhaWdSensor(Entity):
    """Representation of a ZHA Watchdog sensor."""

    def __init__(self, hass, max_delay, device_delay):
        """Initialization"""
        self._name = 'ZHA Watchdog'
        self._attributes = {}
        self._state = 'running'
        self._hass = hass
        self._max_delay = max_delay
        self._device_delay = device_delay

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def extra_state_attributes(self):
        """Return the attributes of the entity."""
        return self._attributes

    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        if DATA_ZHA in self._hass.data:
            if self._hass.data[DATA_ZHA] is not None:
                #_LOGGER.info('self._hass.data[DATA_ZHA] = %s', self._hass.data[DATA_ZHA])
                zha_gateway_proxy = self._hass.data[DATA_ZHA].gateway_proxy
                zha_gateway = zha_gateway_proxy.gateway
                #_LOGGER.info('zha_gateway = %s', zha_gateway)
                if zha_gateway is None:
                    return
                devices = zha_gateway.devices.values()
                attrs = {}
                current_time = datetime.now()
                missing_devices = False
                for dv in devices:
                    device = dv.device_info
                    ieee = device.ieee
                    device_proxy = zha_gateway_proxy.get_device_proxy(ieee)
                    #_LOGGER.info(device)
                    #_LOGGER.info(device_proxy.zha_device_info)
                    name = device.name
                    if (name != 'unk_manufacturer unk_model'):
                        #_LOGGER.info(device_proxy.zha_device_info['user_given_name'])
                        user_given_name = device_proxy.zha_device_info['user_given_name']
                        device_type = device.device_type
                        ieee = device.ieee
                        last_seen = device.last_seen
                        last_seen_time = datetime.strptime(last_seen,
                                                           '%Y-%m-%dT%H:%M:%S')
                        delta = (current_time - last_seen_time).total_seconds()
                        if (user_given_name is None):
                            name = name + '_' + str(ieee)
                        else:
                            name = user_given_name
                        # _LOGGER.info('checking [%s]', name)

                        expected_delay = self._max_delay
                        if (self._device_delay is not None):
                            # _LOGGER.info('checking in [%s]', self._device_delay)
                            if (name in self._device_delay):
                                expected_delay = self._device_delay.get(name)
                                # _LOGGER.info('expected_delay [%s]', expected_delay)

                        if ((device_type != DEVICE_TYPE_COORDINATOR) and
                           ((delta / 60) > expected_delay)):
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
