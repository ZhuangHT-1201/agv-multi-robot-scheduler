from .base import BaseAlgorithm
from common.graph import Graph, a_star_search
import math
import time

class SimpleAlgorithm(BaseAlgorithm):
    def __init__(self, log_cb=None):
        super().__init__(log_cb)
        self.agv_assignments = {} # agv_id -> task_id
        self.agv_full_paths = {} # agv_id -> {full_path, issued_count, task_id, phase, last_base_sequence_id}

    def init_map(self, paths):
        self.graph = Graph()
        for path in paths:
            for v in path.get('vertices', []):
                self.graph.add_vertex(v)
            for e in path.get('edges', []):
                self.graph.add_edge(e)
        self.graph.compute_adjacency_matrix()

    def reset(self):
        super().reset()
        self.agv_assignments.clear()
        self.agv_full_paths.clear()

    def process(self, agvs, tasks, current_time, action_configs=None):
        """
        :param agvs: Dict[str, AGV]
        :return: List[Dict] commands
        """
        commands = []
        if not self.graph:
            return commands

        # 1. Record newly submitted tasks
        self._log_task_submissions(tasks)


        self._monitor_running_tasks(agvs, tasks, commands, current_time)


        self._process_assignments(agvs, tasks, commands)

        return commands

    def _task_name(self, task):
        return task.get('name') or task.get('id', 'Unnamed task')

    def _agv_name(self, agv):
        return agv.name or agv.id

    def _process_assignments(self, agvs, tasks, commands):

        pending_tasks = [t for t in tasks if t['status'] == 'submitted']
        assigned_task_ids = set(self.agv_assignments.values())
        unassigned_tasks = [t for t in pending_tasks if t['id'] not in assigned_task_ids]

        unassigned_tasks.sort(key=self._parse_start_time)

        idle_agvs = []
        for agv_id, agv in agvs.items():

            if agv.status == 'idle' and agv_id not in self.agv_assignments:
                idle_agvs.append(agv_id)

        for task in unassigned_tasks:
            if not idle_agvs:
                break


            best_agv_id = None
            min_dist = float('inf')
            start_node_id = task['start_vertex']

            for agv_id in idle_agvs:
                agv = agvs[agv_id]
                dist = self._get_distance_from_agv_to_node(agv, start_node_id)
                if dist < min_dist:
                    min_dist = dist
                    best_agv_id = agv_id

            if best_agv_id:
                self._assign_task_to_agv(agvs[best_agv_id], task, commands)
                idle_agvs.remove(best_agv_id)

    def _assign_task_to_agv(self, agv, task, commands):
        agv_id = agv.id
        self.log(f"Task {self._task_name(task)} assigned to AGV {self._agv_name(agv)}")

        self.agv_assignments[agv_id] = task['id']


        commands.append({
            'type': 'UPDATE_TASK',
            'task_id': task['id'],
            'updates': {'status': 'assigned', 'agv_id': agv_id}
        })


        nearest_node = self.find_nearest_node(agv.position)
        if nearest_node:
            self._plan_and_issue_path(
                agv=agv,
                task=task,
                agv_id=agv_id,
                start_node=nearest_node,
                target_node=task['start_vertex'],
                order_id_suffix='pickup',
                phase='pickup',
                update_task_status_to='moving_to_pickup',
                commands=commands,
                no_path_msg=f"No path from AGV {self._agv_name(agv)} to the task start"
            )
        else:
            self.log(f"No node near AGV {self._agv_name(agv)}", level='WARN')

    def _monitor_running_tasks(self, agvs, tasks, commands, current_time):
        for agv_id, task_id in list(self.agv_assignments.items()):
            agv = agvs.get(agv_id)
            if not agv: continue

            task = next((t for t in tasks if t['id'] == task_id), None)
            if not task:
                self._clear_assignment(agv_id, commands)
                continue


            if agv_id in self.agv_full_paths:
                self._check_and_update_path(agv, agv_id, commands)


            self._update_agv_task_logic(agv, task, commands, current_time)

    def _plan_and_issue_path(self, agv, task, agv_id, start_node, target_node,
                            order_id_suffix, phase, update_task_status_to,
                            commands, no_path_msg):


        if start_node == target_node:

            seq_id = 0
            nodes = []
            edges = []

            start_v = self.graph.get_node(start_node)
            if not start_v:
                if no_path_msg: self.log(no_path_msg, level='WARN')
                return False

            nodes.append(self._node_to_vda5050(start_v, seq_id, True))

            self.agv_full_paths[agv_id] = {
                'full_path': [],
                'issued_count': 0,
                'task_id': task['id'],
                'phase': phase,
                'last_base_sequence_id': seq_id
            }
        else:
            full_path_edges = a_star_search(self.graph, start_node, target_node)
            if full_path_edges is None:
                if no_path_msg: self.log(no_path_msg, level='WARN')
                return False

            base_size = min(3, len(full_path_edges))
            horizon_size = min(3, len(full_path_edges) - base_size)


            seq_id = 0
            nodes = []
            edges = []


            start_v = self.graph.get_node(start_node)
            nodes.append(self._node_to_vda5050(start_v, seq_id, True))
            seq_id += 1


            for i in range(base_size):
                edge_info = full_path_edges[i]
                # Edge
                edges.append(self._path_edge_to_vda5050(edge_info, seq_id, True))
                seq_id += 1
                # Target Node
                target_v = self.graph.get_node(edge_info['target'])
                nodes.append(self._node_to_vda5050(target_v, seq_id, True))
                seq_id += 1


            last_base_seq_id = seq_id - 1


            for i in range(horizon_size):
                edge_info = full_path_edges[base_size + i]
                # Edge
                edges.append(self._path_edge_to_vda5050(edge_info, seq_id, False))
                seq_id += 1
                # Target Node
                target_v = self.graph.get_node(edge_info['target'])
                nodes.append(self._node_to_vda5050(target_v, seq_id, False))
                seq_id += 1

            self.agv_full_paths[agv_id] = {
                'full_path': full_path_edges,
                'issued_count': base_size,
                'task_id': task['id'],
                'phase': phase,
                'last_base_sequence_id': last_base_seq_id
            }


        order_data = {
            'orderId': f"order_{time.time()}_{agv.name}",
            'orderUpdateId': 0,
            'nodes': nodes,
            'edges': edges
        }


        commands.append({
            'type': 'SEND_ORDER',
            'agv_id': agv_id,
            'order': order_data
        })

        if update_task_status_to:
            commands.append({
                'type': 'UPDATE_TASK',
                'task_id': task['id'],
                'updates': {'status': update_task_status_to}
            })


            commands.append({
                'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                'agv_id': agv_id,
                'task_snapshot': {
                    'id': task['id'],
                    'name': self._task_name(task),
                    'status': update_task_status_to,
                    'start_vertex': task.get('start_vertex'),
                    'end_vertex': task.get('end_vertex'),
                    'end_vertices': self._get_end_vertices(task),
                    'current_end_index': self._get_current_end_index(task)
                }
            })

        return True

    def _check_and_update_path(self, agv, agv_id, commands):
        if agv_id not in self.agv_full_paths: return

        path_info = self.agv_full_paths[agv_id]
        full_path_edges = path_info['full_path']
        issued_count = path_info['issued_count']
        last_base_seq_id = path_info.get('last_base_sequence_id', 0)





        released_edges = [e for e in agv.edgeStates if e.get('released')]
        remaining_base_edges = len(released_edges)

        if remaining_base_edges < 2:
            if issued_count < len(full_path_edges):
                remaining_path = full_path_edges[issued_count:]





                base_size = min(3, len(remaining_path))
                new_base_path = remaining_path[:base_size]

                horizon_size = min(3, len(remaining_path) - base_size)
                new_horizon_path = remaining_path[base_size:base_size + horizon_size] if horizon_size > 0 else []

                nodes = []
                edges = []


                seq_id = last_base_seq_id + 1


                if base_size > 0:
                    first_edge = new_base_path[0]
                    source_node = self.graph.get_node(first_edge['source'])
                    if source_node:
                        nodes.append(self._node_to_vda5050(source_node, seq_id, True))
                        seq_id += 1


                for i in range(base_size):
                    edge_info = new_base_path[i]
                    # Edge
                    edges.append(self._path_edge_to_vda5050(edge_info, seq_id, True))
                    seq_id += 1
                    # Target Node
                    target_v = self.graph.get_node(edge_info['target'])
                    nodes.append(self._node_to_vda5050(target_v, seq_id, True))
                    seq_id += 1


                new_last_base_seq_id = seq_id - 1


                for i in range(horizon_size):
                    edge_info = new_horizon_path[i]
                    # Edge
                    edges.append(self._path_edge_to_vda5050(edge_info, seq_id, False))
                    seq_id += 1
                    # Target Node
                    target_v = self.graph.get_node(edge_info['target'])
                    nodes.append(self._node_to_vda5050(target_v, seq_id, False))
                    seq_id += 1

                order_data = {
                    'orderId': agv.orderId,
                    'orderUpdateId': agv.orderUpdateId + 1,
                    'nodes': nodes,
                    'edges': edges
                }

                commands.append({
                    'type': 'SEND_ORDER',
                    'agv_id': agv_id,
                    'order': order_data
                })

                path_info['issued_count'] = issued_count + base_size
                path_info['last_base_sequence_id'] = new_last_base_seq_id
                self.log(f"Issued next path segment to AGV {self._agv_name(agv)}")

    def _get_end_vertices(self, task):
        """Get task destinations"""

        if 'end_vertices' in task and isinstance(task['end_vertices'], list) and len(task['end_vertices']) > 0:
            return task['end_vertices']

        elif 'end_vertex' in task and task['end_vertex']:
            return [task['end_vertex']]
        return []

    def _get_current_end_index(self, task):
        """Get the active destination index"""
        return task.get('current_end_index', 0)

    def _update_agv_task_logic(self, agv, task, commands, current_time):
        if agv.wait_until is not None:
            return

        target_node_id = None
        if task['status'] == 'moving_to_pickup':
            target_node_id = task['start_vertex']
        elif task['status'] == 'moving_to_dropoff':

            end_vertices = self._get_end_vertices(task)
            current_end_index = self._get_current_end_index(task)
            if end_vertices and current_end_index < len(end_vertices):
                target_node_id = end_vertices[current_end_index]
            else:
                target_node_id = task.get('end_vertex')

        if not target_node_id: return

        if not agv.orderId:
            return


        agv_id = agv.id
        has_remaining_path = False
        if agv_id in self.agv_full_paths:
            path_info = self.agv_full_paths[agv_id]
            has_remaining_path = path_info['issued_count'] < len(path_info['full_path'])
        print(f"agv {agv_id} {self.agv_full_paths[agv_id]['issued_count']}, {len(self.agv_full_paths[agv_id]['full_path'])}")





        if agv.newBaseRequest and not has_remaining_path and agv.orderId:



            def complete_task(log_level, message, include_snapshot=False):
                """Shared completion logic for pickup/dropoff."""
                self.log(message, log_level)
                commands.append({
                    'type': 'UPDATE_TASK',
                    'task_id': task['id'],
                    'updates': {
                        'status': 'completed',
                        'completed_at_sim': current_time
                    }
                })
                if include_snapshot:
                    commands.append({
                        'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                        'agv_id': agv_id,
                        'task_snapshot': None
                    })

            def reset_agv_path():
                if agv_id in self.agv_full_paths:
                    del self.agv_full_paths[agv_id]

            def plan_dropoff(end_vertices, end_index, start_node, order_suffix, no_path_msg):
                reset_agv_path()
                commands.append({
                    'type': 'UPDATE_TASK',
                    'task_id': task['id'],
                    'updates': {
                        'status': 'moving_to_dropoff',
                        'current_end_index': end_index
                    }
                })
                self._plan_and_issue_path(
                    agv=agv,
                    task=task,
                    agv_id=agv_id,
                    start_node=start_node,
                    target_node=end_vertices[end_index],
                    order_id_suffix=order_suffix,
                    phase='dropoff',
                    update_task_status_to='moving_to_dropoff',
                    commands=commands,
                    no_path_msg=no_path_msg
                )

            if task['status'] == 'moving_to_pickup':
                self.log(f"AGV {self._agv_name(agv)} reached the pickup point")


                end_vertices = self._get_end_vertices(task)
                if not end_vertices:
                    complete_task('INFO', f"Task {task['id']} has no end vertices, marking as completed", include_snapshot=True)
                    return


                current_end_index = 0
                plan_dropoff(
                    end_vertices=end_vertices,
                    end_index=current_end_index,
                    start_node=task['start_vertex'],
                    order_suffix='dropoff',
                    no_path_msg=f"No delivery path for task {self._task_name(task)}"
                )

            elif task['status'] == 'moving_to_dropoff':

                end_vertices = self._get_end_vertices(task)
                current_end_index = self._get_current_end_index(task)

                if not end_vertices:
                    complete_task('WARN', f"Task {task['id']} has no end vertices, marking as completed")
                    return


                next_end_index = current_end_index + 1
                if next_end_index < len(end_vertices):

                    next_end_vertex = end_vertices[next_end_index]
                    self.log(f"AGV {self._agv_name(agv)} reached destination {current_end_index + 1}/{len(end_vertices)}; heading to {next_end_index + 1}/{len(end_vertices)}")
                    plan_dropoff(
                        end_vertices=end_vertices,
                        end_index=next_end_index,
                        start_node=end_vertices[current_end_index],
                        order_suffix=f'dropoff_{next_end_index}',
                        no_path_msg=f"No path from task {self._task_name(task)} to the next destination"
                    )
                else:

                    complete_task('INFO', f"AGV {self._agv_name(agv)} completed task {self._task_name(task)}")

                commands.append({
                    'type': 'UPDATE_AGV_TASK_SNAPSHOT',
                    'agv_id': agv_id,
                    'task_snapshot': None # Clear task
                })

                self._clear_assignment(agv_id, commands)

    def _clear_assignment(self, agv_id, commands):
        """Clear the assignment and set the AGV to idle"""
        if agv_id in self.agv_assignments:
            del self.agv_assignments[agv_id]
        if agv_id in self.agv_full_paths:
            del self.agv_full_paths[agv_id]


        commands.append({
            'type': 'UPDATE_AGV_STATUS',
            'agv_id': agv_id,
            'status': 'idle',
            'clear_paths': True
        })

    # ... helpers ...
    def _log_task_submissions(self, tasks):
        for task in tasks:
            task_id = task.get('id')
            if not task_id: continue
            if task.get('status') == 'submitted' and task_id not in self.seen_submitted_tasks:
                self.seen_submitted_tasks.add(task_id)
                self.log(f"Task received: {self._task_name(task)}")

    def _get_distance_from_agv_to_node(self, agv, node_id):
        pos = agv.position
        if node_id in self.graph.nodes:
            node = self.graph.nodes[node_id]
            return math.sqrt((pos['x'] - node['x'])**2 + (pos['y'] - node['y'])**2)
        return float('inf')

    def find_nearest_node(self, pos):
        if not self.graph: return None
        min_dist = float('inf')
        best_node = None
        for node_id, node in self.graph.nodes.items():
            dist = math.sqrt((pos['x'] - node['x'])**2 + (pos['y'] - node['y'])**2)
            if dist < min_dist:
                min_dist = dist
                best_node = node_id
        return best_node

    def _parse_start_time(self, task):
        start_time = task.get('start_time', '')
        if not start_time: return float('inf')
        try:
            parts = start_time.split(':')
            return int(parts[0]) * 60 + int(parts[1])
        except: return float('inf')

    def _path_edge_to_vda5050(self, edge, seq_id, released):
        return {
            'edgeId': edge.get('id', ''),
            'sequenceId': seq_id,
            'description': f"Edge to {edge.get('target')}",
            'released': released,
            'startNodeId': edge.get('source'),
            'endNodeId': edge.get('target'),
            'maxSpeed': edge.get('max_speed'),
            'distance': edge.get('length')
        }

    def _node_to_vda5050(self, node, seq_id, released):
        return {
            'nodeId': node['id'],
            'sequenceId': seq_id,
            'nodePosition': {
                'x': node.get('x', 0),
                'y': node.get('y', 0),
                'theta': node.get('theta', 0),
                'mapId': 'map_0'
            },
            'released': released,
            'actions': [] # Can populate actions here based on node properties
        }
