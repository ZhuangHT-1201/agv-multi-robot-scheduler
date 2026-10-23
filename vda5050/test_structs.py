"""VDA5050 structure tests"""

import json
import sys
import os


project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from vda5050.structs import (
    Order, Header, Node, Edge, NodePosition, Action,
    State, AgvPosition, BatteryState, SafetyState,
    to_dict, from_json
)


def test_order_serialization():
    """Test order serialization"""
    print("=" * 60)
    print("Order serialization test")
    print("=" * 60)


    order = Order(
        header=Header.create("TestManufacturer", "AGV_TEST_001"),
        orderId="TEST_ORDER_001",
        orderUpdateId=0,
        nodes=[
            Node(
                nodeId="node_1",
                sequenceId=0,
                released=True,
                nodePosition=NodePosition(
                    x=0.0,
                    y=0.0,
                    theta=0.0,
                    mapId="test_map"
                ),
                actions=[
                    Action(
                        actionId="action_1",
                        actionType="startCharging",
                        blockingType="HARD",
                        actionDescription="startCharging"
                    )
                ]
            ),
            Node(
                nodeId="node_2",
                sequenceId=2,
                released=True,
                nodePosition=NodePosition(
                    x=10.0,
                    y=5.0,
                    theta=1.57,
                    mapId="test_map"
                ),
                actions=[]
            )
        ],
        edges=[
            Edge(
                edgeId="edge_1",
                sequenceId=1,
                startNodeId="node_1",
                endNodeId="node_2",
                released=True,
                maxSpeed=2.0,
                actions=[]
            )
        ]
    )


    order_dict = to_dict(order)


    order_json = json.dumps(order_dict, indent=2, ensure_ascii=False)
    print("Order JSON:")
    print(order_json)


    order_dict_loaded = json.loads(order_json)
    order_loaded = from_json(order_dict_loaded, Order)


    assert order_loaded.orderId == order.orderId
    assert len(order_loaded.nodes) == 2
    assert len(order_loaded.edges) == 1
    assert order_loaded.nodes[0].nodePosition.x == 0.0

    print("\nOK Order serialization test passed")
    return True


def test_state_deserialization():
    """Test state deserialization"""
    print("\n" + "=" * 60)
    print("State deserialization test")
    print("=" * 60)


    state_json = """
    {
        "header": {
            "headerId": 12345,
            "timestamp": "2024-01-01T12:00:00Z",
            "version": "2.0.0",
            "manufacturer": "TestManufacturer",
            "serialNumber": "AGV_TEST_001"
        },
        "orderId": "TEST_ORDER_001",
        "orderUpdateId": 0,
        "lastNodeId": "node_1",
        "lastNodeSequenceId": 0,
        "nodeStates": [],
        "edgeStates": [],
        "agvPosition": {
            "positionInitialized": true,
            "x": 5.5,
            "y": 2.3,
            "theta": 0.785,
            "mapId": "test_map",
            "localizationScore": 0.95
        },
        "actionStates": [],
        "batteryState": {
            "batteryCharge": 85.5,
            "charging": false,
            "batteryVoltage": 48.2,
            "reach": 12000.0
        },
        "operatingMode": "AUTOMATIC",
        "safetyState": {
            "eStop": "NONE",
            "fieldViolation": false
        },
        "errors": [],
        "information": [],
        "driving": true,
        "paused": false
    }
    """


    state_dict = json.loads(state_json)
    state = from_json(state_dict, State)


    print(f"\nState information:")
    print(f"  Order ID: {state.orderId}")
    print(f"  Last node: {state.lastNodeId}")
    print(f"  Position: ({state.agvPosition.x:.2f}, {state.agvPosition.y:.2f})")
    print(f"  Heading: {state.agvPosition.theta:.2f} rad")
    print(f"  Battery: {state.batteryState.batteryCharge:.1f}%")
    print(f"  Battery voltage: {state.batteryState.batteryVoltage:.1f}V")
    print(f"  Driving: {state.driving}")
    print(f"  Operating mode: {state.operatingMode}")
    print(f"  Emergency stop: {state.safetyState.eStop}")

    assert state.orderId == "TEST_ORDER_001"
    assert state.agvPosition.x == 5.5
    assert state.batteryState.batteryCharge == 85.5
    assert state.driving == True

    print("\nOK State deserialization test passed")
    return True


def test_optional_fields():
    """Test optional field handling"""
    print("\n" + "=" * 60)
    print("Test optional fields")
    print("=" * 60)


    node = Node(
        nodeId="test_node",
        sequenceId=0,
        released=True,
        actions=[]
    )


    node_dict = to_dict(node)

    print("Node dictionary (no None values expected):")
    print(json.dumps(node_dict, indent=2))


    assert "description" not in node_dict
    assert "nodePosition" not in node_dict

    print("\nOK Optional field test passed")
    return True


def main():
    """Run all tests"""
    print("\n" + "" * 30)
    print("VDA5050 structure tests")
    print("" * 30 + "\n")

    try:
        test_order_serialization()
        test_state_deserialization()
        test_optional_fields()

        print("\n" + "=" * 60)
        print("OK All tests passed")
        print("=" * 60 + "\n")

    except Exception as e:
        print(f"\nFAIL Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
