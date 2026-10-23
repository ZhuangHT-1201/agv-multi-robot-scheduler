#!/usr/bin/env python3
"""Quick ECBS installation and string-scenario diagnostic."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.graph import Graph

print("=== ECBS installation check ===")
try:
    import ecbs_standalone

    print("ecbs_standalone: OK")
    print("  Graph:", hasattr(ecbs_standalone, "Graph"))
    print("  ECBS:", hasattr(ecbs_standalone, "ECBS"))
    print("  Agent:", hasattr(ecbs_standalone, "Agent"))
    cpp_ok = hasattr(ecbs_standalone, "Graph")
except ImportError as e:
    print("ecbs_standalone: MISSING -", e)
    cpp_ok = False

SCEN = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "scen", "string", "scene.json")
with open(SCEN, encoding="utf-8") as f:
    scene = json.load(f)

graph = Graph()
for path in scene.get("paths", []):
    for v in path.get("vertices", []):
        graph.add_vertex(v)
    for e in path.get("edges", []):
        graph.add_edge(e)
graph.compute_adjacency_matrix()

# Approximate initial goals from tasks (pickup vertices as first move target)
tasks = scene["tasks"]
print("\n=== string scene tasks ===")
for t in tasks:
    print(f"  {t['name']}: {t['start_vertex']} -> {t['end_vertex']}")

if not cpp_ok:
    print("\nC++ ECBS not available - install with:")
    print("  pip install pybind11 && pip install -e ecbs_standalone")
    sys.exit(1)

from algorithms.mapf_planner import MapfPathPlanner

planner = MapfPathPlanner(None, {})
planner.graph = graph

ecbs_graph = planner._convert_graph_to_ecbs_standalone(graph)

# Three AGVs near corridor - use nearest-node starts like baseline
agvs = scene["agvs"]
agents = []
for i, agv in enumerate(agvs):
    pos = agv["position"]
    start = planner._find_nearest_node(pos)
    # Use task end vertices as goals (simplified convoy test)
    goal = tasks[i]["end_vertex"]
    agents.append((agv["name"], start, goal))
    print(f"\nAGV {agv['name']}: start={start} goal={goal}")

print("\n=== C++ ECBS joint solve (baseline params) ===")
ecbs_agents = [ecbs_standalone.Agent(i, s, g) for i, (_, s, g) in enumerate(agents)]
t0 = time.time()
solver = ecbs_standalone.ECBS(ecbs_graph, ecbs_agents, sub_optimality=1.1, time_limit=15.0)
ok = solver.solve()
elapsed = (time.time() - t0) * 1000
print(f"  solve={ok}  elapsed={elapsed:.1f}ms")
if ok:
    sol = solver.get_solution()
    for i, (name, _, _) in enumerate(agents):
        path = sol.get(i, [])
        print(f"  {name}: path_len={len(path)}")
