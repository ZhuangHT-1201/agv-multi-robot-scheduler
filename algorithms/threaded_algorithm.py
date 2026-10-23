from .base import BaseAlgorithm
from common.graph import Graph
from .task_allocator import TaskAllocator
from .path_planner import PathPlanner
from .mapf_planner import MapfPathPlanner
from .enhanced_planner import EnhancedMapfPlanner
import queue
import threading

PLANNER_ECBS = 'ecbs'
PLANNER_SIMPLE = 'simple'


class ThreadedAlgorithm(BaseAlgorithm):
    def __init__(self, log_cb=None, debug_mapf=False, planner_type=PLANNER_ECBS):
        super().__init__(log_cb)

        # Communication channels
        self.move_request_queue = queue.Queue()
        self.agv_travel_status = {} # Shared dict
        self.planner_type = planner_type

        # Components
        self.task_allocator = TaskAllocator(self.move_request_queue, self.agv_travel_status, log_cb)

        if planner_type == PLANNER_ECBS:
            self.path_planner = EnhancedMapfPlanner(
                self.move_request_queue, self.agv_travel_status, log_cb
            )
        else:
            self.path_planner = PathPlanner(self.move_request_queue, self.agv_travel_status, log_cb)

        self.threads_started = False
        self.graph = None

    def init_map(self, paths):
        self.graph = Graph()
        for path in paths:
            for v in path.get('vertices', []):
                self.graph.add_vertex(v)
            for e in path.get('edges', []):
                self.graph.add_edge(e)
        self.graph.compute_adjacency_matrix()

        if not self.threads_started:
            self.task_allocator.start()
            self.path_planner.start()
            self.threads_started = True

    def reset(self):
        super().reset()

        # Clear queues
        while not self.move_request_queue.empty():
            try: self.move_request_queue.get_nowait()
            except queue.Empty: break

        self.agv_travel_status.clear()

        # Reset component state
        self.task_allocator.reset()
        self.path_planner.reset()

    def set_paused(self, paused):
        """Set the paused state for all worker threads"""
        if self.threads_started:
            self.task_allocator.paused = paused
            self.path_planner.paused = paused

    def process(self, agvs, tasks, current_time, action_configs=None):
        if not self.graph:
            return []

        # 1. Update thread data snapshots
        # We pass references/copies. Since AGV objects are mutable, passing the dict of objects is risky
        # if threads modify them. But threads only read AGV state (position, status).
        # Commands are used to modify state in the main thread app.py.
        # So it is safe enough for simulation.
        self.task_allocator.update_data(agvs, tasks, self.graph, current_time)
        self.path_planner.update_data(agvs, self.graph)

        # 2. Collect generated commands
        commands = []
        commands.extend(self.task_allocator.get_commands())
        commands.extend(self.path_planner.get_commands())

        return commands
