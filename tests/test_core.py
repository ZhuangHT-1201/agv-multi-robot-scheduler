import json
from pathlib import Path

import pytest

from common.graph import Graph
from vda5050.structs import Header, Node, NodePosition, to_dict


ROOT = Path(__file__).resolve().parents[1]
SCENE_DIR = ROOT / "data" / "scen"


def test_graph_shortest_path():
    graph = Graph()
    graph.add_vertex({"id": "a", "x": 0.0, "y": 0.0})
    graph.add_vertex({"id": "b", "x": 1.0, "y": 0.0})
    graph.add_vertex({"id": "c", "x": 2.0, "y": 0.0})
    graph.add_edge(
        {"id": "ab", "from": "a", "to": "b", "direction": "unidirectional", "cost": 1.0}
    )
    graph.add_edge(
        {"id": "bc", "from": "b", "to": "c", "direction": "unidirectional", "cost": 2.0}
    )

    graph.compute_adjacency_matrix()

    assert graph.get_cost("a", "c") == 3.0
    assert graph.get_cost("c", "a") is None


@pytest.mark.parametrize("scene_path", sorted(SCENE_DIR.glob("*/scene.json")))
def test_scene_references_are_consistent(scene_path):
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    paths = scene.get("paths", [])
    vertices = {
        vertex["id"]
        for path in paths
        for vertex in path.get("vertices", [])
    }

    assert scene["name"] == scene_path.parent.name
    assert paths
    assert scene.get("agvs")
    assert scene.get("tasks")

    for path in paths:
        for edge in path.get("edges", []):
            assert edge["from"] in vertices
            assert edge["to"] in vertices

    for task in scene["tasks"]:
        assert task["start_vertex"] in vertices
        destinations = task.get("end_vertices") or [task.get("end_vertex")]
        assert all(destination in vertices for destination in destinations if destination)


def test_vda5050_node_serialization():
    node = Node(
        nodeId="node-1",
        sequenceId=0,
        released=True,
        nodePosition=NodePosition(x=1.0, y=2.0, theta=0.5, mapId="demo"),
        actions=[],
    )
    payload = to_dict(node)

    assert payload["nodeId"] == "node-1"
    assert payload["nodePosition"]["mapId"] == "demo"
    assert "actions" in payload

    header = Header.create("agv-demo", "AGV_001")
    assert header.manufacturer == "agv-demo"
    assert header.serialNumber == "AGV_001"
