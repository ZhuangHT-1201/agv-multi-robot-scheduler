import math
import random
from datetime import datetime
from typing import Dict, List, Any, Optional

class AGV:
    def __init__(self, data: Dict[str, Any]):
        """
        Initialize an AGV
        :param data: AGV property dictionary
        """
        self.id = data.get('id')
        self.name = data.get('name', f'AGV_{self.id}')


        self.position = data.get('position', {'x': 0.0, 'y': 0.0, 'z': 0.0})
        self.orientation = float(data.get('orientation', 0.0))
        self.velocity = {'x': 0.0, 'y': 0.0}
        self.current_speed = 0.0

        # Running state
        self.status = data.get('status', 'idle') # idle, working, error, charging
        self.battery = float(data.get('battery', 100.0))
        self.last_update_time = datetime.now()


        self.length = float(data.get('length', 0.7))
        self.width = float(data.get('width', 0.5))
        self.dimensions = data.get('dimensions', {'length': self.length, 'width': self.width})
        self.max_speed = float(data.get('max_speed', 1.0))
        self.max_acceleration = float(data.get('max_acceleration', 0.5))
        self.angular_velocity = float(data.get('angular_velocity', 1.0))


        self.battery_config = data.get('battery_config', None)


        self.collision_detection_enabled = data.get('collision_detection_enabled', True)
        self.collision_detection_distance = float(data.get('collision_detection_distance', 0.5))
        self.collision_safety_margin = float(data.get('collision_safety_margin', 0.3))
        self.collision_detected = False


        self.orderId: Optional[str] = data.get('orderId')
        self.orderUpdateId: int = int(data.get('orderUpdateId', 0))




        self.nodeStates: List[Dict] = data.get('nodeStates', data.get('nodes', []))
        self.edgeStates: List[Dict] = data.get('edgeStates', data.get('edges', []))


        self.current_task: Optional[Dict] = data.get('current_task')



        sim_state_data = data.get('sim_state', {})
        self.sim_state = {
            'dist': sim_state_data.get('dist', 0.0),
            'last_waited_node': sim_state_data.get('last_waited_node', None)
        }

        self.last_node_id = data.get('last_node_id', sim_state_data.get('last_node_id', None))
        self.last_node_sequence_id = data.get('last_node_sequence_id', sim_state_data.get('last_node_sequence_id', 0))

        self.distanceSinceLastNode: float = data.get('distanceSinceLastNode', sim_state_data.get('distanceSinceLastNode', 0.0))
        self.wait_until: Optional[float] = data.get('wait_until') # Timestamp for waiting
        self.newBaseRequest = data.get('newBaseRequest', False)
        if not self.nodeStates:
            self.newBaseRequest = True


        self.updated_at = data.get('updated_at', datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dictionary for API responses and persistence"""
        result = {
            'id': self.id,
            'name': self.name,
            'position': self.position,
            'orientation': self.orientation,
            'current_speed': self.current_speed,
            'status': self.status,
            'battery': self.battery,
            'length': self.length,
            'width': self.width,
            'dimensions': self.dimensions,
            'max_speed': self.max_speed,
            'max_acceleration': self.max_acceleration,
            'angular_velocity': self.angular_velocity,
            'nodeStates': self.nodeStates,
            'edgeStates': self.edgeStates,
            'current_task': self.current_task,
            'wait_until': self.wait_until,
            'orderId': self.orderId,
            'orderUpdateId': self.orderUpdateId,
            'sim_state': self.sim_state,
            'last_node_id': self.last_node_id,
            'last_node_sequence_id': self.last_node_sequence_id,
            'distanceSinceLastNode': self.distanceSinceLastNode,
            'newBaseRequest': self.newBaseRequest,
            'updated_at': self.updated_at,
            'collision_detection_enabled': self.collision_detection_enabled,
            'collision_detection_distance': self.collision_detection_distance,
            'collision_safety_margin': self.collision_safety_margin,
            'collision_detected': self.collision_detected
        }

        if self.battery_config is not None:
            result['battery_config'] = self.battery_config
        return result

    def update_physics(self, dt: float, graph: Any, action_configs: Dict, current_time: float, battery_config: Dict = None, agv_states: Dict = None) -> bool:
        """
        Advance AGV physics
        :param dt: time step
        :param graph: road-network graph
        :param action_configs: action configuration
        :param current_time: Current simulation time
        :param battery_config: battery configuration
        :param agv_states: dictionary of AGV states, used for collision detection
        """

        if battery_config is None:
            battery_config = {
                'chargeRate': 1.0,
                'idleConsumption': 0.1,
                'workingConsumption': 0.5
            }

        self._update_battery(dt, graph, battery_config)

        if self.status == 'error':
            return False


        if self.battery < 1.0:
            if self.status == 'working':
                self.status = 'error'
            return False


        if self.wait_until is not None:

            if current_time < self.wait_until:
                if self.status != 'working' and self.status != 'error':
                    self.status = 'working'
                return False
            else:
                self.wait_until = None

        if self.status != 'working':
            return False



        has_released_edge = False
        if self.edgeStates:
            has_released_edge = self.edgeStates[0].get('released', False)



        if not has_released_edge:
             return self._handle_zero_length_path(graph, action_configs, current_time)

        self.newBaseRequest = False


        return self._move_along_path(dt, graph, action_configs, current_time, agv_states)

    def _check_collision_ahead(self, agv_states: Dict, graph: Any) -> bool:
        """
        Detect AGVs ahead
        :param agv_states: dictionary of AGV states
        :param graph: road-network graph
        :return: TrueTrue means a collision risk requires stopping
        """
        if not self.collision_detection_enabled or not agv_states:
            return False


        if not self.edgeStates:
            return False


        my_x = self.position.get('x', 0.0)
        my_y = self.position.get('y', 0.0)


        current_edge = self.edgeStates[0]
        edge_angle = self._calculate_edge_angle(graph, current_edge['source'], current_edge['target'])
        if edge_angle is None:
            edge_angle = self.orientation
        cos_orientation = math.cos(edge_angle)
        sin_orientation = math.sin(edge_angle)


        detection_distance = self.collision_detection_distance
        forward_x = my_x + detection_distance * cos_orientation
        forward_y = my_y + detection_distance * sin_orientation


        for other_id, other_agv in agv_states.items():

            if other_id == self.id:
                continue


            other_x = other_agv.position.get('x', 0.0)
            other_y = other_agv.position.get('y', 0.0)


            dx = other_x - my_x
            dy = other_y - my_y
            distance_sq = dx * dx + dy * dy


            max_check_distance = detection_distance + self.collision_safety_margin + max(other_agv.length, other_agv.width) * 1.5
            if distance_sq > max_check_distance * max_check_distance:
                continue



            dot_product = dx * cos_orientation + dy * sin_orientation
            if dot_product < -0.1:
                continue


            if self._is_agv_in_forward_path_fast(other_x, other_y, my_x, my_y,
                                                  forward_x, forward_y,
                                                  self.width, other_agv.width):

                actual_distance = math.sqrt(distance_sq)

                min_safe_distance = self.collision_safety_margin + (self.length + other_agv.length) / 2

                if actual_distance < min_safe_distance:
                    return True

        return False

    def _is_agv_in_forward_path_fast(self, other_x: float, other_y: float,
                                      start_x: float, start_y: float,
                                      end_x: float, end_y: float,
                                      my_width: float, other_width: float) -> bool:
        """
        Check whether a point lies in the forward corridor
        Use point-to-segment distance with fewer allocations
        :param other_x, other_y: other AGV position
        :param start_x, start_y: path start (current position)
        :param end_x, end_y: path end at the detection distance
        :param my_width: Current AGVWidth
        :param other_width: other AGV width
        :return: TrueTrue means inside the corridor
        """

        dx = end_x - start_x
        dy = end_y - start_y


        length_sq = dx * dx + dy * dy
        if length_sq < 0.0001:
            dist_sq = (other_x - start_x) * (other_x - start_x) + (other_y - start_y) * (other_y - start_y)
            threshold_sq = (my_width / 2 + other_width / 2) * (my_width / 2 + other_width / 2)
            return dist_sq < threshold_sq


        t = ((other_x - start_x) * dx + (other_y - start_y) * dy) / length_sq


        if t < 0:
            t = 0
        elif t > 1:
            t = 1


        closest_x = start_x + t * dx
        closest_y = start_y + t * dy


        dist_x = other_x - closest_x
        dist_y = other_y - closest_y
        distance_sq = dist_x * dist_x + dist_y * dist_y


        path_width = (my_width + other_width) / 2

        return distance_sq < path_width * path_width

    def _move_along_path(self, dt: float, graph: Any, action_configs: Dict, current_time: float, agv_states: Dict = None) -> bool:
        """Advance along the path with acceleration and turning
        :param dt: time step
        :param graph: road-network graph
        :param action_configs: action configuration
        :param current_time: Current simulation time
        :param agv_states: dictionary of AGV states, used for collision detection
        """

        if not self.edgeStates:
            self.newBaseRequest = True
            return True

        current_edge = self.edgeStates[0]


        if not current_edge.get('released', False):
            self.newBaseRequest = True
            return False


        current_edge_seq_id = current_edge.get('sequenceId', 0)
        if self.nodeStates and self.nodeStates[0].get('sequenceId', -1) < current_edge_seq_id:
            self.nodeStates = [n for n in self.nodeStates if n.get('sequenceId', -1) >= current_edge_seq_id]

        edge_id = current_edge['id']


        edge_info = self._get_edge_info(graph, current_edge['source'], edge_id)
        if not edge_info:
            edge_info = current_edge

        edge_speed_limit = float(edge_info.get('max_speed', 1.0))
        target_speed = max(0.0, min(self.max_speed, edge_speed_limit))
        edge_len = float(edge_info.get('length', edge_info.get('cost', 1.0)))
        if edge_len <= 0.001:
            edge_len = 0.001


        SPEED_THRESHOLD = 0.05
        DIST_THRESHOLD = 0.1


        collision_detected = self._check_collision_ahead(agv_states, graph)
        self.collision_detected = collision_detected

        if collision_detected:

            if self.current_speed > SPEED_THRESHOLD:

                new_speed = self.current_speed - self.max_acceleration * dt
                self.current_speed = max(0.0, new_speed)

                if self.current_speed < SPEED_THRESHOLD:
                    self.current_speed = 0.0
            else:

                self.current_speed = 0.0


            return True


        if self.current_speed < SPEED_THRESHOLD:
            current_node_id = current_edge['source']
            next_edge = current_edge

            if next_edge and next_edge.get('released', False):

                next_edge_angle = self._calculate_edge_angle(graph, next_edge['source'], next_edge['target'])
                if next_edge_angle is not None:

                    angle_diff = next_edge_angle - self.orientation

                    while angle_diff > math.pi:
                        angle_diff -= 2 * math.pi
                    while angle_diff < -math.pi:
                        angle_diff += 2 * math.pi


                    if abs(angle_diff) > math.radians(5):

                        max_rotation = self.angular_velocity * dt
                        if abs(angle_diff) <= max_rotation:
                            self.orientation = next_edge_angle
                        else:
                            if angle_diff > 0:
                                self.orientation += max_rotation
                            else:
                                self.orientation -= max_rotation

                        while self.orientation >= 2 * math.pi:
                            self.orientation -= 2 * math.pi
                        while self.orientation < 0:
                            self.orientation += 2 * math.pi


                        self.current_speed = 0.0
                        return True



        distance_to_stop = None
        target_edge_index = -1


        last_released_index = -1
        for i in range(len(self.edgeStates)):
            if self.edgeStates[i].get('released', False):
                last_released_index = i

        if last_released_index >= 0:

            for i in range(len(self.edgeStates) - 1):
                edge1 = self.edgeStates[i]
                edge2 = self.edgeStates[i + 1]


                if not edge1.get('released', False) or not edge2.get('released', False):
                    break


                angle_diff = self._calculate_angle_between_edges(
                    graph,
                    edge1['source'], edge1['target'],
                    edge2['source'], edge2['target']
                )

                if angle_diff is not None and math.degrees(angle_diff) > 30:

                    target_edge_index = i
                    break


            if target_edge_index == -1:
                target_edge_index = last_released_index


            accumulated_dist = edge_len - self.sim_state['dist']
            if target_edge_index == 0:

                distance_to_stop = accumulated_dist
            else:

                for i in range(1, target_edge_index + 1):
                    if i < len(self.edgeStates):
                        edge = self.edgeStates[i]
                        if edge.get('released', False):
                            edge_info = self._get_edge_info(graph, edge['source'], edge['id'])
                            if not edge_info:
                                edge_info = edge
                            edge_full_len = float(edge_info.get('length', edge_info.get('cost', 1.0)))
                            accumulated_dist += edge_full_len
                distance_to_stop = accumulated_dist


        if distance_to_stop is not None:

            decel_dist = (self.current_speed ** 2) / (2 * self.max_acceleration) if self.max_acceleration > 0 else 0


            if distance_to_stop <= decel_dist + 0.1:

                self.current_speed = max(0.06, min(distance_to_stop, self.current_speed - self.max_acceleration * dt))
            else:

                if self.current_speed < target_speed:
                    self.current_speed = min(target_speed, self.current_speed + self.max_acceleration * dt)
                elif self.current_speed > target_speed:
                    self.current_speed = max(target_speed, self.current_speed - self.max_acceleration * dt)
        else:

            if self.current_speed < target_speed:
                self.current_speed = min(target_speed, self.current_speed + self.max_acceleration * dt)
            elif self.current_speed > target_speed:
                self.current_speed = max(target_speed, self.current_speed - self.max_acceleration * dt)


        if self.current_speed > SPEED_THRESHOLD:
            speed_with_noise = self.current_speed + random.gauss(0, 0.05)

            speed_with_noise = max(0.0, speed_with_noise)
        else:

            speed_with_noise = 0.0

        dist_to_move = speed_with_noise * dt
        self.sim_state['dist'] += dist_to_move

        self.distanceSinceLastNode += dist_to_move

        last_node = self.nodeStates[-1] if len(self.nodeStates) > 0 else None


        distance_to_stop -= dist_to_move
        while self.sim_state['dist'] >= edge_len or (distance_to_stop < DIST_THRESHOLD and abs(self.sim_state['dist'] - edge_len) < DIST_THRESHOLD/2):

            target_node_id = current_edge['target']
            if distance_to_stop < DIST_THRESHOLD:
                self.current_speed = 0.0


            target_node_order_data = None
            if len(self.nodeStates) > 0 and self.nodeStates[0]['nodeId'] == target_node_id:
                target_node_order_data = self.nodeStates[0]
            else:
                 target_node_order_data = self._find_node_in_order(target_node_id)

            target_node_graph_data = graph.get_node(target_node_id)


            if self._check_node_action(target_node_order_data, target_node_graph_data, action_configs, current_time):

                self.sim_state['dist'] = edge_len
                self.current_speed = 0.0
                return True


            self.sim_state['dist'] -= edge_len
            if self.sim_state['dist'] < 0:
                self.sim_state['dist'] = 0


            if target_node_order_data:
                self.last_node_id = target_node_order_data['nodeId']
                self.last_node_sequence_id = target_node_order_data['sequenceId']

                self.distanceSinceLastNode = 0.0


            if self.nodeStates:
                self.nodeStates.pop(0)
            if self.edgeStates:
                self.edgeStates.pop(0)


            if not self.edgeStates:
                self.sim_state['dist'] = 0
                self.current_speed = 0.0
                self.newBaseRequest = True

                if target_node_graph_data:
                    self.position = {'x': target_node_graph_data['x'], 'y': target_node_graph_data['y'], 'z': target_node_graph_data.get('z', 0)}
                break

            current_edge = self.edgeStates[0]
            if not current_edge.get('released', False):
                self.sim_state['dist'] = 0
                self.current_speed = 0.0
                self.newBaseRequest = True
                break


            edge_info = self._get_edge_info(graph, current_edge['source'], current_edge['id'])
            if not edge_info: edge_info = current_edge
            edge_len = float(edge_info.get('length', edge_info.get('cost', 1.0)))


        if self.edgeStates:
            if self.edgeStates[0].get('released', False):
                self._update_position(graph, self.edgeStates[0], update_orientation=distance_to_stop>0.15)
            else:
                node = graph.get_node(self.edgeStates[0]['source'])
                if node:
                    self.position = {'x': node['x'], 'y': node['y'], 'z': node.get('z', 0)}
        elif last_node:
             node = graph.get_node(last_node['nodeId'])
             if node:
                 self.position = {'x': node['x'], 'y': node['y'], 'z': node.get('z', 0)}

        return True

    def _get_edge_info(self, graph, source_id, edge_id):
        neighbors = graph.get_neighbors(source_id)
        for n in neighbors:
            if n['id'] == edge_id:
                return n
        return None

    def _calculate_edge_angle(self, graph, source_id, target_id):
        """Calculate edge heading in radians"""
        source_node = graph.get_node(source_id)
        target_node = graph.get_node(target_id)
        if not source_node or not target_node:
            return None
        dx = target_node['x'] - source_node['x']
        dy = target_node['y'] - source_node['y']
        if dx == 0 and dy == 0:
            return None
        return math.atan2(dy, dx)

    def _calculate_angle_between_edges(self, graph, edge1_source, edge1_target, edge2_source, edge2_target):
        """Calculate the angle between two edges"""
        angle1 = self._calculate_edge_angle(graph, edge1_source, edge1_target)
        angle2 = self._calculate_edge_angle(graph, edge2_source, edge2_target)
        if angle1 is None or angle2 is None:
            return None


        angle_diff = abs(angle2 - angle1)

        if angle_diff > math.pi:
            angle_diff = 2 * math.pi - angle_diff
        return angle_diff

    def _find_node_in_order(self, node_id, min_sequence_id=0):
        """Find a node in the current order state"""

        fallback_node = None
        for node in self.nodeStates:
            if node['nodeId'] == node_id:
                if node.get('sequenceId', -1) >= min_sequence_id:
                    return node
                elif fallback_node is None:
                    fallback_node = node

        # if fallback_node:

        return fallback_node

    def _check_node_action(self, order_node, graph_node, action_configs, current_time) -> bool:
        """Trigger a node action; True means the AGV must wait"""

        actions = []
        if order_node:
            actions.extend(order_node.get('actions', []))


        if graph_node and graph_node.get('action'):

             actions.append({'actionType': graph_node.get('action'), 'blocking': True})

        node_id = order_node['nodeId'] if order_node else (graph_node['id'] if graph_node else None)
        if not node_id: return False

        current_seq_id = order_node.get('sequenceId') if order_node else None

        if self.sim_state.get('last_waited_node') == node_id:
            if current_seq_id is None or self.sim_state.get('last_waited_seq_id') == current_seq_id:
                return False

        for action in actions:
            action_type = action.get('actionType')
            if action_type and action_configs and action_type in action_configs:
                config = action_configs[action_type]
                wait_duration = self._calculate_wait_duration(config)

                if wait_duration > 0:
                    self.wait_until = current_time + wait_duration
                    self.sim_state['last_waited_node'] = node_id
                    if current_seq_id is not None:
                        self.sim_state['last_waited_seq_id'] = current_seq_id
                    return True

        return False

    def _calculate_wait_duration(self, config):
        if config['type'] == 'fixed':
            return float(config.get('value', 0))
        elif config['type'] == 'random':
            import random
            return random.uniform(float(config.get('min', 0)), float(config.get('max', 0)))
        return 0.0

    def _is_at_charging_station(self, graph: Any) -> bool:
        """Check whether the AGV is on a charging station"""
        if not self.position:
            return False

        agv_x = self.position.get('x', 0)
        agv_y = self.position.get('y', 0)
        agv_z = self.position.get('z', 0)


        for node_id, node in graph.nodes.items():
            if node.get('type') == 'charging_station':

                node_z = node.get('z', 0)
                if abs(node_z - agv_z) > 0.1:
                    continue


                node_x = node.get('x', 0)
                node_y = node.get('y', 0)
                dx = abs(agv_x - node_x)
                dy = abs(agv_y - node_y)


                if dx < 0.2 and dy < 0.2:
                    return True

        return False

    def _update_battery(self, dt: float, graph: Any, battery_config: Dict):
        """Update battery
        Prefer AGV-specific battery settings, then global settings
        """

        effective_config = self.battery_config if self.battery_config is not None else battery_config

        charge_rate = float(effective_config.get('chargeRate', 1.0))
        idle_consumption = float(effective_config.get('idleConsumption', 0.1))
        working_consumption = float(effective_config.get('workingConsumption', 0.5))


        is_charging = self._is_at_charging_station(graph)
        if is_charging and self.status != 'working':

            self.battery = min(100.0, self.battery + charge_rate * dt)
            if self.status != 'charging':
                self.status = 'charging'
        else:

            if self.status == 'working':
                consumption = working_consumption
            else:
                consumption = idle_consumption


            if self.battery >= 1.0:
                self.battery = max(0.0, self.battery - consumption * dt)
            else:
                self.battery = max(0.0, min(1.0, self.battery))

    def _update_position(self, graph, current_edge, update_orientation=True):
        """Update pose from the current edge and travelled distance"""
        path_segment = current_edge
        source_node = graph.get_node(path_segment['source'])
        target_node = graph.get_node(path_segment['target'])

        if source_node and target_node:
            edge_info = self._get_edge_info(graph, path_segment['source'], path_segment['id'])
            if not edge_info: edge_info = path_segment

            logic_len = float(edge_info.get('length', 1.0))
            if logic_len <= 0.001: logic_len = 0.001

            t = min(1.0, max(0.0, self.sim_state['dist'] / logic_len))

            new_x = source_node['x'] + (target_node['x'] - source_node['x']) * t
            new_y = source_node['y'] + (target_node['y'] - source_node['y']) * t

            self.position = {
                'x': new_x,
                'y': new_y,
                'z': source_node.get('z', 0)
            }


            if update_orientation:
                dx = target_node['x'] - source_node['x']
                dy = target_node['y'] - source_node['y']
                if dx != 0 or dy != 0:
                    self.orientation = math.atan2(dy, dx)

    def _handle_zero_length_path(self, graph, action_configs, current_time):
        """Handle an in-place action"""

        if self.nodeStates and self.nodeStates[0].get('released', False):
            target_node = self.nodeStates[0]
            graph_node = graph.get_node(target_node['nodeId'])


            if graph_node:
                self.position = {'x': graph_node['x'], 'y': graph_node['y'], 'z': graph_node.get('z', 0)}


            if self._check_node_action(target_node, graph_node, action_configs, current_time):

                return True



            self.nodeStates.pop(0)


            if target_node:
                self.last_node_id = target_node['nodeId']
                self.last_node_sequence_id = target_node.get('sequenceId', 0)

                self.distanceSinceLastNode = 0.0

        if not self.newBaseRequest:
            self.newBaseRequest = True
            return True
        return False

    def accept_order(self, order_data: Dict[str, Any]) -> bool:
        """
        Accept and validate a VDA5050 order
        """
        try:
            orderId = order_data.get('orderId')
            orderUpdateId = int(order_data.get('orderUpdateId', 0))
            new_nodes = order_data.get('nodes', [])
            new_edges = order_data.get('edges', [])


            if self.orderId == orderId:
                if orderUpdateId <= self.orderUpdateId:
                    print(f"AGV {self.id}: ignoring stale or duplicate update ID {orderUpdateId}; current={self.orderUpdateId}")
                    return False

            is_new_order = (self.orderId != orderId)


            cleaned_nodes = []
            for n in new_nodes:
                cleaned_nodes.append({
                    'nodeId': n.get('nodeId'),
                    'sequenceId': n.get('sequenceId'),
                    'released': n.get('released', False),
                    'actions': n.get('actions', []),
                    'nodePosition': n.get('nodePosition')
                })

            cleaned_edges = []
            for e in new_edges:
                cleaned_edges.append({
                    'edgeId': e.get('edgeId'),
                    'sequenceId': e.get('sequenceId'),
                    'released': e.get('released', False),
                    'startNodeId': e.get('startNodeId'),
                    'endNodeId': e.get('endNodeId'),

                    'id': e.get('edgeId'),
                    'source': e.get('startNodeId'),
                    'target': e.get('endNodeId'),
                    'actions': e.get('actions', []),
                    'max_speed': e.get('maxSpeed', e.get('max_speed')),
                    'length': e.get('distance', e.get('length'))
                })

            # 3. Update state
            if is_new_order:
                self.nodeStates = cleaned_nodes
                self.edgeStates = cleaned_edges
                self.sim_state = {
                    'dist': 0.0,
                    'last_waited_node': None
                }
                self.last_node_id = None
                self.last_node_sequence_id = 0
                self.distanceSinceLastNode = 0.0
                self.newBaseRequest = False
            else:




                self.nodeStates = [n for n in self.nodeStates if n.get('released')]
                self.edgeStates = [e for e in self.edgeStates if e.get('released')]





                max_node_seq = max([n['sequenceId'] for n in self.nodeStates]) if self.nodeStates else -1
                max_edge_seq = max([e['sequenceId'] for e in self.edgeStates]) if self.edgeStates else -1

                for n in cleaned_nodes:
                    if n['sequenceId'] > max_node_seq:
                        self.nodeStates.append(n)

                for e in cleaned_edges:
                    if e['sequenceId'] > max_edge_seq:
                        self.edgeStates.append(e)


                print(f"AGV {self.name} path updated; last_node={self.last_node_sequence_id}, node={cleaned_nodes[0]['sequenceId']}, edge={cleaned_edges[0]['sequenceId']}, distance={self.sim_state.get('dist', 0)}, newBaseRequest={self.newBaseRequest}")

                self.newBaseRequest = False

            self.orderId = orderId
            self.orderUpdateId = orderUpdateId


            if self.status != 'error':
                self.status = 'working'

            self.updated_at = datetime.now().isoformat()

            return True
        except Exception as e:
            print(f"Error accepting order for AGV {self.id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def cancel_order(self):
        """Cancel the current task"""
        self.nodeStates = []
        self.edgeStates = []
        self.status = 'idle'
        self.current_task = None
        self.orderId = None
        self.orderUpdateId = 0

    def clear_paths_and_reset(self):
        """
        Clear the path and reset navigation state
        """
        self.nodeStates = []
        self.edgeStates = []
        self.orderId = None
        self.orderUpdateId = 0
        self.newBaseRequest = False
        self.sim_state = {'dist': 0.0, 'last_waited_node': None}
        self.last_node_id = None
        self.last_node_sequence_id = 0
        self.distanceSinceLastNode = 0.0
        self.updated_at = datetime.now().isoformat()
