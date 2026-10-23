class BaseAlgorithm:
    def __init__(self, log_cb=None):
        self.log_cb = log_cb
        self.graph = None
        self.seen_submitted_tasks = set()

    def log(self, message, level='INFO'):
        if self.log_cb:
            try:
                self.log_cb(message, level)
            except:
                pass
        else:
            print(f"[Algorithm] {message}")

    def init_map(self, paths):
        """Initialize map data"""
        raise NotImplementedError

    def process(self, agvs, tasks, current_time, action_configs=None):
        """
        Run task allocation, path planning, and monitoring
        :param agvs: Dict[str, AGV] dictionary of AGV objects
        :param tasks: List[Dict] Task list
        :param current_time: Current simulation time
        :param action_configs: Dict action configuration
        :return: List[Dict] commands
                 Standard commands:
                 - {'type': 'UPDATE_TASK', 'task_id': str, 'updates': dict}
                 - {'type': 'SEND_ORDER', 'agv_id': str, 'order': dict}
                 - {'type': 'UPDATE_AGV_TASK_SNAPSHOT', 'agv_id': str, 'task_snapshot': dict}
                 - {'type': 'UPDATE_AGV_STATUS', 'agv_id': str, 'status': str, 'clear_paths': bool}
        """
        raise NotImplementedError

    def reset(self):
        self.seen_submitted_tasks.clear()
