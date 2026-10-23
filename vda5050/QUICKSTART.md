# VDA5050 Quick Start

This guide connects a Python client to a local MQTT broker and subscribes to an
AGV state topic.

## 1. Install

```bash
python -m pip install paho-mqtt==1.6.1
```

## 2. Start a Local Broker

With Docker:

```bash
docker run --rm -p 1883:1883 eclipse-mosquitto
```

Set a non-default endpoint when needed:

```powershell
$env:VDA5050_MQTT_BROKER = "127.0.0.1"
$env:VDA5050_MQTT_PORT = "1883"
$env:VDA5050_MANUFACTURER = "agv-demo"
```

## 3. Connect

```python
from vda5050 import VDA5050Client


client = VDA5050Client(
    broker_host="127.0.0.1",
    broker_port=1883,
    manufacturer="agv-demo",
    qos=1,
)

if not client.connect():
    raise RuntimeError("MQTT connection failed")
```

## 4. Subscribe

```python
def on_state(state):
    print("Order:", state.orderId)
    print("Last node:", state.lastNodeId)
    print("Position:", state.agvPosition.x, state.agvPosition.y)
    print("Battery:", state.batteryState.batteryCharge)


client.subscribe_to_agv_state("AGV_001", on_state)
```

## 5. Send a Minimal Route

```python
from vda5050.structs import Edge, Header, Node, NodePosition, Order


order = Order(
    header=Header.create("agv-demo", "AGV_001"),
    orderId="ORDER_QUICKSTART",
    orderUpdateId=0,
    nodes=[
        Node(
            nodeId="a",
            sequenceId=0,
            released=True,
            nodePosition=NodePosition(
                x=0.0,
                y=0.0,
                theta=0.0,
                mapId="demo",
            ),
            actions=[],
        ),
        Node(
            nodeId="b",
            sequenceId=2,
            released=True,
            nodePosition=NodePosition(
                x=1.0,
                y=0.0,
                theta=0.0,
                mapId="demo",
            ),
            actions=[],
        ),
    ],
    edges=[
        Edge(
            edgeId="a-b",
            sequenceId=1,
            startNodeId="a",
            endNodeId="b",
            released=True,
            maxSpeed=1.0,
            actions=[],
        )
    ],
)

client.send_order("AGV_001", order)
```

## 6. Run the Full Example

```bash
python -m vda5050.example
```

## Troubleshooting

If connection fails:

- Confirm the broker is running and reachable.
- Confirm the host and port.
- Check firewall rules.
- Confirm username and password requirements.

If no state messages arrive:

- Confirm the AGV publishes to the expected topic.
- Confirm manufacturer and serial number match.
- Check the requested QoS level.

If the route is rejected:

- Keep node and edge sequence IDs strictly increasing.
- Increment `orderUpdateId` when replacing an order.
- Ensure each edge references existing start and end nodes.
- Confirm the map ID matches the AGV map.

## Further Reading

- [VDA5050 client documentation](README.md)
- [VDA5050 specification](https://github.com/VDA5050/VDA5050)
