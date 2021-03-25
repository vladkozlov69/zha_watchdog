"""Support for reading data from a serial port."""
import json
import logging

# sensor:
#   - platform: zb_sensor

from homeassistant.helpers.entity import Entity

from .const import DOMAIN, ZB_SENSOR, DATA_ZHA, DATA_ZHA_GATEWAY

_LOGGER = logging.getLogger(__name__)
_LOGGER.setLevel(logging.DEBUG)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the sensors."""
    hass.data[DOMAIN] = {}
    sensor = ZBSensor(hass)
    hass.data[DOMAIN][ZB_SENSOR] = sensor

    # await _async_setup_entity(async_add_entities, config)

    async_add_entities([sensor], True)

# async def _async_setup_entity(async_add_entities, config, config_entry=None, discovery_data=None
# ):
#     """Set up the MQTT Camera."""
#     async_add_entities([MqttCamera(config, config_entry, discovery_data)])


class ZBSensor(Entity):
    """Representation of a RCSLink sensor."""

    def __init__(self, hass):
        """Initialization"""
        self._name = 'ZBSensor'
        self._attributes = {}
        self._state = None
        self._hass = hass
        _LOGGER.debug('ZBSensor init')

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    # @property
    # def should_poll(self):
    #     """No polling needed."""
    #     return False

    @property
    def device_state_attributes(self):
        """Return the attributes of the entity (if any JSON present)."""
        return self._attributes

    def update(self):
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        _LOGGER.debug('ZBSensor update')
        if DATA_ZHA in self._hass.data:
            if DATA_ZHA_GATEWAY in self._hass.data[DATA_ZHA]:
                zha_gateway = self._hass.data[DATA_ZHA][DATA_ZHA_GATEWAY]
                devices = [device.zha_device_info for device in zha_gateway.devices.values()]
                attrs = {}
                for device in devices:
                    name = device['name']
                    last_seen = device['last_seen']
                    if (name != 'unk_manufacturer unk_model'):
                        attrs[name.replace(' ', '_')] = last_seen
                        _LOGGER.debug('name: %s, last_seen:%s', 
                                    device['name'], 
                                    device['last_seen'])
                self._attributes.update(attrs)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state
