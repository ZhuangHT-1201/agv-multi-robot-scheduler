"""VDA5050 Usage Example"""

import time
import logging
import sys
import os


project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from vda5050 import VDA5050Client
from vda5050.structs import (
    Order, Header, Node, Edge, NodePosition, Action,
    State, InstantActions
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def state_update_callback(state: State):
    """Callback function for handling state updates from AGV"""
    logger.info(f"AGV state update received:")
    logger.info(f"  - Order ID: {state.orderId}")
    logger.info(f"  - Last node: {state.lastNodeId}")
    logger.info(f"  - Position: ({state.agvPosition.x:.2f}, {state.agvPosition.y:.2f})")
    logger.info(f"  - Heading: {state.agvPosition.theta:.2f} rad")
    logger.info(f"  - Battery: {state.batteryState.batteryCharge:.1f}%")
    logger.info(f"  - Driving: {state.driving}")
    logger.info(f"  - Operating mode: {state.operatingMode}")


    if state.errors:
        logger.warning(f"  - Errors: {len(state.errors)}")
        for error in state.errors:
            logger.warning(f"    * {error.errorType}: {error.errorDescription}")


def connection_callback(connection):
    """Callback function for handling connection status updates"""
    logger.info(f"AGV connection state: {connection.connectionState}")


def create_sample_order(
    manufacturer: str,
    serial_number: str,
    order_id: str = "ORDER_001",
    map_id: str = "map_1"
) -> Order:
    """
    Create a sample order

    The order contains three nodes and two edges
    """
    # Create header.
    header = Header.create(manufacturer, serial_number)


    nodes = [
        Node(
            nodeId="node_1",
            sequenceId=0,
            released=True,
            nodePosition=NodePosition(
                x=0.0,
                y=0.0,
                theta=0.0,
                mapId=map_id
            ),
            actions=[
                Action(
                    actionId="action_start",
                    actionType="startCharging",
                    blockingType="HARD"
                )
            ]
        ),
        Node(
            nodeId="node_2",
            sequenceId=2,
            released=True,
            nodePosition=NodePosition(
                x=10.0,
                y=0.0,
                theta=0.0,
                mapId=map_id
            ),
            actions=[]
        ),
        Node(
            nodeId="node_3",
            sequenceId=4,
            released=True,
            nodePosition=NodePosition(
                x=10.0,
                y=10.0,
                theta=1.57,  # 90 degrees
                mapId=map_id
            ),
            actions=[
                Action(
                    actionId="action_end",
                    actionType="stopCharging",
                    blockingType="HARD"
                )
            ]
        )
    ]


    edges = [
        Edge(
            edgeId="edge_1",
            sequenceId=1,
            startNodeId="node_1",
            endNodeId="node_2",
            released=True,
            maxSpeed=2.0,
            actions=[]
        ),
        Edge(
            edgeId="edge_2",
            sequenceId=3,
            startNodeId="node_2",
            endNodeId="node_3",
            released=True,
            maxSpeed=1.5,
            actions=[]
        )
    ]


    order = Order(
        header=header,
        orderId=order_id,
        orderUpdateId=0,
        nodes=nodes,
        edges=edges
    )

    return order


def main():
    """Demonstrate the VDA5050 client"""


    BROKER_HOST = os.environ.get("VDA5050_MQTT_BROKER", "127.0.0.1")
    BROKER_PORT = 1883
    MANUFACTURER = "AGV_Simulator"
    SERIAL_NUMBER = "AGV_001"


    logger.info("Creating VDA5050 client...")
    client = VDA5050Client(
        broker_host=BROKER_HOST,
        broker_port=BROKER_PORT,
        manufacturer=MANUFACTURER,
        qos=1
    )


    logger.info("Connecting to MQTT broker...")
    if not client.connect():
        logger.error("Cannot connect to MQTT broker; exiting")
        return


    time.sleep(1)

    if not client.is_connected:
        logger.error("MQTT connection not established; exiting")
        return


    logger.info(f"Subscribing to AGV {SERIAL_NUMBER} state updates...")
    client.subscribe_to_agv_state(SERIAL_NUMBER, state_update_callback)


    logger.info(f"Subscribing to AGV {SERIAL_NUMBER} connection state...")
    client.subscribe_to_agv_connection(SERIAL_NUMBER, connection_callback)


    time.sleep(1)


    logger.info("Creating sample order...")
    order = create_sample_order(MANUFACTURER, SERIAL_NUMBER)

    logger.info(f"Sending order {order.orderId} to AGV {SERIAL_NUMBER}...")
    if client.send_order(SERIAL_NUMBER, order):
        logger.info("Order sent successfully")
    else:
        logger.error("Failed to send order")


    logger.info("\nSending an instant action in 5 seconds...")
    time.sleep(5)

    instant_actions = InstantActions(
        header=Header.create(MANUFACTURER, SERIAL_NUMBER),
        actions=[
            Action(
                actionId="instant_action_1",
                actionType="pause",
                blockingType="HARD",
                actionDescription="Pause AGV motion"
            )
        ]
    )

    logger.info("Sending instant action...")
    if client.send_instant_actions(SERIAL_NUMBER, instant_actions):
        logger.info("Instant action sent successfully")
    else:
        logger.error("Failed to send instant action")


    logger.info("\nListening for state updates (Ctrl+C to exit)...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\nInterrupt received; shutting down...")


    client.disconnect()
    logger.info("Application stopped")


if __name__ == "__main__":
    main()
