import threading
import time
import math
import queue

class TaskAllocator(threading.Thread):
    def __init__(self, move_request_queue, agv_travel_status, log_cb=None):
        """
        :param move_request_queue: Queue to send movement requests to PathPlanner
        :param agv_travel_status: Shared dict {agv_id: 'idle'|'moving'|'reached_target'} updated by PathPlanner
        """
        super().__init__(daemon=True)
        self.move_request_queue = move_request_queue
        self.agv_travel_status = agv_travel_status
        self.log_cb = log_cb

        self.running = True
        self.paused = False

        # Local state
        self.agv_assignments = {} # agv_id -> task_id
        self.generated_commands = []
        self.commands_lock = threading.Lock()
        self.seen_submitted_tasks = set()

        # Input data snapshots (updated by main thread)
        self.data_lock = threading.Lock()
        self.latest_agvs = {}
        self.latest_tasks = []
        self.graph = None
        self.current_time = 0.0

    def update_data(self, agvs, tasks, graph, current_time=0.0):
        with self.data_lock:
            self.latest_agvs = agvs
            self.latest_tasks = tasks
            self.graph = graph
            self.current_time = current_time

    def get_commands(self):
        with self.commands_lock:
            cmds = self.generated_commands[:]
            self.generated_commands.clear()
            return cmds

    def log(self, msg, level='INFO'):
        if self.log_cb:
            self.log_cb(f"[Allocator] {msg}", level)

    def run(self):
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue

            try:
                self._run_cycle()
            except Exception as e:
                self.log(f"Error in cycle: {e}", 'ERROR')
                import traceback
                traceback.print_exc()

            time.sleep(0.12)

    def _run_cycle(self):
        # 1. Get snapshot
        with self.data_lock:
            agvs = self.latest_agvs
            tasks = self.latest_tasks
            graph = self.graph

        if not graph: return

        # 2. Record newly submitted tasks
        self._log_task_submissions(tasks)

        # 3. Monitor running tasks
        self._monitor_assignments(agvs, tasks)

        # 4. New assignments
        self._process_new_assignments(agvs, tasks)

    def _monitor_assignments(self, agvs, tasks):
        # Check assignments
        for agv_id, task_id in list(self.agv_assignments.items()):
            agv = agvs.get(agv_id)
            if not agv:
                for candidate in agvs.values():
                    if candidate.id == agv_id:
                        agv = candidate
                        break
            if not agv:
                continue

            task = next((t for t in tasks if t['id'] == task_id), None)
            if not task:
                self._clear_assignment(agv_id)
                continue

            # Check travel status from PathPlanner
            travel_status = self.agv_travel_status.get(agv_id, {})
            status_code = travel_status.get('status') # 'moving', 'reached', 'failed'

            if status_code == 'reached':
                self.agv_travel_status[agv_id] = {'status': 'idle'}
                self._handle_arrival(agv, task, travel_status)
            elif status_code == 'failed':
                agv_name = agv.name or agv.id if agv else agv_id
                self.log(f"Path planning failed for AGV {agv_name}: {travel_status.get('reason')}", 'WARN')

                self.agv_travel_status[agv_id] = {'status': 'idle'}
                # Maybe retry or cancel? For now, do nothing or re-issue
                pass

    def _get_end_vertices(self, task):
        """Get task destinations"""

        if 'end_vertices' in task and isinstance(task['end_vertices'], list) and len(task['end_vertices']) > 0:
            return task['end_vertices']

        elif 'end_vertex' in task and task['end_vertex']:
            return [task['end_vertex']]
        return []

    def _get_current_end_index(self, task):
        """Get the active destination index"""
        value = task.get('current_end_index', 0)
        try:
            return int(value)
        except (TypeError, ValueError):
            self.log(
                f"Task {task.get('id')} has invalid current_end_index={value}, fallback to 0",
                'WARN'
            )
            return 0

    def _resolve_arrival_phase(self, agv, task, travel_status):
        """
        Infer whether an arrival is a pickup or dropoff from target_node.

        Task status alone is unreliable across threads because the status update
        can arrive after the path thread's reached event.
        """
        target_node = travel_status.get('target_node')
        start_vertex = task.get('start_vertex')
        end_vertices = self._get_end_vertices(task)
        current_end_index = self._get_current_end_index(task)
        task_status = task.get('status')

        if target_node and target_node == start_vertex:
            return 'pickup', None

        if target_node and end_vertices:
            if 0 <= current_end_index < len(end_vertices) and target_node == end_vertices[current_end_index]:
                return 'dropoff', current_end_index
            if target_node in end_vertices:
                return 'dropoff', end_vertices.index(target_node)

        current_task = getattr(agv, 'current_task', None)
        if isinstance(current_task, dict):
            snapshot_status = current_task.get('status')
            snapshot_end_vertices = current_task.get('end_vertices') or end_vertices
            snapshot_end_index = current_task.get('current_end_index', current_end_index)

            if target_node and target_node == current_task.get('start_vertex'):
                return 'pickup', None

            if target_node and snapshot_end_vertices:
                if 0 <= snapshot_end_index < len(snapshot_end_vertices) and target_node == snapshot_end_vertices[snapshot_end_index]:
                    return 'dropoff', snapshot_end_index
                if target_node in snapshot_end_vertices:
                    return 'dropoff', snapshot_end_vertices.index(target_node)

            if snapshot_status == 'moving_to_pickup':
                return 'pickup', None
            if snapshot_status == 'moving_to_dropoff':
                return 'dropoff', snapshot_end_index

        if task_status == 'moving_to_pickup':
            return 'pickup', None
        if task_status == 'moving_to_dropoff':
            return 'dropoff', current_end_index

        return None, None

    def _handle_arrival(self, agv, task, travel_status):
        # Check which phase was completed
        # travel_status['target_node'] could help verify

        def complete_task(log_level='INFO', log_msg=None):
            """Finish task and clear assignment with shared bookkeeping."""
            if log_msg:
                self.log(log_msg, log_level)
            with self.commands_lock:
                with self.data_lock:
                    sim_time = self.current_time
                self.generated_commands.append({
                    'type': 'UPDATE_TASK',
                    'task_id': task['id'],
                    'updates': {
                        'status': 'completed',
                        'completed_at_sim': sim_time
                    }
                })
                self.generated_commands.append({
                    'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                    'agv_id': agv.id,
                    'task_snapshot': None
                })
            self._clear_assignment(agv.id)

        def move_to_end(end_vertices, end_index):
            """Issue commands to move toward the specified dropoff index."""
            target_end_vertex = end_vertices[end_index]
            with self.commands_lock:
                self.generated_commands.append({
                    'type': 'UPDATE_TASK',
                    'task_id': task['id'],
                    'updates': {
                        'status': 'moving_to_dropoff',
                        'current_end_index': end_index
                    }
                })
                self.generated_commands.append({
                    'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                    'agv_id': agv.id,
                    'task_snapshot': {
                        'id': task['id'],
                        'name': task.get('name'),
                        'status': 'moving_to_dropoff',
                        'start_vertex': task.get('start_vertex'),
                        'end_vertex': target_end_vertex,  # Current To
                        'end_vertices': end_vertices,
                        'current_end_index': end_index
                    }
                })

            self.agv_travel_status[agv.id] = {'status': 'pre-planning'}
            self.move_request_queue.put({
                'agv_id': agv.id,
                'target_node': target_end_vertex,
                'task_id': task['id'],
                'phase': 'dropoff',
                'description': f'Moving to dropoff {end_index + 1}/{len(end_vertices)}'
            })

        arrival_phase, arrival_end_index = self._resolve_arrival_phase(agv, task, travel_status)

        if arrival_phase == 'pickup':
            self.log(f"AGV {agv.name or agv.id} reached Pickup point")


            end_vertices = self._get_end_vertices(task)
            if not end_vertices:
                complete_task('INFO', f"Task {task['id']} has no end vertices, marking as completed")
                return


            current_end_index = 0
            move_to_end(end_vertices, current_end_index)


        elif arrival_phase == 'dropoff':

            end_vertices = self._get_end_vertices(task)
            current_end_index = arrival_end_index if arrival_end_index is not None else self._get_current_end_index(task)

            if not end_vertices:
                complete_task('WARN', f"Task {task['id']} has no end vertices, marking as completed")
                return


            next_end_index = current_end_index + 1
            if next_end_index < len(end_vertices):

                next_end_vertex = end_vertices[next_end_index]
                self.log(f"AGV {agv.name or agv.id} reached Dropoff point {current_end_index + 1}/{len(end_vertices)}, moving to next dropoff {next_end_index + 1}/{len(end_vertices)}")
                move_to_end(end_vertices, next_end_index)
            else:

                self.log(f"AGV {agv.name or agv.id} reached final Dropoff point. Task Complete.")
                complete_task()
        else:
            self.log(
                f"AGV {agv.name or agv.id} reached {travel_status.get('target_node')} "
                f"but task {task['id']} is in unexpected status {task.get('status')}, "
                "keeping assignment unchanged",
                'WARN'
            )

    def _process_new_assignments(self, agvs, tasks):
        pending_tasks = [t for t in tasks if t['status'] == 'submitted']
        assigned_task_ids = set(self.agv_assignments.values())
        unassigned_tasks = [t for t in pending_tasks if t['id'] not in assigned_task_ids]

        if not unassigned_tasks: return

        priority_rank = {'high': 0, 'medium': 1, 'low': 2}
        unassigned_tasks.sort(
            key=lambda t: (
                priority_rank.get(str(t.get('priority', 'medium')).lower(), 1),
                t.get('created_at', ''),
            )
        )

        idle_agvs = []
        for agv_id, agv in agvs.items():
            if agv.status == 'idle' and agv_id not in self.agv_assignments:
                idle_agvs.append(agv_id)

        # Greedy min-cost bipartite matching: repeatedly assign best (agv, task) pair.
        while idle_agvs and unassigned_tasks:
            best_pair = None
            best_cost = float('inf')
            for task in unassigned_tasks:
                for agv_id in idle_agvs:
                    agv = agvs[agv_id]
                    dist = self._get_distance(agv, task['start_vertex'])
                    if dist == float('inf'):
                        continue
                    end_vertices = self._get_end_vertices(task)
                    drop_node = end_vertices[0] if end_vertices else task.get('end_vertex')
                    drop_cost = 0.0
                    if drop_node and self.graph and hasattr(self.graph, 'get_cost'):
                        leg = self.graph.get_cost(task['start_vertex'], drop_node)
                        if leg is not None:
                            drop_cost = float(leg)
                    cost = float(dist) + 0.35 * drop_cost
                    if cost < best_cost:
                        best_cost = cost
                        best_pair = (agv_id, task)
            if best_pair is None:
                break
            agv_id, task = best_pair
            self._assign(agvs[agv_id], task, agv_dict_key=agv_id)
            idle_agvs.remove(agv_id)
            unassigned_tasks.remove(task)

    def _find_best_agv(self, candidate_ids, agvs, task):
        best_id = None
        min_dist = float('inf')
        start_node_id = task['start_vertex']
        end_vertices = self._get_end_vertices(task)
        drop_node = end_vertices[0] if end_vertices else task.get('end_vertex')
        drop_cost = 0.0
        if drop_node and self.graph and hasattr(self.graph, 'get_cost'):
            leg = self.graph.get_cost(start_node_id, drop_node)
            if leg is not None:
                drop_cost = float(leg)

        for agv_id in candidate_ids:
            agv = agvs[agv_id]
            dist = self._get_distance(agv, start_node_id)
            if dist == float('inf'):
                continue
            total = float(dist) + drop_cost
            if total < min_dist:
                min_dist = total
                best_id = agv_id
        return best_id

    def _get_distance(self, agv, node_id):
        if not self.graph:
            return float('inf')

        agv_node_id = self._get_agv_current_node(agv)
        if agv_node_id and hasattr(self.graph, 'get_cost'):
            cost = self.graph.get_cost(agv_node_id, node_id)
            if cost is not None:
                return cost

        pos = getattr(agv, 'position', {}) or {}
        node = self.graph.get_node(node_id)
        if node:
            return math.sqrt((pos['x'] - node['x'])**2 + (pos['y'] - node['y'])**2)
        return float('inf')

    def _get_agv_current_node(self, agv):
        """Prefer the AGV's last known road-network node."""
        last_node_id = getattr(agv, 'last_node_id', None)
        if last_node_id and last_node_id in getattr(self.graph, 'nodes', {}):
            return last_node_id
        return self._find_nearest_node(getattr(agv, 'position', None))

    def _find_nearest_node(self, pos):
        if not self.graph or not pos:
            return None

        px = pos.get('x', 0) if isinstance(pos, dict) else getattr(pos, 'x', 0)
        py = pos.get('y', 0) if isinstance(pos, dict) else getattr(pos, 'y', 0)
        best_id = None
        best_dist = float('inf')

        for node_id, node in getattr(self.graph, 'nodes', {}).items():
            dx = px - node.get('x', 0)
            dy = py - node.get('y', 0)
            dist = dx * dx + dy * dy
            if dist < best_dist:
                best_dist = dist
                best_id = node_id
        return best_id

    def _assign(self, agv, task, agv_dict_key=None):
        agv_key = agv_dict_key if agv_dict_key is not None else agv.id
        self.log(f"Assigning Task {task.get('name')} to AGV {agv.name or agv.id}")
        self.agv_assignments[agv_key] = task['id']

        with self.commands_lock:
            self.generated_commands.append({
                'type': 'UPDATE_TASK',
                'task_id': task['id'],
                'updates': {'status': 'assigned', 'agv_id': agv_key}
            })

            # Update AGV snapshot to "assigned" immediately
            end_vertices = self._get_end_vertices(task)
            self.generated_commands.append({
                'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                'agv_id': agv_key,
                'task_snapshot': {
                    'id': task['id'],
                    'name': task.get('name'),
                    'status': 'moving_to_pickup',
                    'start_vertex': task.get('start_vertex'),
                    'end_vertex': end_vertices[0] if end_vertices else task.get('end_vertex'),
                    'end_vertices': end_vertices,
                    'current_end_index': 0
                }
            })

            self.generated_commands.append({
                'type': 'UPDATE_TASK',
                'task_id': task['id'],
                'updates': {'status': 'moving_to_pickup'}
            })

        # Send move request
        self.move_request_queue.put({
            'agv_id': agv_key,
            'target_node': task['start_vertex'],
            'task_id': task['id'],
            'phase': 'pickup',
            'description': 'Moving to pickup'
        })

    def _clear_assignment(self, agv_id):
        if agv_id in self.agv_assignments:
            del self.agv_assignments[agv_id]

        with self.commands_lock:
            self.generated_commands.append({
                'type': 'UPDATE_AGV_STATUS',
                'agv_id': agv_id,
                'status': 'idle',
                'clear_paths': True
            })

    def reset(self):
        """Reset task allocator"""
        self.agv_assignments.clear()
        self.seen_submitted_tasks.clear()
        with self.commands_lock:
            self.generated_commands.clear()

    def _log_task_submissions(self, tasks):
        """Record newly submitted tasks"""
        for task in tasks:
            task_id = task.get('id')
            if not task_id: continue
            if task.get('status') == 'submitted' and task_id not in self.seen_submitted_tasks:
                self.seen_submitted_tasks.add(task_id)
                task_name = task.get('name') or task.get('id', 'Unnamed task')
                self.log(f"Task received: {task_name}")
