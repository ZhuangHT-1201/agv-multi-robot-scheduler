# AGV Multi-Robot Scheduler

An open-source simulator and scheduling toolkit for coordinating multiple
automated guided vehicles (AGVs) on a shared factory road network.

The project combines task allocation, rolling multi-agent path planning,
collision avoidance, battery simulation, an interactive map editor, and
optional VDA5050/MQTT integration. It is intended for algorithm research,
teaching, integration testing, and factory logistics prototyping.

## Highlights

- Two scheduling strategies selected from the active fleet size.
- C++ ECBS with pybind11 bindings for conflict-free small-fleet planning.
- Time-window A* with reservations for large, congested fleets.
- Rolling base/horizon path issuance compatible with VDA5050 order updates.
- Priority-aware greedy task allocation with estimated pickup and delivery cost.
- Interactive Flask application for scene editing and visual simulation.
- Headless runners for repeatable algorithm tests and throughput benchmarks.
- Docker support for reproducible Linux builds.
- Sample multi-floor factory scenarios.

## Architecture

```text
Browser
   |
   v
Flask API and simulation loop
   |
   +-- TaskAllocator
   |
   +-- EnhancedMapfPlanner
         |
         +-- small fleet: C++ ECBS / rolling MAPF
         +-- large fleet: reservation-based time-window A*
   |
   +-- AGV physics and battery model
   |
   +-- optional VDA5050 MQTT transport
```

The main planning entry point is
`algorithms/enhanced_planner.py::EnhancedMapfPlanner`. The threshold that separates
small-fleet and large-fleet behavior is controlled by
`LARGE_FLEET_THRESHOLD`.

## Requirements

- Python 3.9 through 3.12. Python 3.11 or 3.12 is recommended.
- CMake 3.12 or newer.
- A C++17 compiler.
- Docker is optional.

On Linux, install a compiler and CMake first:

```bash
sudo apt-get update
sudo apt-get install -y build-essential cmake
```

On Windows, install Visual Studio Build Tools with the C++ workload and CMake.

## Quick Start

```bash
python -m venv .venv
```

Activate the environment on Linux or macOS:

```bash
source .venv/bin/activate
```

Activate the environment in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install the project:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e ./ecbs_standalone
```

Start the simulator:

```bash
python app.py
```

Open `http://localhost:5000`, create or load a scene, configure AGVs and tasks,
then start the simulation.

## Docker

Build and run:

```bash
docker build -t agv-multi-robot-scheduler .
docker run --rm -p 5000:5000 agv-multi-robot-scheduler
```

The image compiles the C++ ECBS extension during the build. A C++ toolchain is
therefore required in the Docker build environment.

## Headless Validation

Run the included small-fleet scenarios:

```bash
python algorithms/headless_test.py swap string revert
```

Run one scenario with a custom simulated-time limit:

```bash
python algorithms/headless_test.py swap 600
```

Validate the ECBS Python extension:

```bash
python algorithms/check_ecbs.py
```

For faster debugging, set `HEADLESS_FAST=1`. This flag accelerates exploratory
runs and is not intended to produce stable performance measurements.

## Scene Workflow

1. Select or create a scene from the left panel.
2. Draw a road network with the path tools.
3. Add AGVs and choose their initial positions.
4. Add delivery tasks and priorities, or generate random tasks.
5. Save the scene explicitly.
6. Start, pause, resume, or reset the simulation.

Scene data is stored under `data/scen/<scene-name>/`. A scene can contain
multiple floor maps, each represented by a `map.yaml`, `map.png`, and the shared
`scene.json`.

## Configuration

Environment variables for optional VDA5050 connections:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VDA5050_MQTT_BROKER` | `127.0.0.1` | MQTT broker host |
| `VDA5050_MQTT_PORT` | `1883` | MQTT broker port |
| `VDA5050_MANUFACTURER` | `agv-demo` | VDA5050 manufacturer identifier |

Never commit real broker credentials, private keys, or organization-specific
network addresses.

## Project Layout

```text
.
|-- algorithms/          Scheduling, MAPF, task allocation, headless tests
|-- common/              Graph and shortest-path utilities
|-- data/scen/           Example scenes and map assets
|-- ecbs_standalone/     C++ ECBS library and Python bindings
|-- simulation/          AGV physics and real-AGV adapter
|-- static/              Browser application assets
|-- templates/           Flask HTML template
|-- vda5050/             VDA5050 protocol models and MQTT client
|-- app.py               Flask server and simulation loop
|-- Dockerfile           Container build
|-- LICENSE              GPL-3.0
```

## Planning Behavior

### Small fleets

For up to eight active vehicles, the planner prioritizes global conflict-free
solutions. It uses C++ ECBS when available, falls back to the Python ECBS
implementation, and issues paths in short rolling segments. A per-agent
fallback prevents a single difficult vehicle from blocking every task.

### Large fleets

For larger active fleets, the planner uses time-window A* and vertex/edge
reservations. It supports:

- adaptive search windows;
- soft goals that return the best partial path under congestion;
- request debounce to avoid unstable replanning;
- safe path extension after issued segments are consumed;
- collision-triggered recovery;
- prioritized and batched fallback planning.

The sample large-fleet scene is computationally intensive. Use Docker or Linux
for representative performance measurements.

## Data and Attribution

The simulator is based on the open-source
[`yunjirobot/planning_simulator`](https://github.com/yunjirobot/planning_simulator)
project and includes substantial scheduling changes from this repository.
The original simulator is distributed under GPL-3.0.

The C++ ECBS module is a separate MIT-licensed component. See
`ecbs_standalone/LICENSE`.

Sample scenes are included to make the project reproducible. Review the
provenance and redistribution terms of any third-party scenario data before
publishing or using it commercially. This repository contains no author names,
institutions, credentials, private network addresses, or personal contact
details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please also read
[SECURITY.md](SECURITY.md) before reporting vulnerabilities.

## License

The main simulator and scheduling code are licensed under GPL-3.0. See
[LICENSE](LICENSE). The `ecbs_standalone` component remains under the MIT
license as described in its own license file.
