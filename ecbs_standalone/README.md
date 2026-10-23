# ECBS Standalone

A C++17 implementation of Enhanced Conflict-Based Search (ECBS) with Python
bindings through pybind11.

ECBS is a bounded-suboptimal variant of Conflict-Based Search for multi-agent
path finding. The high-level search selects conflicts and adds constraints;
the low-level search plans paths under those constraints. The implementation
supports vertex conflicts, edge-swap conflicts, and a configurable
sub-optimality factor.

## Features

- Conflict detection for vertex and edge-swap collisions.
- Focal-search high-level search.
- Configurable sub-optimality and wall-clock deadline.
- Python bindings for graphs, agents, solver instances, and result objects.
- Reusable graph and heuristic caches.

## Requirements

- Python 3.9 through 3.12. Python 3.11 or 3.12 is recommended.
- CMake 3.12 or newer.
- A C++17 compiler.

## Install

From the repository root:

```bash
python -m pip install --upgrade pip
python -m pip install "pybind11>=2.11,<3"
python -m pip install -e ./ecbs_standalone
```

## Quick Start

```python
import ecbs_standalone as ecbs

graph = ecbs.Graph()

for y in range(4):
    for x in range(4):
        node_id = f"n_{x}_{y}"
        graph.add_node(node_id, float(x), float(y))

for y in range(4):
    for x in range(4):
        node_id = f"n_{x}_{y}"
        if x < 3:
            graph.add_edge(node_id, f"n_{x + 1}_{y}", 1.0)
        if y < 3:
            graph.add_edge(node_id, f"n_{x}_{y + 1}", 1.0)
        if x > 0:
            graph.add_edge(node_id, f"n_{x - 1}_{y}", 1.0)
        if y > 0:
            graph.add_edge(node_id, f"n_{x}_{y - 1}", 1.0)

agents = [
    ecbs.Agent(0, "n_0_0", "n_3_3"),
    ecbs.Agent(1, "n_3_0", "n_0_3"),
]

result = ecbs.solve_ecbs(
    graph,
    agents,
    sub_optimality=1.1,
    time_limit=5.0,
)

if result.success:
    print("Makespan:", result.makespan)
    print("Sum of costs:", result.soc)
    print("Paths:", result.paths)
else:
    print("No solution:", result.error_message)
```

## Solver API

### Graph

```python
graph = ecbs.Graph()
graph.add_node(node_id: str, x: float, y: float)
graph.add_edge(from_id: str, to_id: str, cost: float = 1.0)
graph.has_node(node_id: str) -> bool
graph.get_cost(from_id: str, to_id: str) -> float
```

### Agent

```python
agent = ecbs.Agent(
    id: int,
    start: str,
    goal: str,
)
```

### ECBS Solver

```python
solver = ecbs.ECBS(
    graph,
    agents,
    sub_optimality=1.1,
    time_limit=5.0,
)

solved = solver.solve()
solution = solver.get_solution()
makespan = solver.get_makespan()
soc = solver.get_soc()
elapsed = solver.get_computation_time()
expanded = solver.get_expanded_nodes()
generated = solver.get_generated_nodes()
```

### Convenience Function

```python
result = ecbs.solve_ecbs(
    graph,
    agents,
    sub_optimality=1.1,
    time_limit=5.0,
)
```

The returned `ECBSResult` exposes:

- `success`
- `paths`
- `makespan`
- `soc`
- `computation_time`
- `error_message`

## Tuning

- `sub_optimality=1.0` requests optimal solutions and is usually slow.
- `sub_optimality=1.1` allows solutions up to 10 percent above optimal.
- Values around `1.5` are faster but may reduce solution quality.
- Set a finite `time_limit` for interactive or real-time applications.

## Validate

```bash
python ecbs_standalone/tests/test_python.py
python algorithms/check_ecbs.py
```

## License

MIT. See [LICENSE](LICENSE).

## Reference

Barer, M., Sharon, G., Stern, R., and Felner, A. (2014). Suboptimal Variants
of the Conflict-Based Search Algorithm for the Multi-Agent Pathfinding Problem.
Proceedings of the Symposium on Combinatorial Search.
