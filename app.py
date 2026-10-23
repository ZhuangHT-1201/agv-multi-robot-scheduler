#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AGV simulator backend service
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import uuid
import re
import random
import threading
import time
import logging
from simulation.agv import AGV
from simulation.real_agv import create_agv, RealAGV
from algorithms.threaded_algorithm import ThreadedAlgorithm


vda5050_client = None
try:
    from vda5050 import VDA5050Client
    from vda5050.structs import to_dict
    VDA5050_AVAILABLE = True
except ImportError:
    VDA5050_AVAILABLE = False
    print("Warning: VDA5050 module unavailable; real AGV mode is disabled")

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)

# Load configuration file.
def load_config():
    config_path = 'config.json'
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:

        return {
            'data': {
                'paths_dir': 'data/paths',
                'maps_dir': 'data/maps',
                'agvs_dir': 'data/agvs'
            },
            'server': {
                'host': '0.0.0.0',
                'port': 5000,
                'debug': False
            }
        }

config = load_config()


SCENE_DIR = config['data'].get('scen_dir', 'data/scen')


os.makedirs(SCENE_DIR, exist_ok=True)


agv_states: Dict[str, Any] = {}

current_scene_name: Optional[str] = None
current_scene_cache: Dict[str, Any] = {}

active_scene_name: Optional[str] = None
simulation_paused: bool = False

DEFAULT_SIM_SPEED = 1.0
MIN_SIM_SPEED = 0.1
MAX_SIM_SPEED = 20.0
SIM_LOOP_INTERVAL = 0.1
current_sim_speed = DEFAULT_SIM_SPEED

simulation_logs: List[Dict[str, Any]] = []


VDA5050_MQTT_BROKER = os.environ.get('VDA5050_MQTT_BROKER', '127.0.0.1')
VDA5050_MQTT_PORT = int(os.environ.get('VDA5050_MQTT_PORT', '1883'))
VDA5050_MANUFACTURER = os.environ.get('VDA5050_MANUFACTURER', 'agv-demo')


def get_cached_scene(scene_name: str) -> Optional[Dict[str, Any]]:
    """Get the cached scene"""
    if not scene_name:
        return None
    if scene_name == current_scene_name:
        return current_scene_cache
    return None


def set_scene_cache(scene_name: str, scene_data: Dict[str, Any]):
    """Update the single-scene cache"""
    global current_scene_name, current_scene_cache
    if not scene_name:
        return
    current_scene_name = scene_name
    current_scene_cache = scene_data


