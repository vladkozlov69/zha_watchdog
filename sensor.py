"""ZHA Watchdog Sensor"""
import logging
from datetime import datetime

# sensor:
#   - platform: zb_sensor

from homeassistant.helpers.entity import Entity

from .const import DOMAIN, ZHA_WD_SENSOR, DATA_ZHA, DATA_ZHA_GATEWAY
from .const import ATTR_NAME, ATTR_LAST_SEEN

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the sensors."""
    hass.data[DOMAIN] = {}
    sensor = ZhaWdSensor(hass)
    hass.data[DOMAIN][ZHA_WD_SENSOR] = sensor
    async_add_entities([sensor], True)


class ZhaWdSensor(Entity):
    """Representation of a ZHA Watchdog sensor."""

    def __init__(self, hass):
        """Initialization"""
        self._name = 'ZHA Watchdog'
        self._attributes = {}
        self._state = None
        self._hass = hass

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
                for device in devices:
                    name = device[ATTR_NAME]
                    if (name != 'unk_manufacturer unk_model'):
                        last_seen = device[ATTR_LAST_SEEN]
                        last_seen_time = datetime.strptime(last_seen,
                                                           '%Y-%m-%dT%H:%M:%S')
                        delta = (current_time - last_seen_time).total_seconds()
                        _LOGGER.info(delta / 60)
                        attrs[name.replace(' ', '_')] = last_seen

                self._attributes.update(attrs)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
