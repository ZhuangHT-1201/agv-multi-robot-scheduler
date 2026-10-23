#!/usr/bin/env python3
"""Headless scenario runner for local validation."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.graph import Graph
from simulation.agv import AGV
from algorithms.threaded_algorithm import ThreadedAlgorithm, PLANNER_ECBS

SCEN_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "scen")
SIM_DT = 0.1
FAST_MODE = os.environ.get("HEADLESS_FAST", "").lower() in ("1", "true", "yes")
MAX_SIM_TIME = {
    "swap": 600.0,
    "string": 600.0,
    "revert": 600.0,
    # Large-fleet tasks span about 50 minutes of simulated time.
    "large_fleet": 14400.0,
}


def load_scene(name):
    path = os.path.join(SCEN_DIR, name, "scene.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_start_time(value):
    if not value:
        return 0.0
    parts = str(value).split(":")
    if len(parts) != 2:
        return 0.0
    return int(parts[0]) * 60 + int(parts[1])


def run_scene(scene_name, max_time=None):
    scene = load_scene(scene_name)
    paths = scene.get("paths", [])
    tasks = scene.get("tasks", [])
    agvs = {a["id"]: AGV(a) for a in scene.get("agvs", [])}
    action_configs = scene.get("actionConfigs", {})
    battery_config = scene.get("batteryConfig", {})

    algo = ThreadedAlgorithm(planner_type=PLANNER_ECBS)
    algo.init_map(paths)

    sim_time = 0.0
    max_time = max_time or MAX_SIM_TIME.get(scene_name, 1200.0)
    submitted = set()
    completed = 0
    total_tasks = len(tasks)

    wall_start = time.time()
    max_wall = max_time  # allow enough real time for background planner threads

    while sim_time < max_time and (time.time() - wall_start) < max_wall:
        for task in tasks:
            if task["id"] in submitted:
                continue
            if task.get("status") not in (None, "pending"):
                submitted.add(task["id"])
                continue
            if sim_time >= parse_start_time(task.get("start_time")):
                task["status"] = "submitted"
                submitted.add(task["id"])

        commands = algo.process(agvs, tasks, sim_time, action_configs)
        for cmd in commands:
            if cmd["type"] == "UPDATE_TASK":
                for t in tasks:
                    if t["id"] == cmd["task_id"]:
                        t.update(cmd.get("updates", {}))
            elif cmd["type"] == "SEND_ORDER":
                agv = agvs.get(cmd["agv_id"])
                if agv:
                    agv.accept_order(cmd["order"])
            elif cmd["type"] == "UPDATE_AGV_TASK_SNAPSHOT":
                agv = agvs.get(cmd["agv_id"])
                if agv:
                    agv.current_task = cmd.get("task_snapshot")
            elif cmd["type"] == "UPDATE_AGV_STATUS":
                agv = agvs.get(cmd["agv_id"])
                if agv:
                    agv.status = cmd.get("status")
                    if cmd.get("clear_paths"):
                        agv.clear_paths_and_reset()

        for agv in agvs.values():
            agv.update_physics(
                SIM_DT, algo.graph, action_configs, sim_time, battery_config, agvs
            )

        completed = sum(1 for t in tasks if t.get("status") == "completed")
        if completed >= total_tasks and total_tasks > 0:
            break

        if scene_name == "large_fleet" and int(sim_time) % 300 == 0 and int(sim_time) > 0:
            if not getattr(run_scene, "_last_progress", None) or run_scene._last_progress != int(sim_time):
                run_scene._last_progress = int(sim_time)
                print(
                    f"  [large_fleet] sim={sim_time:.0f}s completed={completed}/{total_tasks}",
                    flush=True,
                )

        sim_time += SIM_DT
        if FAST_MODE:
            time.sleep(0.01)
        else:
            time.sleep(SIM_DT)

    return {
        "scene": scene_name,
        "sim_time": sim_time,
        "completed": completed,
        "total": total_tasks,
        "success": completed >= total_tasks,
    }


if __name__ == "__main__":
    scenes = sys.argv[1:] or ["swap", "string", "revert"]
    max_time_override = None
    if scenes and scenes[-1].replace(".", "", 1).isdigit():
        max_time_override = float(scenes.pop())
    results = []
    for name in scenes:
        print(f"Running {name}...", flush=True)
        t0 = time.time()
        result = run_scene(name, max_time=max_time_override)
        wall = time.time() - t0
        result["wall_time"] = wall
        results.append(result)
        status = "PASS" if result["success"] else "FAIL"
        print(
            f"  {status}: {result['completed']}/{result['total']} tasks "
            f"in {result['sim_time']:.1f}s sim ({wall:.1f}s wall)"
        )

    if not all(r["success"] for r in results):
        sys.exit(1)
