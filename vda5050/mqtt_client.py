"""VDA5050 MQTT Client Implementation"""

import json
import logging
from typing import Callable, Optional, Dict, Any
import paho.mqtt.client as mqtt
from threading import Lock

from .structs import Order, State, InstantActions, Connection, to_dict, from_json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VDA5050Client:
    """
    VDA5050 MQTT Client for AGV communication

    This client handles:
    - Publishing Order messages to AGVs
    - Publishing InstantActions messages
    - Subscribing to State updates from AGVs
    - Subscribing to Connection status
    """

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 1883,
        manufacturer: str = "AGV_Simulator",
        qos: int = 1,
        interface_name: str = "uagv",
        major_version: str = "v2",
        username: Optional[str] = None,
        password: Optional[str] = None,
        client_id: Optional[str] = None
    ):
        """
        Initialize VDA5050 MQTT Client

        Args:
            broker_host: MQTT broker hostname/IP
            broker_port: MQTT broker port (default: 1883)
            manufacturer: Manufacturer name for topic structure
            qos: MQTT QoS level (0, 1, or 2)
            interface_name: Interface name for VDA5050 topics (default: "uagv")
            major_version: VDA5050 major version (default: "v2")
            username: MQTT username (optional)
            password: MQTT password (optional)
            client_id: Custom MQTT client ID (optional, will generate unique ID if not provided)
        """
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.manufacturer = manufacturer
        self.qos = qos
        self.interface_name = interface_name
        self.major_version = major_version

        # Generate unique client ID if not provided
        if client_id is None:
            import time
            import uuid
            unique_suffix = str(uuid.uuid4())[:8]
            client_id = f"vda5050_master_{manufacturer}_{unique_suffix}"

        # MQTT client
        self.client = mqtt.Client(client_id=client_id)

        # Set username and password if provided
        if username and password:
            self.client.username_pw_set(username, password)

        # Set callbacks
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        # Callback handlers
        self._state_callbacks: Dict[str, Callable[[State], None]] = {}
        self._connection_callbacks: Dict[str, Callable[[Connection], None]] = {}
        self._lock = Lock()

        # Connection state
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to MQTT broker

        Returns:
            True if connection successful, False otherwise
        """
        try:
            logger.info(f"Connecting to MQTT broker at {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, keepalive=60)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self):
        """Disconnect from MQTT broker"""
        logger.info("Disconnecting from MQTT broker")
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            logger.info("Connected to MQTT broker successfully")
            self._connected = True
        else:
            logger.error(f"Failed to connect to MQTT broker with code: {rc}")
            self._connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection from MQTT broker (rc: {rc})")
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            logger.debug(f"Received message on topic: {topic}")

            # Parse topic to get serial number and message type
            # Topic format: {interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/{topic}
            topic_parts = topic.split('/')

            if len(topic_parts) < 5:
                logger.warning(f"Invalid topic format: {topic}")
                return

            serial_number = topic_parts[3]
            message_type = topic_parts[4]

            # Handle different message types
            if message_type == "state":
                self._handle_state_message(serial_number, payload)
            elif message_type == "connection":
                self._handle_connection_message(serial_number, payload)
            else:
                logger.debug(f"Unhandled message type: {message_type}")

        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)

    def _handle_state_message(self, serial_number: str, payload: str):
        """Handle State message"""
        try:
            data = json.loads(payload)
            state = from_json(data, State)

            with self._lock:
                if serial_number in self._state_callbacks:
                    self._state_callbacks[serial_number](state)

        except Exception as e:
            logger.error(f"Error handling state message: {e}", exc_info=True)

    def _handle_connection_message(self, serial_number: str, payload: str):
        """Handle Connection message"""
        try:
            data = json.loads(payload)
            connection = from_json(data, Connection)

            with self._lock:
                if serial_number in self._connection_callbacks:
                    self._connection_callbacks[serial_number](connection)

        except Exception as e:
            logger.error(f"Error handling connection message: {e}", exc_info=True)

    def subscribe_to_agv_state(
        self,
        serial_number: str,
        callback: Callable[[State], None]
    ) -> bool:
        """
        Subscribe to State messages from an AGV

        Args:
            serial_number: AGV serial number
            callback: Callback function to handle State messages

        Returns:
            True if subscription successful
        """
        topic = self._build_topic(serial_number, "state")

        try:
            result, mid = self.client.subscribe(topic, qos=self.qos)

            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Subscribed to state topic: {topic}")
                with self._lock:
                    self._state_callbacks[serial_number] = callback
                return True
            else:
                logger.error(f"Failed to subscribe to topic: {topic}")
                return False

        except Exception as e:
            logger.error(f"Error subscribing to state: {e}")
            return False

    def subscribe_to_agv_connection(
        self,
        serial_number: str,
        callback: Callable[[Connection], None]
    ) -> bool:
        """
        Subscribe to Connection messages from an AGV

        Args:
            serial_number: AGV serial number
            callback: Callback function to handle Connection messages

        Returns:
            True if subscription successful
        """
        topic = self._build_topic(serial_number, "connection")

        try:
            result, mid = self.client.subscribe(topic, qos=self.qos)

            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Subscribed to connection topic: {topic}")
                with self._lock:
                    self._connection_callbacks[serial_number] = callback
                return True
            else:
                logger.error(f"Failed to subscribe to topic: {topic}")
                return False

        except Exception as e:
            logger.error(f"Error subscribing to connection: {e}")
            return False

    def send_order(self, serial_number: str, order: Order) -> bool:
        """
        Send an Order to an AGV

        Args:
            serial_number: Target AGV serial number
            order: Order object to send

        Returns:
            True if message sent successfully
        """
        if not self._connected:
            logger.error("Not connected to MQTT broker")
            return False

        topic = self._build_topic(serial_number, "order")

        try:
            # Convert order to dict and remove None values
            order_dict = to_dict(order, remove_none=True)
            payload = json.dumps(order_dict, ensure_ascii=False)

            result = self.client.publish(topic, payload, qos=self.qos)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Sent order {order.orderId} to AGV {serial_number}")
                return True
            else:
                logger.error(f"Failed to send order: {result.rc}")
                return False

        except Exception as e:
            logger.error(f"Error sending order: {e}", exc_info=True)
            return False

    def send_instant_actions(
        self,
        serial_number: str,
        instant_actions: InstantActions
    ) -> bool:
        """
        Send InstantActions to an AGV

        Args:
            serial_number: Target AGV serial number
            instant_actions: InstantActions object to send

        Returns:
            True if message sent successfully
        """
        if not self._connected:
            logger.error("Not connected to MQTT broker")
            return False

        topic = self._build_topic(serial_number, "instantActions")

        try:
            # Convert to dict and remove None values
            actions_dict = to_dict(instant_actions, remove_none=True)
            payload = json.dumps(actions_dict, ensure_ascii=False)

            result = self.client.publish(topic, payload, qos=self.qos)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Sent instant actions to AGV {serial_number}")
                return True
            else:
                logger.error(f"Failed to send instant actions: {result.rc}")
                return False

        except Exception as e:
            logger.error(f"Error sending instant actions: {e}", exc_info=True)
            return False

    def _build_topic(self, serial_number: str, message_type: str) -> str:
        """
        Build VDA5050 compliant topic string

        Topic format: {interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/{topic}

        Args:
            serial_number: AGV serial number
            message_type: Message type (order, state, instantActions, connection, etc.)

        Returns:
            Full topic string
        """
        return f"{self.interface_name}/{self.major_version}/{self.manufacturer}/{serial_number}/{message_type}"

    @property
    def is_connected(self) -> bool:
        """Check if client is connected to broker"""
        return self._connected
