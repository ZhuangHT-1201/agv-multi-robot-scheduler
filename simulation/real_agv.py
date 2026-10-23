"""Real AGV adapter supporting both simulated and physical vehicles.

Real AGVs extend the simulator vehicle and override transport methods.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime
from simulation.agv import AGV


try:
    from vda5050.structs import Order as VDAOrder, Header, Node as VDANode, Edge as VDAEdge, NodePosition, Action as VDAAction, State as VDAState
    VDA5050_AVAILABLE = True
except ImportError:
    VDA5050_AVAILABLE = False
    VDAOrder = None
    Header = None
    VDANode = None
    VDAEdge = None
    NodePosition = None
    VDAAction = None
    VDAState = None


class RealAGV(AGV):
    """Real AGV adapter that delegates state changes to MQTT"""

    def __init__(self, data: Dict[str, Any], mqtt_client=None):
        """
        Initialize a real AGV

        Args:
            data: AGV property dictionary
            mqtt_client: VDA5050 optional MQTT client
        """
        super().__init__(data)

        self.serial_number = data.get('serial_number', self.name)

        self.manufacturer = data.get('manufacturer', 'agv-demo')

        self.mqtt_client = mqtt_client

        self.mode = 'real'

    def _convert_to_vda5050_order(self, order_data: Dict[str, Any]) -> VDAOrder:
        """Convert an internal order to VDA5050"""
        if not VDA5050_AVAILABLE:
            raise ImportError("VDA5050 module is not installed")

        # Create header.
        header = Header.create(self.manufacturer, self.serial_number)


        nodes = []
        for n in order_data.get('nodes', []):
            node_position = None
            if 'nodePosition' in n:
                np = n['nodePosition']
                node_position = NodePosition(
                    x=float(np.get('x', 0.0)),
                    y=float(np.get('y', 0.0)),
                    theta=float(np.get('theta', 0.0)),
                    mapId=str(np.get('mapId', 'default_map')),
                    allowedDeviationXY=np.get('allowedDeviationXY'),
                    allowedDeviationTheta=np.get('allowedDeviationTheta')
                )

            actions = []
            for a in n.get('actions', []):
                actions.append(VDAAction(
                    actionId=a.get('actionId', ''),
                    actionType=a.get('actionType', ''),
                    blockingType=a.get('blockingType', 'NONE'),
                    actionDescription=a.get('actionDescription'),
                    actionParameters=None
                ))

            nodes.append(VDANode(
                nodeId=n.get('nodeId', ''),
                sequenceId=int(n.get('sequenceId', 0)),
                released=bool(n.get('released', False)),
                nodePosition=node_position,
                description=n.get('description'),
                actions=actions
            ))


        edges = []
        for e in order_data.get('edges', []):
            actions = []
            for a in e.get('actions', []):
                actions.append(VDAAction(
                    actionId=a.get('actionId', ''),
                    actionType=a.get('actionType', ''),
                    blockingType=a.get('blockingType', 'NONE'),
                    actionDescription=a.get('actionDescription'),
                    actionParameters=None
                ))

            edges.append(VDAEdge(
                edgeId=e.get('edgeId', ''),
                sequenceId=int(e.get('sequenceId', 0)),
                startNodeId=e.get('startNodeId', ''),
                endNodeId=e.get('endNodeId', ''),
                released=bool(e.get('released', False)),
                maxSpeed=e.get('maxSpeed'),
                description=e.get('description'),
                actions=actions
            ))

        return VDAOrder(
            header=header,
            orderId=order_data.get('orderId', ''),
            orderUpdateId=int(order_data.get('orderUpdateId', 0)),
            nodes=nodes,
            edges=edges,
            zoneSetId=order_data.get('zoneSetId')
        )

    def accept_order(self, order_data: Dict[str, Any]) -> bool:
        """
        Real AGVs receive orders through MQTT
        Send orders through MQTT
        """
        if not self.mqtt_client:
            print(f"Real AGV {self.id} has no MQTT client")
            return False

        if not self.mqtt_client.is_connected:
            print(f"MQTT is disconnected; cannot send an order to AGV {self.id}")
            return False

        try:

            vda_order = self._convert_to_vda5050_order(order_data)


            if self.mqtt_client.send_order(self.serial_number, vda_order):

                self.orderId = order_data.get('orderId')
                self.orderUpdateId = int(order_data.get('orderUpdateId', 0))
                self.updated_at = datetime.now().isoformat()
                print(f"Order sent to real AGV {self.id} over MQTT ({self.serial_number})")
                return True
            else:
                print(f"Failed to send an order to real AGV {self.id}")
                return False
        except Exception as e:
            print(f"Error sending order to real AGV {self.id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def update_physics(self, dt: float, graph: Any, action_configs: Dict,
                      current_time: float, battery_config: Dict = None) -> bool:
        """
        Real AGVs are updated by MQTT state messages
        Return False because no local physics is required
        """
        return False

    def update_from_state(self, state: 'VDAState'):
        """Update AGV state from a VDA5050 State message"""
        try:

            if state.agvPosition:
                pos = state.agvPosition
                self.position = {
                    'x': float(pos.x),
                    'y': float(pos.y),
                    'z': 5.0
                }
                self.orientation = float(pos.theta)


            if state.batteryState:
                battery = state.batteryState
                self.battery = float(battery.batteryCharge)

                if battery.charging:
                    if self.status != 'working':
                        self.status = 'charging'


            self.orderId = state.orderId
            self.orderUpdateId = int(state.orderUpdateId)


            if state.lastNodeId:
                self.last_node_id = state.lastNodeId
                self.last_node_sequence_id = int(state.lastNodeSequenceId)


            self.nodeStates = []
            for ns in state.nodeStates:
                self.nodeStates.append({
                    'nodeId': ns.nodeId,
                    'sequenceId': int(ns.sequenceId),
                    'released': bool(ns.released),
                    'nodeDescription': ns.nodeDescription,
                    'nodePosition': ns.nodePosition
                })

            self.edgeStates = []
            for es in state.edgeStates:
                edge_dict = {
                    'edgeId': es.edgeId,
                    'sequenceId': int(es.sequenceId),
                    'released': bool(es.released),
                    'edgeDescription': es.edgeDescription,

                    'id': es.edgeId,
                    'source': None,
                    'target': None,
                    'trajectory': es.trajectory
                }

                if self.nodeStates:

                    seq_id = edge_dict['sequenceId']
                    for i, node in enumerate(self.nodeStates):
                        if node.get('sequenceId') == seq_id - 1:
                            edge_dict['source'] = node.get('nodeId')
                        if node.get('sequenceId') == seq_id + 1:
                            edge_dict['target'] = node.get('nodeId')

                self.edgeStates.append(edge_dict)


            if state.newBaseRequest is not None:
                self.newBaseRequest = bool(state.newBaseRequest)


            if state.distanceSinceLastNode is not None:

                self.distanceSinceLastNode = float(state.distanceSinceLastNode)

                if not hasattr(self, 'sim_state'):
                    self.sim_state = {}
                self.sim_state['dist'] = float(state.distanceSinceLastNode)


            if state.driving:

                if self.status != 'charging':
                    self.status = 'working'
            else:

                if self.status != 'charging':
                    self.status = 'idle'


            if state.paused is not None:
                paused = state.paused
                if paused and self.status == 'working':
                    self.status = 'idle'


            operating_mode = state.operatingMode
            if operating_mode == 'SERVICE' or operating_mode == 'MANUAL':
                self.status = 'error'
            elif operating_mode == 'TEACHIN':

                if self.status == 'working':
                    self.status = 'idle'


            if state.safetyState:
                safety = state.safetyState
                e_stop = safety.eStop
                field_violation = safety.fieldViolation


                if e_stop != 'NONE' or field_violation:
                    self.status = 'error'


            errors = state.errors
            if errors:
                fatal_errors = [e for e in errors if e.errorLevel == 'FATAL']
                if fatal_errors:
                    self.status = 'error'

                    for error in fatal_errors:
                        print(f"AGV {self.id} fatal error: {error.errorType} - {error.errorDescription}")


            if state.zoneSetId:

                pass


            self.updated_at = datetime.now().isoformat()
            self.last_update_time = datetime.now()

        except Exception as e:
            print(f"Error updating RealAGV {self.id} from state: {e}")
            import traceback
            traceback.print_exc()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize additional real-AGV fields"""
        result = super().to_dict()
        result['mode'] = self.mode
        result['serial_number'] = self.serial_number
        result['manufacturer'] = self.manufacturer
        return result


def create_agv(agv_id: str, agv_data: Dict[str, Any], mqtt_client=None, state_callback=None) -> AGV:
    """
    Create a simulated or real AGV from the MQTT configuration

    Args:
        agv_id: AGV ID
        agv_data: AGV data dictionary
        mqtt_client: MQTT client (present for real AGVs)
        state_callback: state callback receiving (agv_id, state_dict)

    Returns:
        Simulated or real AGV instance
    """

    if mqtt_client is not None:
        # real AGV mode
        agv = RealAGV(agv_data, mqtt_client)


        if mqtt_client.is_connected and state_callback is not None:
            def make_callback(aid):
                def callback(state):

                    try:
                        state_callback(aid, state)
                    except Exception as e:
                        print(f"Error in state callback for AGV {aid}: {e}")
                        import traceback
                        traceback.print_exc()
                return callback

            if hasattr(agv, 'serial_number'):
                mqtt_client.subscribe_to_agv_state(agv.serial_number, make_callback(agv_id))
                print(f"Subscribed to state updates for real AGV {agv_id} ({agv.serial_number})")

        return agv
    else:

        return AGV(agv_data)
