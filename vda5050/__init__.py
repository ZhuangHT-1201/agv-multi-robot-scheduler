"""VDA5050 Protocol Implementation for Python"""

from .structs import *

__version__ = "1.0.0"

# Try to import MQTT client, but don't fail if paho-mqtt is not installed
try:
    from .mqtt_client import VDA5050Client
    __all__ = ["VDA5050Client"]
except ImportError:
    __all__ = []
    import warnings
    warnings.warn("paho-mqtt not installed. MQTT client functionality will not be available. "
                  "Install it with: pip install paho-mqtt")
