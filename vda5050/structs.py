"""VDA5050 Data Structures for Python"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timezone
import json


def to_dict(obj, remove_none: bool = True) -> Dict[str, Any]:
    """Convert dataclass to dictionary, optionally removing None values"""
    result = asdict(obj)
    if remove_none:
        return _remove_none_recursive(result)
    return result


def _remove_none_recursive(d: Any) -> Any:
    """Recursively remove None values from dictionaries"""
    if isinstance(d, dict):
        return {k: _remove_none_recursive(v) for k, v in d.items() if v is not None}
    elif isinstance(d, list):
        return [_remove_none_recursive(item) for item in d]
    else:
        return d


# Common Header
@dataclass
class Header:
    """VDA5050 Message Header"""
    headerId: int
    timestamp: str
    version: str
    manufacturer: str
    serialNumber: str

    @staticmethod
    def create(manufacturer: str, serialNumber: str, version: str = "2.0.0") -> "Header":
        """Create a new header with auto-generated timestamp and ID"""
        import time
        return Header(
            headerId=int(time.time() * 1000) % 2**32,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
            version=version,
            manufacturer=manufacturer,
            serialNumber=serialNumber
        )


# 6.8 Actions
@dataclass
class ActionParameter:
    """Action Parameter"""
    key: str
    value: Union[bool, int, float, str, List, Dict]  # Can be various types


@dataclass
class Action:
    """VDA5050 Action"""
    actionId: str
    actionType: str
    blockingType: str  # NONE, SOFT, HARD
    actionDescription: Optional[str] = None
    actionParameters: Optional[List[ActionParameter]] = None


# 6.6 Topic: "order"
@dataclass
class NodePosition:
    """Node Position Information"""
    x: float
    y: float
    theta: float
    mapId: str
    allowedDeviationXY: Optional[float] = None
    allowedDeviationTheta: Optional[float] = None


@dataclass
class Node:
    """VDA5050 Node"""
    nodeId: str
    sequenceId: int
    released: bool
    actions: List[Action] = field(default_factory=list)
    nodePosition: Optional[NodePosition] = None
    description: Optional[str] = None


@dataclass
class ControlPoint:
    """Trajectory Control Point"""
    x: float
    y: float
    weight: float


@dataclass
class Trajectory:
    """Trajectory Definition"""
    degree: float
    knotVector: List[float]
    controlPoints: List[ControlPoint]


@dataclass
class Corridor:
    """Corridor Definition"""
    leftWidth: float
    rightWidth: float
    corridorRefPoint: str


@dataclass
class Edge:
    """VDA5050 Edge"""
    edgeId: str
    sequenceId: int
    startNodeId: str
    endNodeId: str
    released: bool
    actions: List[Action] = field(default_factory=list)
    description: Optional[str] = None
    maxSpeed: Optional[float] = None
    maxHeight: Optional[float] = None
    minHeight: Optional[float] = None
    orientation: Optional[float] = None
    orientationType: Optional[str] = None  # GLOBAL, TANGENTIAL
    direction: Optional[str] = None
    rotationAllowed: Optional[bool] = None
    maxRotationSpeed: Optional[float] = None
    trajectory: Optional[Trajectory] = None
    length: Optional[float] = None
    corridor: Optional[Corridor] = None


@dataclass
class Order:
    """VDA5050 Order Message"""
    header: Header
    orderId: str
    orderUpdateId: int
    nodes: List[Node]
    edges: List[Edge]
    zoneSetId: Optional[str] = None


# 6.9 Topic: "instantActions"
@dataclass
class InstantActions:
    """VDA5050 Instant Actions Message"""
    header: Header
    actions: List[Action]


# 6.10 Topic: "state"
@dataclass
class AgvPosition:
    """AGV Position Information"""
    positionInitialized: bool
    x: float
    y: float
    theta: float
    mapId: str
    localizationScore: Optional[float] = None
    deviationRange: Optional[float] = None
    mapDescription: Optional[str] = None


@dataclass
class Velocity:
    """Velocity Information"""
    vx: Optional[float] = None
    vy: Optional[float] = None
    omega: Optional[float] = None


@dataclass
class BoundingBoxReference:
    """Bounding Box Reference Point"""
    x: float
    y: float
    z: float
    theta: Optional[float] = None


@dataclass
class LoadDimensions:
    """Load Dimensions"""
    length: float
    width: float
    height: Optional[float] = None


@dataclass
class Load:
    """Load Information"""
    loadId: Optional[str] = None
    loadType: Optional[str] = None
    loadPosition: Optional[str] = None
    boundingBoxReference: Optional[BoundingBoxReference] = None
    loadDimensions: Optional[LoadDimensions] = None
    weight: Optional[float] = None


@dataclass
class ActionState:
    """Action State"""
    actionId: str
    actionStatus: str  # WAITING, INITIALIZING, RUNNING, FINISHED, FAILED
    actionType: Optional[str] = None
    resultDescription: Optional[str] = None


@dataclass
class BatteryState:
    """Battery State"""
    batteryCharge: float
    charging: bool
    batteryVoltage: Optional[float] = None
    batteryHealth: Optional[int] = None
    reach: Optional[float] = None


@dataclass
class SafetyState:
    """Safety State"""
    eStop: str  # AUTOACK, MANUAL, REMOTE, NONE
    fieldViolation: bool


@dataclass
class ErrorReference:
    """Error Reference"""
    referenceKey: str
    referenceValue: str


@dataclass
class ErrorEntry:
    """Error Entry"""
    errorType: str
    errorLevel: str  # WARNING, FATAL
    errorReferences: Optional[List[ErrorReference]] = None
    errorDescription: Optional[str] = None
    errorHint: Optional[str] = None


@dataclass
class InfoReference:
    """Info Reference"""
    referenceKey: str
    referenceValue: str


@dataclass
class InfoEntry:
    """Info Entry"""
    infoType: str
    infoLevel: str  # DEBUG, INFO
    infoReferences: Optional[List[InfoReference]] = None
    infoDescription: Optional[str] = None


@dataclass
class Map:
    """Map Information"""
    mapId: str
    mapVersion: str
    mapStatus: str  # ENABLED, DISABLED
    mapDescription: Optional[str] = None


@dataclass
class NodeState:
    """Node State"""
    nodeId: str
    sequenceId: int
    released: bool
    nodeDescription: Optional[str] = None
    nodePosition: Optional[NodePosition] = None


@dataclass
class EdgeState:
    """Edge State"""
    edgeId: str
    sequenceId: int
    released: bool
    edgeDescription: Optional[str] = None
    trajectory: Optional[Trajectory] = None


@dataclass
class State:
    """VDA5050 State Message"""
    header: Header
    orderId: str
    orderUpdateId: int
    lastNodeId: str
    lastNodeSequenceId: int
    nodeStates: List[NodeState]
    edgeStates: List[EdgeState]
    agvPosition: AgvPosition
    actionStates: List[ActionState]
    batteryState: BatteryState
    operatingMode: str  # AUTOMATIC, SEMIAUTOMATIC, MANUAL, SERVICE, TEACHIN
    safetyState: SafetyState
    errors: List[ErrorEntry]
    information: List[InfoEntry]
    driving: bool
    maps: Optional[List[Map]] = None
    zoneSetId: Optional[str] = None
    velocity: Optional[Velocity] = None
    loads: Optional[List[Load]] = None
    paused: Optional[bool] = None
    newBaseRequest: Optional[bool] = None
    distanceSinceLastNode: Optional[float] = None


# 6.14 Topic: "connection"
@dataclass
class Connection:
    """VDA5050 Connection Message"""
    header: Header
    connectionState: str  # ONLINE, OFFLINE, CONNECTIONBROKEN


# 6.15 Topic: "factsheet" - Simplified structures
@dataclass
class TypeSpecification:
    """Type Specification"""
    seriesName: str
    agvKinematic: str  # DIFF, OMNI, THREEWHEEL
    agvClass: str  # FORKLIFT, CONVEYOR, TUGGER, CARRIER
    maxLoadMass: float
    localizationTypes: List[str]
    navigationTypes: List[str]
    seriesDescription: Optional[str] = None


@dataclass
class PhysicalParameters:
    """Physical Parameters"""
    speedMin: float
    speedMax: float
    accelerationMax: float
    decelerationMax: float
    heightMin: float
    heightMax: float
    width: float
    length: float
    angularSpeedMin: Optional[float] = None
    angularSpeedMax: Optional[float] = None


# Helper functions for JSON serialization
def from_json(data: Union[str, Dict], cls):
    """Deserialize JSON to dataclass"""
    if isinstance(data, str):
        data = json.loads(data)
    return _dict_to_dataclass(data, cls)


def _dict_to_dataclass(data: Dict, cls):
    """Convert dictionary to dataclass recursively"""
    if not hasattr(cls, '__dataclass_fields__'):
        return data

    field_types = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs = {}

    for key, value in data.items():
        if key not in field_types:
            continue

        field_type = field_types[key]

        # Handle Optional types
        if hasattr(field_type, '__origin__') and field_type.__origin__ is Union:
            args = field_type.__args__
            if type(None) in args:
                if value is None:
                    kwargs[key] = None
                    continue
                field_type = next(arg for arg in args if arg is not type(None))

        # Handle List types
        if hasattr(field_type, '__origin__') and field_type.__origin__ is list:
            item_type = field_type.__args__[0]
            if hasattr(item_type, '__dataclass_fields__'):
                kwargs[key] = [_dict_to_dataclass(item, item_type) for item in value]
            else:
                kwargs[key] = value
        # Handle nested dataclasses
        elif hasattr(field_type, '__dataclass_fields__'):
            kwargs[key] = _dict_to_dataclass(value, field_type)
        else:
            kwargs[key] = value

    return cls(**kwargs)
