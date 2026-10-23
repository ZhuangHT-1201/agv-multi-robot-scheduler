# VDA5050 Python Client

A compact Python implementation of the VDA5050 order and state model with an
MQTT client for AGV communication.

This module is optional. The simulator can run entirely offline without an MQTT
broker.

## Features

- Dataclasses for orders, states, nodes, edges, actions, errors, and related
  protocol messages.
- JSON serialization and deserialization helpers.
- MQTT order publishing.
- AGV state and connection subscriptions.
- Instant-action support.
- Thread-safe callback dispatch.

## Install

```bash
python -m pip install -r requirements.txt
```

## Configuration

The repository uses these environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `VDA5050_MQTT_BROKER` | `127.0.0.1` | MQTT broker host |
| `VDA5050_MQTT_PORT` | `1883` | MQTT broker port |
| `VDA5050_MANUFACTURER` | `agv-demo` | Manufacturer identifier |

The Python client also accepts a username and password at construction time.
Load those values from a secret manager or untracked environment file.

## Basic Usage

```python
from vda5050 import VDA5050Client


client = VDA5050Client(
    broker_host="127.0.0.1",
    broker_port=1883,
    manufacturer="agv-demo",
    qos=1,
)

if not client.connect():
    raise RuntimeError("Could not connect to MQTT")


def on_state(state):
    position = state.agvPosition
    battery = state.batteryState.batteryCharge
    print(f"Position=({position.x}, {position.y}) battery={battery}%")


client.subscribe_to_agv_state("AGV_001", on_state)
```

Disconnect when the process exits:

```python
client.disconnect()
```

## Send an Order

```python
from vda5050.structs import Edge, Header, Node, NodePosition, Order


order = Order(
    header=Header.create("agv-demo", "AGV_001"),
    orderId="ORDER_001",
    orderUpdateId=0,
    nodes=[
        Node(
            nodeId="start",
            sequenceId=0,
            released=True,
            nodePosition=NodePosition(
                x=0.0,
                y=0.0,
                theta=0.0,
                mapId="factory_map",
            ),
            actions=[],
        ),
        Node(
            nodeId="goal",
            sequenceId=2,
            released=True,
            nodePosition=NodePosition(
                x=10.0,
                y=5.0,
                theta=1.57,
                mapId="factory_map",
            ),
            actions=[],
        ),
    ],
    edges=[
        Edge(
            edgeId="edge_1",
            sequenceId=1,
            startNodeId="start",
            endNodeId="goal",
            released=True,
            maxSpeed=2.0,
            actions=[],
        )
    ],
)

client.send_order("AGV_001", order)
```

## Send Instant Actions

```python
from vda5050.structs import Action, Header, InstantActions


message = InstantActions(
    header=Header.create("agv-demo", "AGV_001"),
    actions=[
        Action(
            actionId="pause_001",
            actionType="pause",
            blockingType="HARD",
        )
    ],
)

client.send_instant_actions("AGV_001", message)
```

## Topics

VDA5050 topics follow this structure:

```text
{interfaceName}/{majorVersion}/{manufacturer}/{serialNumber}/{topic}
```

Typical topics:

```text
uagv/v2/agv-demo/AGV_001/order
uagv/v2/agv-demo/AGV_001/state
uagv/v2/agv-demo/AGV_001/instantActions
uagv/v2/agv-demo/AGV_001/connection
```

## Protocol Models

- `Order`: the complete route assigned to an AGV.
- `State`: periodic vehicle state from the AGV.
- `Node`: a route node with optional actions.
- `Edge`: a directed route segment with optional speed and actions.
- `Action`: charging, pickup, dropoff, pause, resume, or custom behavior.
- `InstantActions`: actions that are independent of the route order.

## Run the Example

Start an MQTT broker first, then run:

```bash
python -m vda5050.example
```

The example reads `VDA5050_MQTT_BROKER` and defaults to `127.0.0.1`.

## License

MIT. See [LICENSE](LICENSE).
