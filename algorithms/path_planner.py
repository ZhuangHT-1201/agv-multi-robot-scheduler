import threading
import time
import queue
from common.graph import a_star_search

class PathPlanner(threading.Thread):
    def __init__(self, move_request_queue, agv_travel_status, log_cb=None, base_size=3, horizon_size=3):
        super().__init__(daemon=True)
        self.move_request_queue = move_request_queue
        self.agv_travel_status = agv_travel_status # Shared dict
        self.log_cb = log_cb

        # Rolling path parameters
        self.base_size = base_size  # Released segment size
        self.horizon_size = horizon_size  # Horizon segment size

        self.running = True
        self.paused = False

        # agv_id -> {full_path: [], issued_count: int, target_node: str, last_base_sequence_id: int}
        self.active_paths = {}

        self.generated_commands = []
        self.commands_lock = threading.Lock()

        self.data_lock = threading.Lock()
        self.latest_agvs = {}
        self.graph = None

    def update_data(self, agvs, graph):
        with self.data_lock:
            self.latest_agvs = agvs
            self.graph = graph

    def get_commands(self):
        with self.commands_lock:
            cmds = self.generated_commands[:]
            self.generated_commands.clear()
            return cmds

    def reset(self):
        """Reset path planner"""
        self.active_paths.clear()
        with self.commands_lock:
            self.generated_commands.clear()

    def log(self, msg, level='INFO'):
        if self.log_cb:
            self.log_cb(f"[Planner] {msg}", level)

    def _agv_name(self, agv):
        return agv.name or agv.id

    def run(self):
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue

            try:
                self._process_requests()
                self._monitor_paths()
            except Exception as e:
                self.log(f"Error in planner cycle: {e}", 'ERROR')
                import traceback
                traceback.print_exc()

            time.sleep(0.05)

    def _process_requests(self):
        while not self.move_request_queue.empty():
            try:
                req = self.move_request_queue.get_nowait()
                self._handle_move_request(req)
            except queue.Empty:
                break

    def _handle_move_request(self, req):
        agv_id = req['agv_id']
        target_node = req['target_node']
        task_id = req.get('task_id', 'unknown')

        # Update status immediately to prevent allocator from thinking it's still 'reached'
        self.agv_travel_status[agv_id] = {'status': 'planning'}

        with self.data_lock:
            agv = self.latest_agvs.get(agv_id)
            graph = self.graph

        if not agv or not graph:
            self.log(f"AGV {agv_id} or map is unavailable", 'ERROR')
            self.agv_travel_status[agv_id] = {'status': 'failed', 'reason': 'No AGV/Graph'}
            return

        agv_name = self._agv_name(agv)
        self.log(f"Plan a path for AGV {agv_name} to {target_node}")

        # Find start node (nearest)
        start_node = self._find_nearest_node(agv.position)
        if not start_node:
            self.log(f"No nearest node found for AGV {agv_name}", 'WARN')
            self.agv_travel_status[agv_id] = {'status': 'failed', 'reason': 'No Start Node'}
            return

        # Plan path
        if start_node == target_node:
             # Already there? Check physics?
             # If strictly same node ID, generate a zero-length order to ensure AGV logic is consistent
             full_path_edges = []
        else:
            full_path_edges = a_star_search(graph, start_node, target_node)
            if full_path_edges is None:
                self.log(f"No path found for AGV {agv_name}: {start_node} -> {target_node}", 'WARN')
                self.agv_travel_status[agv_id] = {'status': 'failed', 'reason': 'No Path Found'}
                return

        # Initialize path state
        self.active_paths[agv_id] = {
            'full_path': full_path_edges,
            'issued_count': 0,
            'target_node': target_node,
            'last_base_sequence_id': 0,
            'task_id': task_id,
            'req': req, # Store request for context
            'issued_time': time.time(), # Record issue time to avoid immediate arrival detection
            'order_update_id': -1  # Start at -1, then increment on each update
        }

        # Issue first segment
        success = self._issue_path_segment(agv, self.active_paths[agv_id], first_issue=True)
        if success:
            self.agv_travel_status[agv_id] = {'status': 'moving', 'target_node': target_node}
        else:
             self.agv_travel_status[agv_id] = {'status': 'failed', 'reason': 'Issue Failed'}

    def _monitor_paths(self):
        with self.data_lock:
            # Copy keys to avoid modification during iteration if we delete
            for agv_id in list(self.active_paths.keys()):
                agv = self.latest_agvs.get(agv_id)
                if not agv: continue

                path_info = self.active_paths[agv_id]

                # Check if we need to issue more path
                self._check_and_update_path(agv, path_info)

                # Check arrival
                if self._check_arrival(agv, path_info):
                    agv_name = self._agv_name(agv)
                    self.log(f"AGV {agv_name} reached {path_info['target_node']}")
                    self.agv_travel_status[agv_id] = {
                        'status': 'reached',
                        'target_node': path_info['target_node']
                    }
                    del self.active_paths[agv_id]

    def _issue_path_segment(self, agv, path_info, first_issue=False):
        full_path = path_info['full_path']
        issued_count = path_info['issued_count']

        # Determine segment size
        remaining = len(full_path) - issued_count
        if remaining <= 0 and not first_issue: return False

        # Strategy: Send base_size base + horizon_size horizon
        base_size = min(self.base_size, remaining)
        horizon_size = min(self.horizon_size, remaining - base_size)

        seq_id = path_info['last_base_sequence_id']

        nodes = []
        edges = []

        current_idx = issued_count
        start_node_id = full_path[current_idx]['source'] if full_path else path_info['target_node'] # If empty path, start=target
        start_node = self._node_to_vda5050(start_node_id, seq_id, True)
        if not start_node:
            self.log(f"Node {start_node_id} not found in graph", 'ERROR')
            return False
        nodes.append(start_node)
        seq_id += 1

        # Base
        for i in range(base_size):
            edge_info = full_path[current_idx + i]
            edges.append(self._path_edge_to_vda5050(edge_info, seq_id, True))
            seq_id += 1
            target_node = self._node_to_vda5050(edge_info['target'], seq_id, True)
            if not target_node:
                self.log(f"Target node {edge_info['target']} not found in graph", 'ERROR')
                return False
            nodes.append(target_node)
            seq_id += 1

        last_base_seq_id = seq_id - 1

        # Horizon
        for i in range(horizon_size):
            edge_info = full_path[current_idx + base_size + i]
            edges.append(self._path_edge_to_vda5050(edge_info, seq_id, False))
            seq_id += 1
            target_node = self._node_to_vda5050(edge_info['target'], seq_id, False)
            if not target_node:
                self.log(f"Target node {edge_info['target']} not found in graph", 'ERROR')
                return False
            nodes.append(target_node)
            seq_id += 1

        # Update state
        path_info['issued_count'] += base_size
        path_info['last_base_sequence_id'] = last_base_seq_id

        order_update_id = path_info.get('order_update_id', -1) + 1
        path_info['order_update_id'] = order_update_id

        if first_issue:
            order_id = f"order_{time.time()}_{agv.name}"
            path_info['order_id'] = order_id
        else:
            order_id = path_info.get('order_id')

        self.log(f"AGV {agv.name} path issued: {order_id} {order_update_id}; released: {path_info['issued_count']}; length: {len(path_info['full_path'])}")
        order_data = {
            'orderId': order_id,
            'orderUpdateId': order_update_id,
            'nodes': nodes,
            'edges': edges
        }

        with self.commands_lock:
            self.generated_commands.append({
                'type': 'SEND_ORDER',
                'agv_id': agv.id,
                'order': order_data
            })

        return True

    def _check_and_update_path(self, agv, path_info):
        """
        Validate the active path before issuing another segment
        """

        path_order_id = path_info.get('order_id')
        if not path_order_id:

            return

        if not agv.orderId or agv.orderId != path_order_id:
            return

        # 2. Verify the last released edge sequence

        released_edges = [e for e in agv.edgeStates if e.get('released')]

        if not agv.newBaseRequest:
            # No released edges means execution has not started
            if not released_edges:
                return


            max_seq_id = max([e.get('sequenceId', -1) for e in released_edges])
            last_base_seq_id = path_info.get('last_base_sequence_id', -1)

            if abs(max_seq_id - last_base_seq_id) > 1:
                # A sequence mismatch indicates a stale path
                # Do not issue a new segment in this case
                return
        else:
            if path_info.get('last_base_sequence_id') > agv.last_node_sequence_id:
                print(f"AGV {agv.name}: last_base_sequence_id {path_info.get('last_base_sequence_id')} exceeds last_node_sequence_id {agv.last_node_sequence_id}")
                return

        # 3. After validation, decide whether to issue another segment
        remaining_base_edges = len(released_edges)


        # If running low on base edges, issue more
        if remaining_base_edges < 2 and path_info['issued_count'] < len(path_info['full_path']):
            self._issue_path_segment(agv, path_info, first_issue=False)

    def _check_arrival(self, agv, path_info):
        """
        Check whether the AGV reached its goal
        The following conditions are required:
        1. All segments were issued
        2. Enough time has elapsed since issuance
        3. The AGV accepted the order
        3.1. The order IDs match
        4. The AGV completed all released edges (newBaseRequest=True)
        5. No released edges remain
        6. The AGV reached the goal
        """
        full_path = path_info['full_path']
        issued_count = path_info['issued_count']

        # 1. All path segments must be issued
        if issued_count < len(full_path):
            return False

        # 2. Require at least 0.2 seconds after issuance
        issued_time = path_info.get('issued_time', 0)
        if time.time() - issued_time < 0.1:
            return False

        # 3. Ensure the AGV accepted an order
        if not agv.orderId:
            return False


        # Check the active order rather than a stale one
        path_order_id = path_info.get('order_id')
        if path_order_id and agv.orderId != path_order_id:
            return False

        # 4. For non-empty paths, complete every released edge
        # 'newBaseRequest' indicates the released edges are complete
        if not agv.newBaseRequest:
            return False

        # 5. Ensure no released edges remain
        released_edges = [e for e in agv.edgeStates if e.get('released')]
        if len(released_edges) > 0:
            return False

        # 6. Check the AGV position against the goal
        target_node = path_info['target_node']
        # Find the nearest node
        nearest_node = self._find_nearest_node(agv.position)

        # The nearest node is the goal
        if nearest_node == target_node:
            return True

        # Otherwise calculate distance to the goal
        # Treat a short distance as arrival
        target_node_data = self.graph.get_node(target_node)
        if target_node_data:
            pos = agv.position
            dist = ((pos['x'] - target_node_data['x'])**2 +
                    (pos['y'] - target_node_data['y'])**2)**0.5
            if dist < 0.2:  # 0.2 m tolerance
                return True

        return False

    def _find_nearest_node(self, pos):
        if not self.graph: return None
        min_dist = float('inf')
        best_node = None
        for node_id, node in self.graph.nodes.items():
            dist = (pos['x'] - node['x'])**2 + (pos['y'] - node['y'])**2
            if dist < min_dist:
                min_dist = dist
                best_node = node_id
        return best_node

    def _path_edge_to_vda5050(self, edge, seq_id, released):
        """Convert path edges to VDA5050"""
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

    def _node_to_vda5050(self, node_id, seq_id, released):
        """Convert nodes to VDA5050"""
        node = self.graph.get_node(node_id)
        if not node:
            return None
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