def get_loaded_scene_state(require_paths: bool = False) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Get the active scene and its data"""
    scene_name = current_scene_name
    if not scene_name:
        return None, None
    scene = get_cached_scene(scene_name)
    if scene is None:
        scene = load_scene_data(scene_name, use_cache_if_active=False)
        set_scene_cache(scene_name, scene)
    if require_paths:
        scene.setdefault('paths', [])
    return scene_name, scene


def touch_scene_metadata(scene: Dict[str, Any], scene_name: str):
    """Refresh scene metadata and cache"""
    scene['name'] = scene_name
    scene.setdefault('created_at', datetime.now().isoformat())
    scene['updated_at'] = datetime.now().isoformat()

    set_scene_cache(scene_name, scene)


def parse_positive_float(value, default: float = 1.0) -> float:
    """Parse a positive floating-point value"""
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def parse_sim_time_text(value) -> Optional[float]:
    """Parse MM:SS, HH:MM:SS, or seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    parts = text.split(':')
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return float(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return float(hours) * 3600 + float(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def append_simulation_log(message: str, level: str = 'INFO', source: str = 'Simulation'):
    """Append a simulation log entry."""
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'level': level,
        'message': message,
        'source': source
    }
    simulation_logs.append(log_entry)
    if len(simulation_logs) > 1000:
        simulation_logs.pop(0)


def auto_submit_ready_tasks(scene_data: Dict[str, Any], sim_time: float) -> List[str]:
    """Auto-submit tasks whose start time has arrived."""
    submitted_task_ids = []
    for task in scene_data.get('tasks', []):
        if task.get('status') != 'pending':
            continue

        start_seconds = parse_sim_time_text(task.get('start_time'))
        if start_seconds is None:
            continue
        if start_seconds > sim_time:
            continue

        task['status'] = 'submitted'
        submitted_task_ids.append(task.get('id'))
        append_simulation_log(
            f"Task auto-submitted: {task.get('name') or task.get('id')} (t={sim_time:.1f}s)",
            source='Simulation',
        )

    return submitted_task_ids


def get_scene_sim_speed(scene_name: str = None) -> float:
    """Get the scene simulation speed"""
    if scene_name and active_scene_name and scene_name != active_scene_name:
        return DEFAULT_SIM_SPEED
    return current_sim_speed


def set_scene_sim_speed(scene_name: str, speed: float) -> float:
    """Set and return the effective simulation speed"""
    global current_sim_speed
    if active_scene_name and scene_name and scene_name != active_scene_name:
        return current_sim_speed
    clamped = max(MIN_SIM_SPEED, min(MAX_SIM_SPEED, parse_positive_float(speed, DEFAULT_SIM_SPEED)))
    current_sim_speed = clamped
    return current_sim_speed


def is_simulation_active(scene_name: str = None) -> bool:
    """Check whether simulation is running"""
    if scene_name:
        return active_scene_name == scene_name
    return active_scene_name is not None


def is_simulation_paused(scene_name: str = None) -> bool:
    """Check whether simulation is paused"""
    if scene_name and scene_name != active_scene_name:
        return False
    return simulation_paused


def mark_simulation_active(scene_name: str, scene_state: Dict[str, Any] = None):
    """Mark a scene as running and refresh the cache"""
    global active_scene_name, simulation_paused, current_sim_speed, algorithm
    if not scene_name:
        return
    previously_active = active_scene_name
    active_scene_name = scene_name
    simulation_paused = False

    if algorithm and hasattr(algorithm, 'set_paused'):
        algorithm.set_paused(False)
    if previously_active != scene_name:
        current_sim_speed = DEFAULT_SIM_SPEED
    if scene_state is None:

        cached_scene = get_cached_scene(scene_name)
        if cached_scene is not None:
            scene_state = cached_scene
        else:
            scene_state = load_scene_data(scene_name, use_cache_if_active=False)
            set_scene_cache(scene_name, scene_state)
    else:

        set_scene_cache(scene_name, scene_state)


def update_scene_cache(scene_name: str, scene_data: Dict[str, Any]):
    """Update the cache while simulation is running"""
    if scene_name:
        set_scene_cache(scene_name, scene_data)


current_sim_time = 0.0

def run_simulation_loop():
    """Simulation loop"""
    global algorithm, current_sim_time
    loop_scene_name = None
    print("Simulation loop started")
    last_tick_time = time.perf_counter()
    current_sim_time = 0.0

    while True:
        try:
            active_scene = active_scene_name

            if not active_scene:
                if loop_scene_name:
                    if algorithm: algorithm.reset()
                    loop_scene_name = None
                    current_sim_time = 0.0
                time.sleep(0.5)
                last_tick_time = time.perf_counter()
                continue


            if loop_scene_name != active_scene:
                loop_scene_name = active_scene
                if algorithm:
                    algorithm.reset()
                    # Load map and init graph
                    scene_data = load_scene_data(active_scene)
                    paths = scene_data.get('paths', [])
                    algorithm.init_map(paths)
                    print(f"Scheduler loaded scene: {active_scene}")
                    current_sim_time = 0.0

            if not algorithm:
                time.sleep(1)
                last_tick_time = time.perf_counter()
                continue

            # Check if paused and sync with algorithm threads
            is_paused = is_simulation_paused(active_scene)
            if hasattr(algorithm, 'set_paused'):
                algorithm.set_paused(is_paused)

            if is_paused:
                time.sleep(0.5)
                last_tick_time = time.perf_counter()
                continue



            scene_data = load_scene_data(active_scene)
            tasks = scene_data.get('tasks', [])
            action_configs = scene_data.get('actionConfigs', {})
            battery_config = scene_data.get('batteryConfig', {
                'chargeRate': 1.0,
                'idleConsumption': 0.1,
                'workingConsumption': 0.5
            })


            loop_start = time.perf_counter()
            real_dt = loop_start - last_tick_time
            if real_dt <= 0:
                real_dt = SIM_LOOP_INTERVAL
            last_tick_time = loop_start
            sim_speed = get_scene_sim_speed(active_scene)
            dt = real_dt * sim_speed
            current_sim_time += dt


            submitted_task_ids = auto_submit_ready_tasks(scene_data, current_sim_time)
            updated_task_ids = set(submitted_task_ids)


            # agv_states is Dict[str, AGV]
            commands = algorithm.process(agv_states, tasks, current_sim_time, action_configs)

            updated_agv_ids = set()

            # Apply commands
            for cmd in commands:
                cmd_type = cmd.get('type')

                if cmd_type == 'UPDATE_TASK':
                    task_id = cmd.get('task_id')
                    updates = cmd.get('updates', {})
                    for t in tasks:
                        if t['id'] == task_id:
                            t.update(updates)
                            updated_task_ids.add(task_id)
                            break

                elif cmd_type == 'SEND_ORDER':
                    agv_id = cmd.get('agv_id')
                    order_data = cmd.get('order')
                    if agv_id in agv_states:
                        agv = agv_states[agv_id]

                        if agv.accept_order(order_data):
                            updated_agv_ids.add(agv_id)

                elif cmd_type == 'UPDATE_AGV_TASK_SNAPSHOT':
                    agv_id = cmd.get('agv_id')
                    snapshot = cmd.get('task_snapshot')
                    if agv_id in agv_states:
                        agv_states[agv_id].current_task = snapshot
                        updated_agv_ids.add(agv_id)

                elif cmd_type == 'UPDATE_AGV_STATUS':
                    agv_id = cmd.get('agv_id')
                    status = cmd.get('status')
                    clear_paths = cmd.get('clear_paths', False)
                    if agv_id in agv_states:
                        agv = agv_states[agv_id]
                        agv.status = status
                        if clear_paths:
                            agv.clear_paths_and_reset()
                        updated_agv_ids.add(agv_id)


            has_physics_updates = False
            for agv in agv_states.values():


                if not isinstance(agv, RealAGV):
                    if agv.update_physics(dt, algorithm.graph, action_configs, current_sim_time, battery_config, agv_states):
                        updated_agv_ids.add(agv.id)
                        has_physics_updates = True


            if updated_task_ids or updated_agv_ids or has_physics_updates:



                scene_agvs_map = {a['id']: a for a in scene_data.get('agvs', [])}
                for agv_id in updated_agv_ids:
                    if agv_id in agv_states:
                        # update dict in scene_data
                        agv_obj = agv_states[agv_id]
                        if agv_id in scene_agvs_map:
                            scene_agvs_map[agv_id].update(agv_obj.to_dict())
                        else:

                            pass

                update_scene_cache(active_scene, scene_data)

            elapsed = time.perf_counter() - loop_start
            sleep_time = max(0.0, SIM_LOOP_INTERVAL - elapsed)
            time.sleep(sleep_time)

        except Exception as e:
            print(f"Simulation Loop Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(1)

def _on_agv_state_update(agv_id: str, state):
    """Handle AGV state updates from MQTT"""
    if agv_id in agv_states:
        agv = agv_states[agv_id]
        if isinstance(agv, RealAGV):
            agv.update_from_state(state)

            global updated_agv_ids
            updated_agv_ids = updated_agv_ids if 'updated_agv_ids' in globals() else set()
            updated_agv_ids.add(agv_id)


def init_vda5050_client(broker_host: str = None, broker_port: int = None, manufacturer: str = None) -> bool:
    """Initialize the VDA5050 MQTT client"""
    global vda5050_client

    if not VDA5050_AVAILABLE:
        print("Warning: VDA5050 module unavailable; cannot initialize MQTT")
        return False


    if vda5050_client is not None:
        if vda5050_client.is_connected:
            print("Existing MQTT connection found; disconnecting first...")
            vda5050_client.disconnect()
        vda5050_client = None

    try:
        broker_host = broker_host or VDA5050_MQTT_BROKER
        broker_port = broker_port or VDA5050_MQTT_PORT
        manufacturer = manufacturer or VDA5050_MANUFACTURER


        vda5050_client = VDA5050Client(
            broker_host=broker_host,
            broker_port=broker_port,
            manufacturer=manufacturer,
            qos=0
        )

        if vda5050_client.connect():
            print(f"VDA5050 MQTT client connected to {broker_host}:{broker_port}")

            return True
        else:
            print(f"Warning: Cannot connect to VDA5050 MQTT broker {broker_host}:{broker_port}")
            return False

    except Exception as e:
        print(f"Error: Failed to initialize VDA5050 MQTT client: {e}")
        import traceback
        traceback.print_exc()
        return False


def sync_agv_state_from_scene(scene_data: Dict[str, Any]):
    """Synchronize scene AGVs into memory"""
    if not scene_data or 'agvs' not in scene_data:
        return


    for agv_data in scene_data.get('agvs', []):
        agv_id = agv_data.get('id')
        if not agv_id:
            continue

        if agv_id not in agv_states:


            if 'name' not in agv_data: agv_data['name'] = f'AGV_{agv_id[:8]}'
            if 'position' not in agv_data: agv_data['position'] = {'x': 0, 'y': 0, 'z': 0}

            agv_states[agv_id] = create_agv(agv_id, agv_data, vda5050_client, _on_agv_state_update)

def normalize_agv_current_task(agv: Any):
    """Ensure the AGV current_task includes the task name"""



    pass

def sanitize_filename(value: str, default: str = 'agv') -> str:
    if not value:
        return default
    safe = "".join(c for c in value if c.isalnum() or c in (' ', '-', '_')).strip()
    safe = safe.replace(' ', '_')
    return safe or default


def persist_agv_config(agv: Any, skip_if_simulating: bool = True):
    """Compatibility placeholder: AGV configuration is kept in the scene cache"""
    return


def get_scene_directory(name: str) -> str:
    safe_name = sanitize_filename(name, 'scene')
    directory = os.path.join(SCENE_DIR, safe_name)
    os.makedirs(directory, exist_ok=True)
    return directory


def get_scene_file(name: str) -> str:
    return os.path.join(get_scene_directory(name), 'scene.json')


def load_scene_data(name: str, use_cache_if_active: bool = True) -> Dict[str, Any]:
    """Load a scene file, preferring the cache while running"""

    cached_scene = get_cached_scene(name)
    if use_cache_if_active and is_simulation_active(name) and cached_scene is not None:
        return cached_scene


    scene_file = get_scene_file(name)
    if os.path.exists(scene_file):
        with open(scene_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    else:
        data = {
            'name': name,
            'paths': [],
            'agvs': [],
            'tasks': [],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
    data.setdefault('paths', [])
    data.setdefault('agvs', [])
    data.setdefault('tasks', [])
    data.setdefault('name', name)
    data.setdefault('created_at', datetime.now().isoformat())
    data.setdefault('updated_at', datetime.now().isoformat())


    for agv in data.get('agvs', []):
        if isinstance(agv, dict):
            agv.setdefault('max_speed', 1.0)


    if use_cache_if_active and is_simulation_active(name):
        set_scene_cache(name, data)

    return data


def save_scene_data(name: str, scene: Dict[str, Any], skip_if_simulating: bool = True, force_save: bool = False) -> Dict[str, Any]:
    """Save scene data

    Args:
        name: Scene name
        scene: Scene data
        skip_if_simulating: Skip saving while simulation is running.
        force_save: Force the scene to be written to disk.

    Returns:
        Scene data
    """

    if skip_if_simulating and is_simulation_active(name):
        scene['name'] = name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        set_scene_cache(name, scene)
        return scene


    if not force_save:

        scene['name'] = name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        if is_simulation_active(name):
            set_scene_cache(name, scene)
        return scene


    scene_file = get_scene_file(name)
    scene['name'] = name
    scene.setdefault('created_at', datetime.now().isoformat())
    scene['updated_at'] = datetime.now().isoformat()
    with open(scene_file, 'w', encoding='utf-8') as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)


    if is_simulation_active(name):
        set_scene_cache(name, scene)

    return scene


def list_scenes() -> List[Dict[str, Any]]:
    scenes = []
    for entry in sorted(os.listdir(SCENE_DIR)):
        scene_dir = os.path.join(SCENE_DIR, entry)
        if not os.path.isdir(scene_dir):
            continue
        scene_file = os.path.join(scene_dir, 'scene.json')
        if os.path.exists(scene_file):
            try:
                with open(scene_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                scenes.append({
                    'name': data.get('name', entry),
                    'path_count': len(data.get('paths', [])),
                    'agv_count': len(data.get('agvs', [])),
                    'task_count': len(data.get('tasks', [])),
                    'updated_at': data.get('updated_at'),
                    'created_at': data.get('created_at')
                })
            except Exception:
                continue
    return scenes


def parse_map_yaml(filepath):
    """Parse Simple Map YAML"""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            # Simple regex parsing
            res_match = re.search(r'resolution:\s*([\d\.]+)', content)
            resolution = float(res_match.group(1)) if res_match else 0.05

            # Origin parsing
            origin_vals = re.findall(r'-\s*([-\d\.]+)', content)
            if len(origin_vals) >= 3:
                origin = {'x': float(origin_vals[0]), 'y': float(origin_vals[1]), 'z': float(origin_vals[2])}
            else:
                origin = {'x': 0, 'y': 0, 'z': 0}

            return {'resolution': resolution, 'origin': origin}
    except:
        return {'resolution': 0.05, 'origin': {'x': 0, 'y': 0, 'z': 0}}



@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')


@app.route('/api/app/state', methods=['GET'])
def get_app_state():
    """Get application state"""
    try:
        active_scene = active_scene_name
        is_running = active_scene is not None
        is_paused = is_simulation_paused()
        speed = get_scene_sim_speed(active_scene) if active_scene else DEFAULT_SIM_SPEED

        return jsonify({
            'success': True,
            'state': {
                'active_scene': active_scene,
                'is_simulation_running': is_running,
                'is_simulation_paused': is_paused,
                'simulation_speed': speed,
                'current_sim_time': current_sim_time
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get configuration"""
    return jsonify({
        'success': True,
        'config': {
            'map': config.get('map', {}),
            'data': config.get('data', {})
        }
    })


@app.route('/api/paths', methods=['GET'])
def get_paths():
    """Get all paths"""
    try:
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400
        return jsonify({'success': True, 'scene_name': scene_name, 'paths': scene.get('paths', [])})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/paths/<path_id>', methods=['GET'])
def get_path(path_id):
    """Get a path"""
    try:
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400
        for path in scene.get('paths', []):
            if path.get('id') == path_id:
                return jsonify({'success': True, 'path': path, 'scene_name': scene_name})
        return jsonify({'success': False, 'error': 'Path not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/paths', methods=['POST'])
def save_path():
    """save the path"""
    try:
        data = request.json or {}
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400


        if 'vertices' not in data or 'edges' not in data:
            return jsonify({'success': False, 'error': 'Required field is missing'}), 400


        name = data.get('name', f'path_{datetime.now().strftime("%Y%m%d_%H%M%S")}')

        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        if not safe_name:
            safe_name = f'path_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

        path_id = data.get('id') or safe_name


        path_data = {
            'id': path_id,
            'name': name,
            'floor': data.get('floor', 0),
            'vertices': data['vertices'],
            'edges': data['edges'],
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }

        paths = [p for p in scene.get('paths', []) if p.get('id') != path_id]
        paths.append(path_data)
        scene['paths'] = paths
        touch_scene_metadata(scene, scene_name)

        return jsonify({'success': True, 'path_id': path_id, 'path': path_data, 'scene_name': scene_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/paths/<path_id>', methods=['PUT'])
def update_path(path_id):
    """Update a path"""
    try:
        data = request.json or {}
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400

        target = None
        for path in scene.get('paths', []):
            if path.get('id') == path_id:
                target = path
                break
        if not target:
            return jsonify({'success': False, 'error': 'Path not found'}), 404

        target.update({
            'name': data.get('name', target.get('name')),
            'floor': data.get('floor', target.get('floor')),
            'vertices': data.get('vertices', target.get('vertices')),
            'edges': data.get('edges', target.get('edges')),
            'updated_at': datetime.now().isoformat()
        })

        touch_scene_metadata(scene, scene_name)

        return jsonify({'success': True, 'path': target, 'scene_name': scene_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/paths/<path_id>', methods=['DELETE'])
def delete_path(path_id):
    """Delete a path"""
    try:
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400

        original_len = len(scene.get('paths', []))
        scene['paths'] = [p for p in scene.get('paths', []) if p.get('id') != path_id]
        if len(scene['paths']) == original_len:
            return jsonify({'success': False, 'error': 'Path not found'}), 404

        touch_scene_metadata(scene, scene_name)
        return jsonify({'success': True, 'scene_name': scene_name})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/vertices/<vertex_id>', methods=['PUT'])
def update_vertex_global(vertex_id):
    """Update a vertex across all paths"""
    try:
        data = request.json or {}
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400
        updated_paths = []

        for path in scene.get('paths', []):
            updated = False
            for vertex in path.get('vertices', []):
                if vertex.get('id') == vertex_id:
                    if 'x' in data:
                        vertex['x'] = data['x']
                    if 'y' in data:
                        vertex['y'] = data['y']
                    if 'z' in data:
                        vertex['z'] = data['z']
                    if 'type' in data:
                        vertex['type'] = data['type']
                    if 'action' in data:
                        vertex['action'] = data['action']
                    if 'properties' in data:
                        vertex['properties'] = data['properties']
                    updated = True
                    break
            if updated:
                path['updated_at'] = datetime.now().isoformat()
                updated_paths.append(path.get('id'))

        if updated_paths:
            touch_scene_metadata(scene, scene_name)

        return jsonify({
            'success': True,
            'updated_paths': updated_paths,
            'scene_name': scene_name,
            'message': f'Updated vertex {vertex_id} in {len(updated_paths)} paths'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/edges/<edge_id>', methods=['PUT'])
def update_edge_global(edge_id):
    """Update an edge across all paths"""
    try:
        data = request.json or {}
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400
        updated_paths = []

        for path in scene.get('paths', []):
            updated = False
            for edge in path.get('edges', []):
                if edge.get('id') == edge_id:
                    for key in ['direction', 'length', 'cost', 'max_speed', 'width', 'action']:
                        if key in data:
                            edge[key] = data[key]
                    updated = True
                    break
            if updated:
                path['updated_at'] = datetime.now().isoformat()
                updated_paths.append(path.get('id'))

        if updated_paths:
            touch_scene_metadata(scene, scene_name)

        return jsonify({
            'success': True,
            'updated_paths': updated_paths,
            'scene_name': scene_name,
            'message': f'Updated edge {edge_id} in {len(updated_paths)} paths'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/vertices/<vertex_id>', methods=['DELETE'])
def delete_vertex_global(vertex_id):
    """Delete a vertex from all paths"""
    try:
        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400
        updated_paths = []

        for path in scene.get('paths', []):
            original_vertex_count = len(path.get('vertices', []))
            path['vertices'] = [v for v in path.get('vertices', []) if v.get('id') != vertex_id]

            original_edge_count = len(path.get('edges', []))
            path['edges'] = [
                e for e in path.get('edges', [])
                if e.get('from') != vertex_id and e.get('to') != vertex_id
            ]

            if len(path['vertices']) < original_vertex_count or len(path['edges']) < original_edge_count:
                path['updated_at'] = datetime.now().isoformat()
                updated_paths.append(path.get('id'))

        if updated_paths:
            touch_scene_metadata(scene, scene_name)

        return jsonify({
            'success': True,
            'updated_paths': updated_paths,
            'scene_name': scene_name,
            'message': f'Removed vertex {vertex_id} from {len(updated_paths)} paths'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/vertices/insert', methods=['POST'])
def insert_vertex_in_edge():
    """Insert a vertex on an edge"""
    try:
        data = request.json or {}
        edge_id = data.get('edge_id')
        vertex_data = data.get('vertex')
        path_id = data.get('path_id')

        if not edge_id or not vertex_data or not path_id:
            return jsonify({'success': False, 'error': 'Required parameter is missing'}), 400

        scene_name, scene = get_loaded_scene_state(require_paths=True)
        if not scene_name or scene is None:
            return jsonify({'success': False, 'error': 'No active scene'}), 400

        path_data = None
        for path in scene.get('paths', []):
            if path.get('id') == path_id:
                path_data = path
                break
        if not path_data:
            return jsonify({'success': False, 'error': 'Path not found'}), 404

        edge = None
        edge_index = -1
        for i, e in enumerate(path_data.get('edges', [])):
            if e.get('id') == edge_id:
                edge = e
                edge_index = i
                break

        if not edge:
            return jsonify({'success': False, 'error': 'Edge not found'}), 404

        path_data.setdefault('vertices', []).append(vertex_data)

        import time
        timestamp = int(time.time() * 1000)
        new_edge1_id = f"E{timestamp}{hash(edge['id']) % 1000}"
        new_edge2_id = f"E{timestamp + 1}{hash(edge['id']) % 1000}"


        new_edge1 = {
            'id': new_edge1_id,
            'from': edge['from'],
            'to': vertex_data['id'],
            'direction': edge.get('direction', 'bidirectional'),
            'length': data.get('length1', 0),
            'cost': data.get('cost1', 0),
            'max_speed': edge.get('max_speed', 1.5),
            'width': edge.get('width', 0.6),
            'action': edge.get('action')
        }

        new_edge2 = {
            'id': new_edge2_id,
            'from': vertex_data['id'],
            'to': edge['to'],
            'direction': edge.get('direction', 'bidirectional'),
            'length': data.get('length2', 0),
            'cost': data.get('cost2', 0),
            'max_speed': edge.get('max_speed', 1.5),
            'width': edge.get('width', 0.6),
            'action': edge.get('action')
        }


        path_edges = path_data.setdefault('edges', [])
        path_edges[edge_index] = new_edge1
        path_edges.insert(edge_index + 1, new_edge2)

        path_data['updated_at'] = datetime.now().isoformat()
        touch_scene_metadata(scene, scene_name)

        return jsonify({
            'success': True,
            'path': path_data,
            'scene_name': scene_name,
            'message': f'Inserted vertex into edge {edge_id}: vertex {vertex_data["id"]}'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agvs', methods=['GET'])
def get_agvs():
    """Get all AGV states"""
    agv_list = []
    for agv in agv_states.values():
        # normalize_agv_current_task is handled inside AGV object logic mostly,
        # or we can check it before serialization if needed.
        # But better: relying on AGV.to_dict()
        agv_list.append(agv.to_dict())
    return jsonify({'success': True, 'agvs': agv_list})


@app.route('/api/agvs/<agv_id>', methods=['GET'])
def get_agv(agv_id):
    """Get an AGV state"""
    if agv_id not in agv_states:
        return jsonify({'success': False, 'error': 'AGV not found'}), 404
    agv = agv_states[agv_id]
    return jsonify({'success': True, 'agv': agv.to_dict()})


@app.route('/api/agvs', methods=['POST'])
def create_agv_api():
    """Create an AGV"""
    try:
        data = request.json
        agv_id = data.get('id') or str(uuid.uuid4())

        default_length = 0.7
        default_width = 0.5
        length = float(data.get('length', data.get('dimensions', {}).get('length', default_length)) if isinstance(data.get('dimensions', {}), dict) else data.get('length', default_length))
        width = float(data.get('width', data.get('dimensions', {}).get('width', default_width)) if isinstance(data.get('dimensions', {}), dict) else data.get('width', default_width))
        max_speed = parse_positive_float(data.get('max_speed'), 1.0)
        dimensions = {
            'length': length,
            'width': width
        }

        agv_data = {
            'id': agv_id,
            'name': data.get('name', f'AGV_{agv_id[:8]}'),
            'position': data.get('position', {'x': 0, 'y': 0, 'z': 0}),
            'orientation': data.get('orientation', 0),
            'status': data.get('status', 'idle'),  # idle, moving, charging, error
            'battery': data.get('battery', 100),
            'current_path': data.get('current_path'),
            'current_task': data.get('current_task'),
            'length': length,
            'width': width,
            'dimensions': dimensions,
            'max_speed': max_speed,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }


        if 'battery_config' in data and data['battery_config'] is not None:
            agv_data['battery_config'] = data['battery_config']

        agv_states[agv_id] = create_agv(agv_id, agv_data, vda5050_client, _on_agv_state_update)


        scene_name = current_scene_name
        if scene_name:
            cached_scene = get_cached_scene(scene_name)
            if cached_scene is not None:
                scene_agvs = cached_scene.get('agvs', [])

                agv_exists = False
                for scene_agv in scene_agvs:
                    if scene_agv.get('id') == agv_id:
                        scene_agv.update(agv_states[agv_id].to_dict())
                        agv_exists = True
                        break
                if not agv_exists:
                    scene_agvs.append(agv_states[agv_id].to_dict())
                cached_scene['agvs'] = scene_agvs
                touch_scene_metadata(cached_scene, scene_name)

        persist_agv_config(agv_states[agv_id])

        return jsonify({'success': True, 'agv': agv_states[agv_id].to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agvs/<agv_id>', methods=['PUT'])
def update_agv(agv_id):
    """Update an AGV"""
    try:
        if agv_id not in agv_states:
            return jsonify({'success': False, 'error': 'AGV not found'}), 404

        data = request.json
        agv = agv_states[agv_id]


        if 'position' in data:
            agv.position = data['position']
        if 'orientation' in data:
            agv.orientation = data['orientation']
        if 'status' in data:
            agv.status = data['status']
        if 'battery' in data:
            agv.battery = data['battery']
        if 'current_path' in data:
            agv.current_path = data['current_path']
        if 'current_task' in data:
            agv.current_task = data['current_task']
        if 'name' in data:
            agv.name = data['name']
        if 'max_speed' in data:
            agv.max_speed = parse_positive_float(data['max_speed'], agv.max_speed)

        length = data.get('length')
        width = data.get('width')
        if isinstance(data.get('dimensions'), dict):
            length = data['dimensions'].get('length', length)
            width = data['dimensions'].get('width', width)

        if length is not None:
            agv.length = float(length)
        if width is not None:
            agv.width = float(width)
        if length is not None or width is not None:
            agv.dimensions = {
                'length': agv.length,
                'width': agv.width
            }


        if 'battery_config' in data:
            battery_config_data = data['battery_config']

            if battery_config_data is None or (isinstance(battery_config_data, dict) and not battery_config_data):
                agv.battery_config = None
            elif isinstance(battery_config_data, dict):

                agv.battery_config = {
                    'chargeRate': float(battery_config_data.get('chargeRate', 1.0)),
                    'idleConsumption': float(battery_config_data.get('idleConsumption', 0.1)),
                    'workingConsumption': float(battery_config_data.get('workingConsumption', 0.5))
                }

        agv.updated_at = datetime.now().isoformat()


        scene_name = current_scene_name
        if scene_name:
            cached_scene = get_cached_scene(scene_name)
            if cached_scene is not None:

                scene_agvs = cached_scene.get('agvs', [])
                agv_updated = False
                for scene_agv in scene_agvs:
                    if scene_agv.get('id') == agv_id:
                        scene_agv.update(agv.to_dict())
                        agv_updated = True
                        break
                if not agv_updated:

                    scene_agvs.append(agv.to_dict())
                cached_scene['agvs'] = scene_agvs
                touch_scene_metadata(cached_scene, scene_name)


        # persist_agv_config(agv)

        return jsonify({'success': True, 'agv': agv.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/agvs/<agv_id>', methods=['DELETE'])
def delete_agv(agv_id):
    """Delete an AGV"""
    if agv_id not in agv_states:
        return jsonify({'success': False, 'error': 'AGV not found'}), 404

    del agv_states[agv_id]


    scene_name = current_scene_name
    if scene_name:
        cached_scene = get_cached_scene(scene_name)
        if cached_scene is not None:
            scene_agvs = cached_scene.get('agvs', [])
            cached_scene['agvs'] = [a for a in scene_agvs if a.get('id') != agv_id]
            touch_scene_metadata(cached_scene, scene_name)

    return jsonify({'success': True})


@app.route('/api/scenes', methods=['GET'])
def get_scenes():
    """List scenes"""
    return jsonify({'success': True, 'scenes': list_scenes()})


@app.route('/api/scenes', methods=['POST'])
def create_or_update_scene():
    """Create or replace a scene without saving automatically"""
    try:
        data = request.json or {}
        name = data.get('name')
        if not name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400


        if is_simulation_active(name):
            return jsonify({'success': False, 'error': 'Cannot modify a running scene'}), 400

        scene = load_scene_data(name, use_cache_if_active=False)
        if 'paths' in data:
            scene['paths'] = data['paths']
        if 'agvs' in data:
            scene['agvs'] = data['agvs']
        if 'tasks' in data:
            scene['tasks'] = data['tasks']
        if 'actionConfigs' in data:
            scene['actionConfigs'] = data['actionConfigs']
        if 'batteryConfig' in data:
            scene['batteryConfig'] = data['batteryConfig']

        scene['name'] = name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        set_scene_cache(name, scene)
        return jsonify({'success': True, 'scene': scene, 'message': 'Scene updated in memory. Click Save scene to persist it.'})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/scenes/<scene_name>', methods=['GET'])
def get_scene(scene_name):
    """Get a scene"""
    try:
        cached_scene = get_cached_scene(scene_name)

        if cached_scene is not None:
            scene = cached_scene
        else:
            scene = load_scene_data(scene_name, use_cache_if_active=False)
            if not is_simulation_active(scene_name):
                sync_agv_state_from_scene(scene)
            set_scene_cache(scene_name, scene)
        return jsonify({'success': True, 'scene': scene})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/scenes/<scene_name>', methods=['PUT'])
def update_scene(scene_name):
    """Update scene data without saving automatically"""
    try:

        if is_simulation_active(scene_name):
            return jsonify({'success': False, 'error': 'Cannot modify a running scene'}), 400

        data = request.json or {}
        cached_scene = get_cached_scene(scene_name)
        if cached_scene is not None:
            scene = cached_scene.copy()
        else:
            scene = load_scene_data(scene_name, use_cache_if_active=False)

        if 'paths' in data:
            scene['paths'] = data['paths']
        if 'agvs' in data:
            scene['agvs'] = data['agvs']
        if 'tasks' in data:
            scene['tasks'] = data['tasks']
        if 'actionConfigs' in data:
            scene['actionConfigs'] = data['actionConfigs']
        if 'batteryConfig' in data:
            scene['batteryConfig'] = data['batteryConfig']

        scene['name'] = scene_name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        set_scene_cache(scene_name, scene)
        return jsonify({'success': True, 'scene': scene, 'message': 'Scene updated in memory. Click Save scene to persist it.'})
    except Exception as exc:
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/scenes/<scene_name>/maps', methods=['GET'])
def get_scene_maps(scene_name):
    """Get scene map configuration"""
    try:
        scene_dir = get_scene_directory(scene_name)
        maps = {}
        if os.path.exists(scene_dir):
            for entry in os.listdir(scene_dir):
                subdir = os.path.join(scene_dir, entry)
                if os.path.isdir(subdir):
                    map_yaml = os.path.join(subdir, 'map.yaml')
                    map_png = os.path.join(subdir, 'map.png')
                    if os.path.exists(map_yaml) and os.path.exists(map_png):
                        info = parse_map_yaml(map_yaml)
                        maps[entry] = {
                            'image': f'/api/scenes/{scene_name}/assets/{entry}/map.png',
                            'origin': info['origin'],
                            'resolution': info['resolution'],
                            'floor': entry
                        }
        return jsonify({'success': True, 'maps': maps})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scenes/<scene_name>/assets/<path:filename>')
def serve_scene_asset(scene_name, filename):
    """Serve scene assets"""
    scene_dir = get_scene_directory(scene_name)
    return send_from_directory(scene_dir, filename)


@app.route('/api/scenes/<scene_name>/tasks/generate', methods=['POST'])
def generate_tasks(scene_name):
    """Generate random tasks"""
    try:
        data = request.json
        count = int(data.get('count', 5))
        duration = float(data.get('duration', 10)) # minutes


        priority_dist = data.get('priority_distribution', {})
        priority_low = priority_dist.get('low', 33)
        priority_medium = priority_dist.get('medium', 34)
        priority_high = priority_dist.get('high', 33)


        if priority_low + priority_medium + priority_high != 100:

            priority_dist = None


        end_count_range = data.get('end_vertex_count_range', {})
        end_min = max(0, min(5, int(end_count_range.get('min', 1))))
        end_max = max(end_min, min(5, int(end_count_range.get('max', end_min))))


        cached_scene = get_cached_scene(scene_name)
        if cached_scene is not None:
            scene = cached_scene
        else:
            scene = load_scene_data(scene_name, use_cache_if_active=False)

            set_scene_cache(scene_name, scene)
        paths = scene.get('paths', [])


        all_vertices = []
        for path in paths:
            all_vertices.extend(path.get('vertices', []))

        if len(all_vertices) < 1:
            return jsonify({'success': False, 'error': 'At least one map node is required to generate tasks'}), 400

        new_tasks = []
        existing_count = len(scene.get('tasks', []))


        deadline_range = data.get('deadline_range', {})
        deadline_min = deadline_range.get('min', 0)
        deadline_max = deadline_range.get('max', 0)
        use_deadline = deadline_min > 0 and deadline_max > 0 and deadline_min <= deadline_max

        for i in range(count):

            start_offset = random.uniform(0, duration * 60)

            start_time_str = f"{int(start_offset // 60):02d}:{int(start_offset % 60):02d}"


            deadline_str = ''
            if use_deadline:

                deadline_offset_minutes = random.uniform(deadline_min, deadline_max)
                deadline_total_seconds = start_offset + deadline_offset_minutes * 60
                deadline_str = f"{int(deadline_total_seconds // 60):02d}:{int(deadline_total_seconds % 60):02d}"


            start_node = random.choice(all_vertices)

            # Random destination count
            end_count = random.randint(end_min, end_max)
            end_vertices = []
            if end_count > 0:
                candidates = [v for v in all_vertices if v.get('id') != start_node.get('id')]
                if len(candidates) >= end_count:
                    end_vertices = random.sample(candidates, end_count)
                else:

                    end_vertices = [random.choice(all_vertices) for _ in range(end_count)]
                end_vertices = [v['id'] for v in end_vertices if v and v.get('id')]


            if priority_dist:

                rand_val = random.randint(1, 100)
                if rand_val <= priority_low:
                    priority = 'low'
                elif rand_val <= priority_low + priority_medium:
                    priority = 'medium'
                else:
                    priority = 'high'
            else:

                priority = random.choice(['low', 'medium', 'high'])

            task = {
                'id': f"T{datetime.now().strftime('%Y%m%d%H%M%S')}_{i}",
                'name': f'Task-{existing_count + i + 1}',
                'start_vertex': start_node['id'],
                'end_vertex': end_vertices[0] if end_vertices else '',
                'end_vertices': end_vertices,
                'priority': priority,
                'start_time': start_time_str,
                'deadline': deadline_str,
                'status': 'pending',
                'created_at': datetime.now().isoformat()
            }
            new_tasks.append(task)


        if is_simulation_active(scene_name):
            return jsonify({'success': False, 'error': 'Cannot generate tasks while the scene is running'}), 400


        scene.setdefault('tasks', [])
        scene['tasks'].extend(new_tasks)

        scene['name'] = scene_name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        set_scene_cache(scene_name, scene)


        return jsonify({
            'success': True,
            'tasks': new_tasks,
            'scene': scene,
            'message': 'Tasks generated in memory. Click Save scene to persist them.'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulate/move', methods=['POST'])
def simulate_move():
    """Preview AGV movement"""
    try:
        data = request.json
        agv_id = data.get('agv_id')
        target_position = data.get('target_position')

        if not agv_id or not target_position:
            return jsonify({'success': False, 'error': 'Required parameter is missing'}), 400

        if agv_id not in agv_states:
            return jsonify({'success': False, 'error': f'AGV {agv_id} not found'}), 404


        agv = agv_states[agv_id]
        agv.position = target_position
        agv.status = 'moving'
        agv.updated_at = datetime.now().isoformat()

        return jsonify({'success': True, 'agv': agv.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500




@app.route('/api/scenes/<scene_name>/tasks/<task_id>/submit', methods=['POST'])
def submit_task(scene_name, task_id):
    """Submit a task through the REST API"""
    try:

        if is_simulation_active(scene_name):
            cached_scene = get_cached_scene(scene_name)
            if cached_scene is None:
                scene = load_scene_data(scene_name)
                set_scene_cache(scene_name, scene)
            else:
                scene = cached_scene
        else:

            scene = load_scene_data(scene_name)
            sync_agv_state_from_scene(scene)


        task_updated = False
        for t in scene.get('tasks', []):
            if t['id'] == task_id:
                t['status'] = 'submitted'
                task_updated = True
                break

        if not task_updated:
            return jsonify({'success': False, 'error': 'Task not found'}), 404


        scene['name'] = scene_name
        scene.setdefault('created_at', datetime.now().isoformat())
        scene['updated_at'] = datetime.now().isoformat()
        set_scene_cache(scene_name, scene)

        return jsonify({'success': True, 'message': 'Task submitted'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/paths', methods=['GET'])
def get_sim_paths():
    """Get scheduled AGV paths through the REST API"""
    paths = {}
    for agv_id, agv in agv_states.items():
        if agv.edgeStates:
            paths[agv_id] = agv.edgeStates
    return jsonify({'success': True, 'paths': paths})


@app.route('/api/simulation/start', methods=['POST'])
def start_simulation():
    """Start simulation"""
    try:
        data = request.json or {}
        scene_name = data.get('scene_name')
        speed = data.get('speed')
        if not scene_name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400

        mark_simulation_active(scene_name)
        if speed is not None:
            set_scene_sim_speed(scene_name, speed)

        return jsonify({'success': True, 'message': f'Scene {scene_name} simulation activated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/pause', methods=['POST'])
def pause_simulation():
    """Pause simulation"""
    global simulation_paused, algorithm
    try:
        data = request.json or {}
        scene_name = data.get('scene_name')
        if not scene_name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400

        if active_scene_name == scene_name:
            simulation_paused = True

            if algorithm and hasattr(algorithm, 'set_paused'):
                algorithm.set_paused(True)

        return jsonify({'success': True, 'message': f'Scene {scene_name} simulation paused'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/resume', methods=['POST'])
def resume_simulation():
    """Resume simulation"""
    global simulation_paused, algorithm
    try:
        data = request.json or {}
        scene_name = data.get('scene_name')
        speed = data.get('speed')
        if not scene_name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400

        if active_scene_name == scene_name:
            simulation_paused = False

            if algorithm and hasattr(algorithm, 'set_paused'):
                algorithm.set_paused(False)
        if speed is not None:
            set_scene_sim_speed(scene_name, speed)

        return jsonify({'success': True, 'message': f'Scene {scene_name} simulation resumed'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/speed', methods=['POST'])
def update_simulation_speed():
    """Set simulation speed"""
    try:
        data = request.json or {}
        scene_name = data.get('scene_name')
        speed = data.get('speed')
        if not scene_name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400
        if speed is None:
            return jsonify({'success': False, 'error': 'Simulation speed is required'}), 400
        if active_scene_name and active_scene_name != scene_name:
            return jsonify({'success': False, 'error': 'This scene is not running'}), 400
        effective_speed = set_scene_sim_speed(scene_name, speed)
        return jsonify({'success': True, 'speed': effective_speed})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/reset', methods=['POST'])
def reset_simulation():
    """Reset simulation state"""
    global active_scene_name, simulation_paused, current_scene_name, current_scene_cache, current_sim_speed, algorithm, current_sim_time
    try:
        data = request.json or {}
        scene_name = data.get('scene_name')
        clear_all = data.get('clear_all', False)

        if clear_all:
            active_scene_name = None
            simulation_paused = False
            current_scene_name = None
            current_scene_cache = {}
            current_sim_speed = DEFAULT_SIM_SPEED
            current_sim_time = 0.0
            agv_states.clear()

            # simulation_logs.clear()


            if algorithm and hasattr(algorithm, 'set_paused'):
                algorithm.set_paused(False)

            if algorithm:
                algorithm.reset()

            print("Simulation state fully reset")
            return jsonify({'success': True, 'message': 'Simulation state fully reset'})

        if scene_name:
            if active_scene_name == scene_name:
                active_scene_name = None
                simulation_paused = False
                current_sim_speed = DEFAULT_SIM_SPEED
                current_sim_time = 0.0

                if algorithm and hasattr(algorithm, 'set_paused'):
                    algorithm.set_paused(False)
            if current_scene_name == scene_name:
                current_scene_name = None
                current_scene_cache = {}


        for agv in agv_states.values():
            agv.status = 'idle'
            agv.current_task = None
            agv.clear_paths_and_reset()


        if algorithm:
            algorithm.reset()


        if scene_name:
            scene = load_scene_data(scene_name, use_cache_if_active=False)

            for task in scene.get('tasks', []):
                task['status'] = 'pending'
                task.pop('agv_id', None)
                task.pop('completed_at_sim', None)
                task.pop('completed_at', None)
                task.pop('current_end_index', None)


            scene_file_data = load_scene_data(scene_name, use_cache_if_active=False)
            for file_agv in scene_file_data.get('agvs', []):
                agv_id = file_agv.get('id')
                if agv_id and agv_id in agv_states:
                    agv = agv_states[agv_id]

                    agv.position = file_agv.get('position', {'x': 0, 'y': 0, 'z': 0})
                    agv.orientation = file_agv.get('orientation', 0)
                    agv.status = 'idle'
                    agv.current_task = None
                    agv.battery = float(file_agv.get('battery', 100.0))
                    agv.max_speed = parse_positive_float(
                        file_agv.get('max_speed'),
                        agv.max_speed
                    )
                    agv.clear_paths_and_reset()




        return jsonify({'success': True, 'message': 'Simulation reset'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/scenes/<scene_name>/save', methods=['POST'])
def save_scene_explicit(scene_name):
    """Explicitly save a scene to disk"""
    try:

        if is_simulation_active(scene_name):
            return jsonify({'success': False, 'error': 'Cannot save while the scene is running'}), 400

        cached_scene = get_cached_scene(scene_name)
        scene = cached_scene if cached_scene is not None else load_scene_data(scene_name, use_cache_if_active=False)


        scene = save_scene_data(scene_name, scene, skip_if_simulating=False, force_save=True)
        return jsonify({'success': True, 'message': 'Scene saved', 'scene': scene})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/tasks/<task_id>/status', methods=['PUT'])
def update_task_status(task_id):
    """Update task state through the REST API"""
    try:
        data = request.json
        status = data.get('status') # pending, running, completed
        scene_name = data.get('scene_name')

        if not scene_name:
            return jsonify({'success': False, 'error': 'Scene name is required'}), 400


        if is_simulation_active(scene_name):
            cached_scene = get_cached_scene(scene_name)
            if cached_scene is None:
                scene = load_scene_data(scene_name)
                set_scene_cache(scene_name, scene)
            else:
                scene = cached_scene
        else:
            scene = load_scene_data(scene_name)

        updated = False
        for t in scene.get('tasks', []):
            if t['id'] == task_id:
                t['status'] = status
                updated = True
                break

        if not updated:
            return jsonify({'success': False, 'error': 'Task not found'}), 404


        if is_simulation_active(scene_name):
            set_scene_cache(scene_name, scene)
        else:
            scene['name'] = scene_name
            scene.setdefault('created_at', datetime.now().isoformat())
            scene['updated_at'] = datetime.now().isoformat()
            set_scene_cache(scene_name, scene)

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulation/stats', methods=['GET'])
def get_sim_stats():
    """Get simulation statistics"""
    try:
        scene_name = request.args.get('scene_name')
        if not scene_name:
            return jsonify({'success': False}), 400

        scene = load_scene_data(scene_name)
        tasks = scene.get('tasks', [])
        total = len(tasks)
        completed_tasks = [t for t in tasks if t.get('status') == 'completed']
        completed = len(completed_tasks)


        status_counts = {}
        for task in tasks:
            status = task.get('status', 'unknown')
            status_counts[status] = status_counts.get(status, 0) + 1
        failed_statuses = ['failed', 'error', 'cancelled']
        failed = sum(status_counts.get(s, 0) for s in failed_statuses)
        pending = status_counts.get('pending', 0) + status_counts.get('submitted', 0)
        running = status_counts.get('running', 0) + status_counts.get('moving_to_pickup', 0) + status_counts.get('moving_to_dropoff', 0)


        overdue_count = 0
        total_overdue_time = 0.0
        max_overdue_time = 0.0
        min_overdue_time = None

        early_count = 0
        total_early_time = 0.0
        max_early_time = 0.0
        min_early_time = None

        def parse_time_to_seconds(t_str):
            if not t_str: return None
            try:
                parts = t_str.split(':')
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
            except: pass
            return None

        stats = {
            'tasks': {
                'total': total,
                'completed': completed,
                'failed': failed,
                'pending': pending,
                'running': running,
                'success_rate': (completed / total * 100) if total > 0 else 0,
                'failure_rate': (failed / total * 100) if total > 0 else 0
            },
            'timing': {
                'overdue': {
                    'count': 0,
                    'rate': 0,
                    'avg': 0,
                    'max': 0,
                    'min': 0
                },
                'early': {
                    'count': 0,
                    'rate': 0,
                    'avg': 0,
                    'max': 0,
                    'min': 0
                }
            }
        }


        valid_completion_count = 0
        for t in completed_tasks:


            done_time = t.get('completed_at_sim')
            deadline_str = t.get('deadline')

            print(f"Task information: {t}")
            print(f"Completion time: {done_time}")
            print(f"Deadline: {deadline_str}")

            if done_time is not None and deadline_str:
                deadline = parse_time_to_seconds(deadline_str)
                if deadline is not None:
                    valid_completion_count += 1
                    diff = done_time - deadline

                    if diff > 0:
                        overdue_count += 1
                        total_overdue_time += diff
                        if diff > max_overdue_time:
                            max_overdue_time = diff
                        if min_overdue_time is None or diff < min_overdue_time:
                            min_overdue_time = diff
                    else:
                        early_count += 1
                        diff_abs = abs(diff)
                        total_early_time += diff_abs
                        if diff_abs > max_early_time:
                            max_early_time = diff_abs
                        if min_early_time is None or diff_abs < min_early_time:
                            min_early_time = diff_abs

        if completed > 0:
            stats['timing']['overdue']['rate'] = (overdue_count / completed * 100)
            stats['timing']['early']['rate'] = (early_count / completed * 100)

        if overdue_count > 0:
            stats['timing']['overdue']['count'] = overdue_count
            stats['timing']['overdue']['avg'] = total_overdue_time / overdue_count
            stats['timing']['overdue']['max'] = max_overdue_time
            stats['timing']['overdue']['min'] = min_overdue_time if min_overdue_time is not None else 0

        if early_count > 0:
            stats['timing']['early']['count'] = early_count
            stats['timing']['early']['avg'] = total_early_time / early_count
            stats['timing']['early']['max'] = max_early_time
            stats['timing']['early']['min'] = min_early_time if min_early_time is not None else 0

        return jsonify({
            'success': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Get simulation logs"""
    limit = int(request.args.get('limit', 100))
    return jsonify({'success': True, 'logs': simulation_logs[-limit:]})

@app.route('/api/logs', methods=['POST'])
def create_log():
    """Create a log entry through the REST API"""
    try:
        data = request.json
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': data.get('level', 'INFO'),
            'message': data.get('message', ''),
            'source': data.get('source', 'External')
        }
        simulation_logs.append(log_entry)
        # Keep log size manageable
        if len(simulation_logs) > 1000:
            simulation_logs.pop(0)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/static/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory('static', path)

@app.route('/<path:path>')
def serve_root(path):
    """Serve root files such as maps"""
    return send_from_directory('.', path)


if __name__ == '__main__':
    import argparse


    parser = argparse.ArgumentParser(description='AGV simulator backend service')
    parser.add_argument('--mqtt-broker', type=str, default=None,
                       help='VDA5050 MQTT broker host (default: environment or config)')
    parser.add_argument('--mqtt-port', type=int, default=None,
                       help='VDA5050 MQTT broker port (default: 1883)')
    parser.add_argument('--manufacturer', type=str, default=None,
                       help='VDA5050 manufacturer (default: AGV_Simulator)')
    parser.add_argument('--enable-real-agv', action='store_true',
                       help='Enable real AGV mode (requires MQTT)')
    args = parser.parse_args()

    print('=' * 60)
    print('Starting AGV simulator backend')
    print('=' * 60)
    print(f'Web UI: http://localhost:{config["server"]["port"]}')
    print(f'Scene directory: {SCENE_DIR}')



    if args.enable_real_agv:

        is_reloader = os.environ.get('WERKZEUG_RUN_MAIN') != 'true' and config['server']['debug']

        if not is_reloader:
            broker_host = args.mqtt_broker or VDA5050_MQTT_BROKER
            broker_port = args.mqtt_port or VDA5050_MQTT_PORT
            manufacturer = args.manufacturer or VDA5050_MANUFACTURER

            print(f'VDA5050 MQTT configuration:')
            print(f'  Broker: {broker_host}:{broker_port}')
            print(f'  manufacturer: {manufacturer}')
            print(f'  real AGV mode: {"enabled" if args.enable_real_agv else "disabled (simulation only)"}')

            if args.enable_real_agv:
                if init_vda5050_client(broker_host, broker_port, manufacturer):
                    print('OK VDA5050 MQTT client connected')
                else:
                    print('FAIL VDA5050 MQTT connection failed; real AGV support is unavailable')

    print('=' * 60)
    print('API endpoints:')
    print('  GET    /api/config         - Get configuration')
    print('  GET    /api/paths          - Get all paths')
    print('  GET    /api/paths/<id>     - Get a path')
    print('  POST   /api/paths          - save the path')
    print('  PUT    /api/paths/<id>     - Update a path')
    print('  DELETE /api/paths/<id>     - Delete a path')
    print('  GET    /api/agvs           - get all AGVs')
    print('  GET    /api/agvs/<id>      - get one AGV')
    print('  POST   /api/agvs           - Create an AGV')
    print('  PUT    /api/agvs/<id>      - Update an AGV')
    print('  DELETE /api/agvs/<id>      - Delete an AGV')
    print('  POST   /api/simulate/move  - Preview AGV movement')
    print('  GET    /api/logs           - get logs')
    print('  POST   /api/logs           - create a log entry')
    print('  POST   /api/scenes/<scene>/tasks/<task_id>/submit - submit a task')
    print('  PUT    /api/tasks/<task_id>/status - update task status')
    print('  POST   /api/simulation/reset - reset simulation')
    print('  POST   /api/scenes/<scene_name>/save - save scene explicitly')
    print('=' * 60)


    def log_callback(message, level='INFO'):
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'source': 'Scheduler'
        }
        simulation_logs.append(log_entry)
        if len(simulation_logs) > 1000:
            simulation_logs.pop(0)
        print(f"[Scheduler] {message}")

    # Enable MAPF debug mode to get detailed path planning logs
    # Set to True to see detailed debugging information for path planning failures
    MAPF_DEBUG_MODE = True
    algorithm = ThreadedAlgorithm(log_callback, debug_mapf=MAPF_DEBUG_MODE)


    if not config['server']['debug'] or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        print('Starting simulation loop...')
        sim_thread = threading.Thread(target=run_simulation_loop, daemon=True)
        sim_thread.start()


    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    app.run(
        host=config['server']['host'],
        port=config['server']['port'],
        debug=config['server']['debug']
    )
