#!/usr/bin/env python3
"""Docker-equivalent verification via Flask API (swap/string/revert)."""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5000"
SCENES = ("swap", "string", "revert")
MAX_WAIT = {
    "swap": 600,
    "string": 600,
    "revert": 600,
}
POLL = 2.0


def api(method, path, data=None):
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_server(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            api("GET", "/api/scenes")
            return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    return False


def load_and_start(scene):
    api("POST", "/api/simulation/reset", {"clear_all": True})
    loaded = api("GET", f"/api/scenes/{scene}")
    if not loaded.get("success"):
        raise RuntimeError(f"failed to load scene {scene}")
    api("POST", "/api/simulation/reset", {"scene_name": scene})
    api("POST", "/api/simulation/start", {"scene_name": scene, "speed": 2.0})


def scene_progress(scene):
    result = api("GET", f"/api/scenes/{scene}")
    tasks = result.get("scene", {}).get("tasks", [])
    total = len(tasks)
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    return completed, total


def run_scene(scene):
    load_and_start(scene)
    deadline = time.time() + MAX_WAIT[scene]
    while time.time() < deadline:
        completed, total = scene_progress(scene)
        if total > 0 and completed >= total:
            return True, completed, total
        time.sleep(POLL)
    completed, total = scene_progress(scene)
    return completed >= total and total > 0, completed, total


def main():
    scenes = sys.argv[1:] or list(SCENES)
    if not wait_server():
        print("FAIL: Flask server not reachable at", BASE)
        sys.exit(1)

    results = []
    for scene in scenes:
        print(f"Verifying {scene}...", flush=True)
        t0 = time.time()
        ok, completed, total = run_scene(scene)
        wall = time.time() - t0
        status = "PASS" if ok else "FAIL"
        print(f"  {status}: {completed}/{total} tasks ({wall:.1f}s wall)")
        results.append((scene, ok))
        api("POST", "/api/simulation/reset", {"scene_name": scene})

    if all(ok for _, ok in results):
        print("\nAll scenarios PASS")
        sys.exit(0)
    print("\nSome scenarios FAILED")
    sys.exit(1)


if __name__ == "__main__":
    main()
