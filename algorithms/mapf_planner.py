import threading
import time
import queue
import heapq
import copy
import math
import random
import collections
from collections import defaultdict


try:
    import ecbs_standalone
    ECBS_STANDALONE_AVAILABLE = True
except ImportError:
    ECBS_STANDALONE_AVAILABLE = False
    ecbs_standalone = None


class Constraint:
    def __init__(self, agent_id, t, v, u=None, stay=False):
        self.agent_id = agent_id
        self.t = t
        self.v = v # node
        self.u = u # node (for edge conflict: u->v at t)
        self.stay = stay # stay forever after t

    def __repr__(self):
        type_str = "vertex" if self.u is None else "edge"
        return f"Constraint({type_str}, agent={self.agent_id}, t={self.t}, v={self.v}, u={self.u})"

class FocalNode:
    def __init__(self, v, g, f1, f2, parent=None):
        self.v = v
        self.g = g
        self.f1 = f1
        self.f2 = f2
        self.parent = parent

    def __lt__(self, other):
        # Open list comparison (f1)
        if self.f1 != other.f1:
            return self.f1 < other.f1
        return self.f2 < other.f2 # Tie-breaker

class HighLevelNode:
    def __init__(self, paths=None, constraints=None, makespan=0, soc=0, f=0, lb=0, f_mins=None, valid=True):
        self.paths = paths if paths is not None else {} # agent_id -> Path
        self.constraints = constraints if constraints is not None else []
        self.makespan = makespan
        self.soc = soc
        self.f = f # conflict count
        self.lb = lb # lower bound
        self.f_mins = f_mins if f_mins is not None else {} # agent_id -> min_f
        self.valid = valid

    def __lt__(self, other):
        # Main objective (LB)
        return self.lb < other.lb

class ECBS:
    SOLVER_NAME = "ECBS"
    DEFAULT_SUB_OPTIMALITY = 1.1

    def __init__(self, graph, agents, sub_optimality=DEFAULT_SUB_OPTIMALITY, time_limit=5.0):
        """
        graph: Common graph object (or wrapper)
        agents: List of dicts {'id': id, 'start': node_id, 'goal': node_id}
        """
        self.graph = graph
        self.agents = agents
        self.agent_ids = [a['id'] for a in agents]
        self.sub_optimality = sub_optimality
        self.time_limit = time_limit
        self.start_time = time.time()

        self.num_agents = len(agents)
        self.path_table = {} # (t, node_id) -> agent_id (for checking conflicts efficiently)

        # Statistics
        self.expanded_nodes = 0
        self.generated_nodes = 0

        # Precompute heuristics (Reverse BFS from each goal)
        self.heuristics = {} # agent_id -> {node_id -> dist}
        self._compute_heuristics()

    def _compute_heuristics(self):
        # Precompute heuristics using graph.get_cost for all nodes to each agent's goal
        # Since the graph is strongly connected, get_cost will always return a valid distance
        for agent in self.agents:
            aid = agent['id']
            goal = agent['goal']
            self.heuristics[aid] = {}

            # Precompute distance from all nodes to goal
            for node_id in self.graph.nodes.keys():
                cost = self.graph.get_cost(node_id, goal)
                if cost is not None:
                    self.heuristics[aid][node_id] = cost
                else:
                    # Fallback: should not happen in strongly connected graph
                    # Use large value as fallback
                    self.heuristics[aid][node_id] = float('inf')


    def get_solver_elapsed_time(self):
        return time.time() - self.start_time

    def over_comp_time(self):
        return self.get_solver_elapsed_time() > self.time_limit

    def run(self):
        # High-level search
        # OPEN: ordered by LB (Lower Bound)
        open_list = []

        # FOCAL: ordered by f (conflicts), then soc
        # We handle FOCAL as a separate list/heap

        # Initial Node
        n = HighLevelNode()
        self.set_initial_high_level_node(n)

        if not n.valid:
            print("Failed to find initial paths")
            return None

        heapq.heappush(open_list, (n.lb, id(n), n))

        lb_min = n.lb
        focal_list = [] # List of nodes in FOCAL

        # Add initial node to FOCAL
        heapq.heappush(focal_list, (n.f, n.soc, id(n), n))

        while open_list:
            if self.over_comp_time():
                print("Time limit exceeded")
                break

            # Pop out invalid nodes from OPEN (replicate C++ line 47)
            while open_list and not open_list[0][2].valid:
                heapq.heappop(open_list)
            if not open_list:
                break

            # Update FOCAL list if LB increases
            best_open_lb = open_list[0][0]

            if lb_min != best_open_lb:
                lb_min = best_open_lb
                lb_bound = lb_min * self.sub_optimality

                # Rebuild FOCAL: replicate C++ logic
                # Pop nodes from OPEN, check LB, add to FOCAL if LB <= lb_bound
                # Since OPEN is sorted by LB, we can break early
                focal_list = []
                tmp = []
                while open_list:
                    lb, node_id, node = heapq.heappop(open_list)
                    if not node.valid:
                        continue
                    tmp.append((lb, node_id, node))
                    # Since OPEN is sorted by LB, if this node's LB > lb_bound,
                    # all remaining nodes will also have LB > lb_bound
                    if lb > lb_bound:
                        break
                    # Add to FOCAL if LB <= lb_bound
                    heapq.heappush(focal_list, (node.f, node.soc, node_id, node))
                # Put nodes back into OPEN
                for item in tmp:
                    heapq.heappush(open_list, item)

            if not focal_list:
                # Should not happen if open_list has valid nodes matching condition
                # But if we popped from OPEN separate from FOCAL management, sync is needed.
                # Let's resync FOCAL from OPEN
                lb_bound = lb_min * self.sub_optimality
                focal_list = []
                for lb, _, node in open_list:
                    if node.valid and lb <= lb_bound:
                        heapq.heappush(focal_list, (node.f, node.soc, id(node), node))
                if not focal_list:
                    break

            # Pop best from FOCAL
            _, _, _, n = heapq.heappop(focal_list)

            # Remove from OPEN (inefficient in list, but OK for prototype)
            # In C++ they use a handle to remove from open_list
            # Here we mark invalid or just filter when popping from OPEN
            n.valid = False # Mark as closed/expanded

            # Check conflicts
            constraints = self.get_first_constraints(n.paths)
            if not constraints:
                # Solved!
                return n.paths

            # Create new nodes
            for constraint in constraints:
                new_constraints = n.constraints + [constraint]
                m = HighLevelNode(
                    paths=copy.deepcopy(n.paths),
                    constraints=new_constraints,
                    makespan=n.makespan,
                    soc=n.soc,
                    f=n.f,
                    lb=n.lb,
                    f_mins=copy.deepcopy(n.f_mins),
                    valid=True
                )

                # Update path for the constrained agent
                self.invoke(m, constraint.agent_id)

                if not m.valid:
                    continue

                heapq.heappush(open_list, (m.lb, id(m), m))

                if m.lb <= lb_min * self.sub_optimality:
                    heapq.heappush(focal_list, (m.f, m.soc, id(m), m))

    def set_initial_high_level_node(self, n):
        paths = {}
        f_mins = {}
        # Build paths incrementally, considering previously planned agents
        for agent in self.agents:
            aid = agent['id']
            # Initial path considering other agents already planned
            path = self.get_initial_path(aid, paths)
            if not path:
                n.valid = False
                return
            paths[aid] = path
            # f_min is path length - 1 (number of steps)
            f_mins[aid] = len(path) - 1

        n.paths = paths
        n.constraints = []
        n.makespan = self.get_makespan(paths)
        n.soc = self.get_soc(paths)
        n.f = self.count_conflicts(paths)
        n.f_mins = f_mins
        n.lb = n.soc # Simple lower bound
        n.valid = True

    def get_initial_path(self, agent_id, paths):
        # Replicate C++ getInitialPath logic: greedy path considering other agents' paths
        start = self.get_agent_start(agent_id)
        goal = self.get_agent_goal(agent_id)

        # Get all goal nodes (config_g)
        config_g = set(self.get_agent_goal(aid) for aid in self.agent_ids)

        path = [start]
        p = start
        t = 1
        makespan = self.get_makespan(paths) if paths else 0
        num_agents = self.num_agents

        while p != goal:
            # Find best neighbor using greedy selection
            neighbors = self.graph.get_neighbors(p)
            if not neighbors:
                return None  # No path exists

            best_neighbor = None

            for edge in neighbors:
                candidate = edge['to']
                if best_neighbor is None:
                    best_neighbor = candidate
                    continue

                # Compare candidate vs best_neighbor
                dist_candidate = self.heuristics[agent_id].get(candidate, float('inf'))
                dist_best = self.heuristics[agent_id].get(best_neighbor, float('inf'))

                # Priority 1: distance to goal
                if dist_candidate != dist_best:
                    if dist_candidate < dist_best:
                        best_neighbor = candidate
                    continue

                # Priority 2: avoid other agents at time t (if within makespan)
                if t <= makespan:
                    cand_occupied = False
                    best_occupied = False

                    for aid, other_path in paths.items():
                        if aid == agent_id: continue
                        if t < len(other_path):
                            if other_path[t] == candidate: cand_occupied = True
                            if other_path[t] == best_neighbor: best_occupied = True

                    if cand_occupied != best_occupied:
                        if not cand_occupied: # candidate free, best occupied -> candidate better
                            best_neighbor = candidate
                        continue

                # Priority 3: avoid other agents' goals (unless it's our goal)
                cand_is_goal = (candidate != goal and candidate in config_g)
                best_is_goal = (best_neighbor != goal and best_neighbor in config_g)

                if cand_is_goal != best_is_goal:
                    if not cand_is_goal:
                        best_neighbor = candidate
                    continue

            if best_neighbor is None:
                return None

            path.append(best_neighbor)
            p = best_neighbor
            t += 1

        return path

    def invoke(self, h_node, agent_id):
        path, f_min = self.get_focal_path(h_node, agent_id)

        if not path:
            h_node.valid = False
            return

        # Update path efficiently (replicate C++ logic)
        old_path = h_node.paths[agent_id]

        # Incrementally update conflict count: f = f - conflicts(old_path) + conflicts(new_path)
        # For efficiency, we need to count conflicts with old_path and new_path
        old_conflicts = self._count_path_conflicts(agent_id, old_path, h_node.paths)
        h_node.paths[agent_id] = path
        new_conflicts = self._count_path_conflicts(agent_id, path, h_node.paths)
        h_node.f = h_node.f - old_conflicts + new_conflicts

        # Update other metrics
        h_node.makespan = self.get_makespan(h_node.paths)
        h_node.soc = self.get_soc(h_node.paths)

        # Update Lower Bound: LB = LB - old_f_min + new_f_min
        old_f_min = h_node.f_mins[agent_id]
        h_node.lb = h_node.lb - old_f_min + f_min
        h_node.f_mins[agent_id] = f_min

    def get_focal_path(self, h_node, agent_id):
        # Build constraints for this agent
        agent_constraints = [c for c in h_node.constraints if c.agent_id == agent_id]

        # Max constraint time (only for goal constraints: c->v == g && c->u == nullptr)
        agent_goal = self.get_agent_goal(agent_id)
        max_t = -1
        for c in agent_constraints:
            if c.v == agent_goal and c.u is None:
                max_t = max(max_t, c.t)

        # Build Path Table from OTHER agents (with agent_id stored)
        self.update_path_table(h_node.paths, exclude_agent=agent_id)

        # Define Heuristics for Focal Search
        # f1: standard A* (g + h) with special handling if pathDist <= max_constraint_time
        # f2: conflict count

        agent_start = self.get_agent_start(agent_id)
        path_dist = self.heuristics[agent_id].get(agent_start, float('inf'))

        def f1(n):
            h = self.heuristics[agent_id].get(n.v, float('inf'))
            if path_dist > max_t:
                return n.g + h
            else:
                # Must wait until max_constraint_time + 1
                return max(max_t + 1, n.g + h)

        def f2(n):
            # Replicate C++ f2Value logic
            if n.g == 0:
                return 0

            conflicts = n.f2 if n.parent else 0
            makespan = h_node.makespan

            # Check vertex conflict
            if n.g <= makespan:
                if n.g in self.path_table and n.v in self.path_table[n.g]:
                    return conflicts + 1

                # Check swap conflict
                if n.parent and n.g > 0:
                    prev_t = n.g - 1
                    if prev_t in self.path_table and n.g in self.path_table:
                        # Check if someone was at n.v at prev_t and is at n.parent.v at n.g
                        if n.parent.v in self.path_table[n.g]:
                            other_agent_at_g = self.path_table[n.g][n.parent.v]
                            if prev_t in self.path_table and n.v in self.path_table[prev_t]:
                                other_agent_at_prev = self.path_table[prev_t][n.v]
                                if other_agent_at_g == other_agent_at_prev:
                                    # Swap conflict detected
                                    return conflicts + 1
            else:
                # After makespan: check if goal is occupied
                if makespan in self.path_table and n.v in self.path_table[makespan]:
                    return conflicts + 1

            return conflicts

        return self.get_timed_path_by_focal_search(
            agent_start, agent_goal,
            self.sub_optimality,
            f1, f2,
            agent_constraints,
            max_t
        )

    def get_timed_path_by_focal_search(self, start, goal, w, f1, f2, constraints, max_constraint_time):
        def get_node_name(node):
            return f"{node.v}-{node.g}"

        open_list = []
        focal_list = []
        closed_set = set() # node names as strings

        start_node = FocalNode(start, 0, 0, 0)
        start_node.f1 = f1(start_node)
        start_node.f2 = f2(start_node)

        heapq.heappush(open_list, (start_node.f1, id(start_node), start_node))
        heapq.heappush(focal_list, (start_node.f2, start_node.f1, id(start_node), start_node))

        f1_min = start_node.f1

        best_node = None

        while open_list:
            if self.over_comp_time():
                break

            # Pop out invalid nodes from OPEN (replicate C++ line 347-348)
            while open_list and get_node_name(open_list[0][2]) in closed_set:
                heapq.heappop(open_list)
            if not open_list:
                break

            # Update FOCAL
            if open_list[0][0] != f1_min:
                f1_min = open_list[0][0]
                f1_bound = f1_min * w
                # Rebuild FOCAL (replicate C++ line 354-363)
                focal_list = []
                tmp = []
                for f1_val, _, node in open_list:
                    if get_node_name(node) in closed_set:
                        continue
                    tmp.append((f1_val, id(node), node))
                    if f1_val > f1_bound:
                        break
                    heapq.heappush(focal_list, (node.f2, node.f1, id(node), node))
                # Rebuild open_list from tmp (simplified, C++ uses priority_queue)
                open_list = []
                for f1_val, node_id, node in tmp:
                    heapq.heappush(open_list, (f1_val, node_id, node))

            if not focal_list:
                # Sync issue fallback
                f1_bound = f1_min * w
                for f1_val, _, node in open_list:
                    if get_node_name(node) in closed_set:
                        continue
                    if f1_val <= f1_bound:
                        heapq.heappush(focal_list, (node.f2, node.f1, id(node), node))
                if not focal_list: break

            _, _, _, n = heapq.heappop(focal_list)

            # Check CLOSED (replicate C++ line 371)
            if get_node_name(n) in closed_set:
                continue
            closed_set.add(get_node_name(n))

            # Goal check
            # Must be at goal and after max constraint time (to avoid future conflicts at goal)
            if n.v == goal and n.g > max_constraint_time:
                best_node = n
                break

            # Expand
            neighbors = self.graph.get_neighbors(n.v)
            # Add wait
            neighbors.append({'to': n.v})

            for edge in neighbors:
                succ_v = edge['to']
                succ_g = n.g + 1

                succ_node = FocalNode(succ_v, succ_g, 0, 0, n)
                succ_node.f1 = f1(succ_node)
                succ_node.f2 = f2(succ_node)

                # Check CLOSED (replicate C++ line 390)
                if get_node_name(succ_node) in closed_set:
                    continue

                # Check constraints (replicate C++ line 392)
                if self.is_constrained(n.v, succ_v, succ_g, constraints):
                    continue

                heapq.heappush(open_list, (succ_node.f1, id(succ_node), succ_node))
                if succ_node.f1 <= f1_min * w:
                    heapq.heappush(focal_list, (succ_node.f2, succ_node.f1, id(succ_node), succ_node))

        if best_node:
            path = []
            curr = best_node
            while curr:
                path.append(curr.v)
                curr = curr.parent
            path.reverse()
            # C++ version returns f1_min (the minimum f1 in OPEN), not best_node.f1
            return path, f1_min # path, cost

        return None, 0

    def get_timed_path(self, agent_id, constraints):
        # Wrapper for initial path (A*)
        goal = self.get_agent_goal(agent_id)
        start = self.get_agent_start(agent_id)

        def f1(n):
            h = self.heuristics[agent_id].get(n.v, float('inf'))
            return n.g + h
        def f2(n): return 0

        return self.get_timed_path_by_focal_search(
            start, goal, 1.0, f1, f2, constraints, -1
        )

    def is_constrained(self, u, v, t, constraints):
        # Replicate C++ checkInvalidFocalNode logic
        for c in constraints:
            if c.t == t and c.v == v:
                # Vertex constraint or swap conflict
                if c.u is None or c.u == u:
                    return True
        return False

    def get_first_constraints(self, paths):
        # Find first conflict
        # Populate path table
        self.update_path_table(paths)

        # We need to check all pairs.
        # Efficient way: iterate time steps and nodes.
        # Since update_path_table populates self.path_table, we can check overlaps there.
        # But update_path_table as implemented below just stores one agent.
        # We need to detect collisions.

        # Proper conflict detection:
        # Check Vertex Conflicts
        # Check Edge Conflicts (Swaps)

        # Re-implement conflict detection by iterating all pairs of agents?
        # Or using a lookup table.

        table = {} # (t, v) -> agent_id

        constraints = []

        # Check Vertex Conflicts
        # C++ version starts from t=1 (t=0 is initial position, no conflicts)
        max_len = max(len(p) for p in paths.values()) if paths else 0

        for t in range(1, max_len):
            table = {}
            for aid, path in paths.items():
                if t < len(path):
                    v = path[t]
                    if v in table:
                        other_aid = table[v]
                        # Found vertex conflict between aid and other_aid at t, v
                        c1 = Constraint(aid, t, v)
                        c2 = Constraint(other_aid, t, v)
                        return [c1, c2]
                    table[v] = aid
                else:
                    # Agent stays at goal?
                    # ECBS typically assumes agent stays at goal forever if not disappeared
                    v = path[-1]
                    if v in table:
                        other_aid = table[v]
                        c1 = Constraint(aid, t, v)
                        c2 = Constraint(other_aid, t, v)
                        return [c1, c2]
                    table[v] = aid

        # Check Edge Conflicts (Swaps)
        # C++ version: paths.get(i, t) == paths.get(j, t-1) && paths.get(j, t) == paths.get(i, t-1)
        # This means: agent i at position v at t, was at u at t-1
        #             agent j at position u at t, was at v at t-1
        for t in range(1, max_len):
            for aid_i, path_i in paths.items():
                if t >= len(path_i):
                    continue
                u_i = path_i[t-1]  # agent i at t-1
                v_i = path_i[t]    # agent i at t

                for aid_j, path_j in paths.items():
                    if aid_j <= aid_i:  # Only check pairs once (i < j)
                        continue
                    if t >= len(path_j):
                        continue
                    u_j = path_j[t-1]  # agent j at t-1
                    v_j = path_j[t]    # agent j at t

                    # Swap conflict: i at v_i(t) == j at u_j(t-1) && j at v_j(t) == i at u_i(t-1)
                    if v_i == u_j and v_j == u_i:
                        c1 = Constraint(aid_i, t, v_i, u=u_i)
                        c2 = Constraint(aid_j, t, v_j, u=u_j)
                        return [c1, c2]

        return []

    def update_path_table(self, paths, exclude_agent=None):
        # Replicate C++ PATH_TABLE: PATH_TABLE[t][node_id] = agent_id
        self.path_table = {}
        for aid, path in paths.items():
            if aid == exclude_agent: continue
            for t, v in enumerate(path):
                if t not in self.path_table:
                    self.path_table[t] = {}
                self.path_table[t][v] = aid
            # After path ends, agent stays at goal (infinite path)
            if path:
                goal = path[-1]
                makespan = len(path) - 1
                # For all t > makespan, agent is at goal
                # We'll check this in f2 when n.g > makespan

    def heuristic(self, u, v):
        # Manhattan or Euclidean
        n1 = self.graph.get_node(u)
        n2 = self.graph.get_node(v)
        if not n1 or not n2: return 0
        return abs(n1['x'] - n2['x']) + abs(n1['y'] - n2['y'])

    def get_makespan(self, paths):
        if not paths: return 0
        # C++ version: makespan = max(path_size - 1)
        # because path includes start node at t=0
        return max(len(p) - 1 for p in paths.values())

    def get_soc(self, paths):
        return sum(len(p) for p in paths.values())

    def count_conflicts(self, paths):
        # Count all conflicts in paths
        count = 0
        max_len = max(len(p) for p in paths.values()) if paths else 0

        # Check vertex conflicts
        for t in range(max_len):
            occupied = {}
            for aid, path in paths.items():
                if t < len(path):
                    v = path[t]
                else:
                    v = path[-1]  # Stay at goal
                if v in occupied:
                    count += 1
                occupied[v] = aid

        # Check edge conflicts (swaps)
        for t in range(max_len - 1):
            edges = {}
            for aid, path in paths.items():
                if t + 1 < len(path):
                    u = path[t]
                    v = path[t + 1]
                    if (v, u) in edges:
                        count += 1
                    edges[(u, v)] = aid

        return count

    def _count_path_conflicts(self, agent_id, path, all_paths):
        # Count conflicts between this path and all other paths
        count = 0
        max_len = max(len(p) for p in all_paths.values()) if all_paths else 0

        for t in range(max_len):
            # Vertex conflicts
            if t < len(path):
                v = path[t]
            else:
                v = path[-1]

            for other_id, other_path in all_paths.items():
                if other_id == agent_id: continue
                if t < len(other_path):
                    if other_path[t] == v:
                        count += 1
                else:
                    if other_path[-1] == v:
                        count += 1

            # Edge conflicts (swaps)
            if t + 1 < len(path):
                u = path[t]
                v = path[t + 1]
                for other_id, other_path in all_paths.items():
                    if other_id == agent_id: continue
                    if t + 1 < len(other_path):
                        if other_path[t] == v and other_path[t + 1] == u:
                            count += 1

        return count

    def get_agent_start(self, aid):
        for a in self.agents:
            if a['id'] == aid: return a['start']
        return None

    def get_agent_goal(self, aid):
        for a in self.agents:
            if a['id'] == aid: return a['goal']
        return None

# =============================================================================
# Application Integration
# =============================================================================

class MapfPathPlanner(threading.Thread):
    def __init__(self, move_request_queue, agv_travel_status, log_cb=None, base_size=3, horizon_size=3, debug=False):
        super().__init__(daemon=True)
        self.move_request_queue = move_request_queue
        self.agv_travel_status = agv_travel_status
        self.log_cb = log_cb
        self.debug = debug
        self.running = True
        self.paused = False
        self.generated_commands = []
        self.commands_lock = threading.Lock()
        self.data_lock = threading.Lock()
        self.latest_agvs = {}
        self.latest_agvs_cache = {}
        self.graph = None
        self.agv_goals = {}
        self.agv_plans = {}
        # Rolling path parameters
        self.base_size = base_size  # Released segment size
        self.horizon_size = horizon_size  # Horizon segment size
        # Track issued path segments for each AGV (similar to path_planner.py)
        # agv_id -> {'issued_count': int, 'full_path_segments': list, 'last_base_sequence_id': int, 'order_id': str, 'order_update_id': int}
        self.issued_state = {}

    def update_data(self, agvs, graph):
        with self.data_lock:
            self.latest_agvs_cache = agvs
            self.graph = graph

    def get_commands(self):
        with self.commands_lock:
            cmds = self.generated_commands[:]
            self.generated_commands.clear()
            return cmds

    def reset(self):
        self.agv_goals.clear()
        self.agv_plans.clear()
        self.issued_state.clear()
        with self.commands_lock:
            self.generated_commands.clear()

    def log(self, msg, level='INFO'):
        if self.log_cb: self.log_cb(f"[Planner] {msg}", level)

    def _convert_graph_to_ecbs_standalone(self, graph):
        """Convert the simulator graph to an ECBS graph"""
        if not ECBS_STANDALONE_AVAILABLE:
            raise ImportError("ecbs_standalone module is not available")

        ecbs_graph = ecbs_standalone.Graph()


        for node_id, node_data in graph.nodes.items():
            x = node_data.get('x', 0.0)
            y = node_data.get('y', 0.0)
            ecbs_graph.add_node(node_id, float(x), float(y))


        for from_id, edges_list in graph.edges.items():
            for edge in edges_list:
                to_id = edge['to']
                cost = edge.get('cost', 1.0)
                ecbs_graph.add_edge(from_id, to_id, float(cost))

        return ecbs_graph

    def run(self):
        last_replan = 0
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue
            try:
                with self.data_lock:
                    if not self.graph or not self.latest_agvs_cache:
                        time.sleep(0.1)
                        continue
                    self.latest_agvs = copy.deepcopy(self.latest_agvs_cache)

                replan = False
                # Process Requests
                while not self.move_request_queue.empty():
                    try:
                        req = self.move_request_queue.get_nowait()
                        self._handle_request(req)
                        replan = True
                    except queue.Empty: break

                # Replan
                current_time = time.time()
                if replan: # or current_time - last_replan > 1.0:
                    self._replan_all()
                    last_replan = current_time

                # Issue Commands
                self._issue_commands()

            except Exception as e:
                self.log(f"Error: {e}", 'ERROR')
                import traceback
                traceback.print_exc()
            time.sleep(0.1)

    def _handle_request(self, req):
        agv_id = req['agv_id']
        target_node = req['target_node']
        with self.data_lock:
            if self.graph and target_node not in self.graph.nodes:
                self.log(f"Invalid target {target_node}", "ERROR")
                return
        self.agv_goals[agv_id] = target_node
        self.agv_travel_status[agv_id] = {'status': 'planning'}
        self.log(f"Goal for {agv_id}: {target_node}")

    def _replan_all(self):
        # Prepare Agents for ECBS
        agents_config = []

        for agv_id, goal in self.agv_goals.items():
            agv = self.latest_agvs.get(agv_id)
            if not agv: continue

            # Determine start node from issued_count (similar to path_planner.py)
            # Start from the source node of the edge at issued_count index
            start_node = None
            issued_info = self.issued_state.get(agv_id)

            if issued_info and issued_info.get('issued_count', 0) > 0:
                # Get the full path segments
                full_path_segments = issued_info.get('full_path_segments', [])
                issued_count = issued_info.get('issued_count', 0)

                # Find the source node of the edge at issued_count
                if issued_count < len(full_path_segments):
                    # Start from the source of the next edge to issue
                    start_node = full_path_segments[issued_count]['source']
            else:
                start_node = self._find_nearest_node(agv.position)

            if start_node:
                agents_config.append({
                    'id': agv_id,
                    'start': start_node,
                    'goal': goal
                })

        if not agents_config: return

        # Run ECBS using ecbs_standalone
        ecbs_start_time = time.time()

        if ECBS_STANDALONE_AVAILABLE:
            try:

                ecbs_graph = self._convert_graph_to_ecbs_standalone(self.graph)

                # Map string IDs to integer indices
                id_to_index = {}
                index_to_id = {}


                ecbs_agents = []
                for idx, agent_cfg in enumerate(agents_config):
                    original_id = agent_cfg['id']
                    # Use integer indices as ECBS agent IDs
                    agent_index = idx
                    id_to_index[original_id] = agent_index
                    index_to_id[agent_index] = original_id

                    ecbs_agents.append(
                        ecbs_standalone.Agent(
                            agent_index,
                            agent_cfg['start'],
                            agent_cfg['goal']
                        )
                    )


                solver = ecbs_standalone.ECBS(
                    ecbs_graph,
                    ecbs_agents,
                    sub_optimality=1.1,
                    time_limit=15.0
                )
                success = solver.solve()

                if success:

                    solution = solver.get_solution()
                    # Map integer indices back to string IDs
                    paths = {}
                    for agent_index, path in solution.items():
                        original_id = index_to_id.get(agent_index)
                        if original_id is not None:
                            paths[original_id] = path
                else:
                    paths = None
                    self.log("ECBS failed: no solution found", "WARN")

            except Exception as e:
                self.log(f"ecbs_standalone failed; falling back to Python: {e}", "WARN")
                import traceback
                traceback.print_exc()

                ecbs = ECBS(self.graph, agents_config, sub_optimality=1.1, time_limit=15.0)
                paths = ecbs.run()
        else:
            # Fall back to Python if ecbs_standalone is unavailable
            ecbs = ECBS(self.graph, agents_config, sub_optimality=1.1, time_limit=15.0)
            paths = ecbs.run()

        ecbs_elapsed = time.time() - ecbs_start_time
        print(f"ECBS solved in {ecbs_elapsed*1000:.2f} ms (agents={len(agents_config)})")

        if paths:
            self.log(f"ECBS planned for {len(paths)} agents")
            for agv_id, node_path in paths.items():
                # Check for short paths (start==goal?)
                if len(node_path) <= 1:
                    # Find start and goal from agents_config
                    a_cfg = next((a for a in agents_config if a['id'] == agv_id), None)
                    if a_cfg:
                            print(f"[WARN] AGV {agv_id} path len {len(node_path)}. Start: {a_cfg['start']}, Goal: {a_cfg['goal']}")

                # Convert node sequence to segments
                segments = []
                # Assume discrete time steps = 1.0s
                print(f'agv: {agv_id} node_path: {node_path}')
                for i in range(len(node_path) - 1):
                    u = node_path[i]
                    v = node_path[i+1]

                    # Merge waiting intervals: Skip u->u transitions
                    if u == v:
                        continue

                    # Find edge id from graph
                    edge_id = None
                    neighbors = self.graph.get_neighbors(u)
                    for edge in neighbors:
                        if edge['to'] == v:
                            edge_id = edge.get('id', f"{u}_{v}")
                            break

                    # Calculate dependencies
                    dependencies = []
                    for other_id, other_path in paths.items():
                        if other_id == agv_id: continue

                        # Check if other agent occupies v at step i (blocked entry)
                        # or at step i+1 (collision at target)
                        start_search = -1
                        if i < len(other_path) and other_path[i] == v:
                            start_search = i
                        elif i + 1 < len(other_path) and other_path[i+1] == v:
                            start_search = i + 1

                        if start_search != -1:
                            dependencies.append({
                                'agv': other_id,
                                'node': v
                            })
                            break

                    segments.append({
                        'source': u,
                        'target': v,
                        'id': edge_id,
                        'dependencies': dependencies
                    })

                # Update full path segments: keep issued base part, append new plan
                issued_info = self.issued_state.get(agv_id)
                if issued_info and issued_info.get('issued_count', 0) > 0:
                    # Keep the issued base part (first issued_count segments)
                    issued_count = issued_info.get('issued_count', 0)
                    old_segments = issued_info.get('full_path_segments', [])
                    # Keep only the issued part
                    base_segments = old_segments[:issued_count] if issued_count <= len(old_segments) else old_segments
                    # Append new segments
                    full_segments = base_segments + segments
                    # Update issued_state: keep issued_count, last_base_sequence_id, order_id, order_update_id
                    self.issued_state[agv_id] = {
                        'issued_count': issued_count,
                        'full_path_segments': full_segments,
                        'last_base_sequence_id': issued_info.get('last_base_sequence_id', 0),
                        'order_id': issued_info.get('order_id'),  # Preserve order_id
                        'order_update_id': issued_info.get('order_update_id', -1)  # Preserve order_update_id
                    }
                    # agv_plans should contain segments from issued_count onwards (unissued parts)
                    # Since we're replanning, only new segments are in agv_plans
                    self.agv_plans[agv_id] = segments
                else:
                    # No issued parts, replace entirely
                    self.issued_state[agv_id] = {
                        'issued_count': 0,
                        'full_path_segments': segments,
                        'last_base_sequence_id': 0,
                        'order_id': None,  # No order_id before first issuance
                        'order_update_id': -1
                    }
                    self.agv_plans[agv_id] = segments
                self.agv_travel_status[agv_id] = {'status': 'moving', 'target_node': self.agv_goals[agv_id]}
        else:
            self.log("ECBS failed to find solution", "WARN")

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

    def _issue_commands(self):
        """Issue a path segment using the rolling planner flow"""
        for agv_id in list(self.agv_plans.keys()):
            agv = self.latest_agvs.get(agv_id)
            if not agv: continue


            self._check_and_update_path(agv_id, agv)


            if self._check_arrival(agv_id, agv):
                agv_name = agv.name or agv.id
                goal = self.agv_goals.get(agv_id)
                self.log(f"AGV {agv_name} reached {goal}")
                self.agv_travel_status[agv_id] = {
                    'status': 'reached',
                    'target_node': goal
                }
                if agv_id in self.agv_plans:
                    del self.agv_plans[agv_id]
                if agv_id in self.issued_state:
                    del self.issued_state[agv_id]
                if agv_id in self.agv_goals:
                    del self.agv_goals[agv_id]

    def _check_and_update_path(self, agv_id, agv):
        """Check and advance the issued path"""
        issued_info = self.issued_state.get(agv_id)
        if not issued_info:
            return


        path_order_id = issued_info.get('order_id')
        if not path_order_id:

            full_path_segments = issued_info.get('full_path_segments', [])
            self._issue_path_segment(agv, agv_id, first_issue=True)
            return

        if not agv.orderId or agv.orderId != path_order_id:
            return

        # 2. Verify the last released edge sequence
        released_edges = [e for e in agv.edgeStates if e.get('released')]
        if not agv.newBaseRequest:
            if not released_edges:
                return

            max_seq_id = max([e.get('sequenceId', -1) for e in released_edges])
            last_base_seq_id = issued_info.get('last_base_sequence_id', -1)

            if abs(max_seq_id - last_base_seq_id) > 1:
                return
        else:
            if issued_info.get('last_base_sequence_id', 0) > agv.last_node_sequence_id:
                return

        # 3. After validation, decide whether to issue another segment
        remaining_base_edges = len(released_edges)
        full_path_segments = issued_info.get('full_path_segments', [])
        issued_count = issued_info.get('issued_count', 0)

        # If running low on base edges, issue more
        if remaining_base_edges < 2 and issued_count < len(full_path_segments):
            self._issue_path_segment(agv, agv_id, first_issue=False)

    def _check_dependencies(self, dependencies):
        """Check dependency readiness"""
        for dep in dependencies:
            target_agv_id = dep['agv']
            target_node = dep['node']

            target_agv = self.latest_agvs.get(target_agv_id)
            if not target_agv:
                continue

            # Check if target_agv has reached or passed target_node
            last_node_id = target_agv.last_node_id
            if last_node_id == target_node:
                continue

            # Check if passed (in target_agv's current plan)
            target_issued = self.issued_state.get(target_agv_id)
            if not target_issued:
                continue

            path_segments = target_issued.get('full_path_segments', [])

            # Build node list to check order
            nodes = []
            if path_segments:
                nodes.append(path_segments[0]['source'])
                for s in path_segments:
                    nodes.append(s['target'])

            try:
                # Find index of target_node and lastNodeId
                t_idx = -1
                c_idx = -1

                if target_node in nodes:
                    t_idx = nodes.index(target_node)

                if last_node_id in nodes:
                    c_idx = nodes.index(last_node_id)

                if t_idx != -1 and c_idx != -1:
                    if c_idx >= t_idx:
                        continue
            except ValueError:
                pass

            return False

        return True

    def _issue_path_segment(self, agv, agv_id, first_issue=False):
        """Issue a path segment with dependency checks"""
        issued_info = self.issued_state.get(agv_id)
        if not issued_info:
            return False

        full_path_segments = issued_info.get('full_path_segments', [])
        issued_count = issued_info.get('issued_count', 0)


        remaining = len(full_path_segments) - issued_count
        if remaining <= 0 and not first_issue:
            return False


        limit_index = len(full_path_segments)
        for i in range(issued_count, len(full_path_segments)):
            seg = full_path_segments[i]
            deps = seg.get('dependencies', [])
            if deps:
                if not self._check_dependencies(deps):
                    # Stop before the first unmet dependency
                    limit_index = i
                    break

        # Cannot issue if the first item is blocked
        if limit_index == issued_count and len(full_path_segments) > 0 :
            return False

        remaining = min(remaining, limit_index - issued_count)

        # Strategy: Send base_size base + horizon_size horizon
        base_size = min(self.base_size, remaining)
        horizon_size = min(self.horizon_size, remaining - base_size)

        seq_id = issued_info.get('last_base_sequence_id', 0)

        nodes = []
        edges = []

        current_idx = issued_count




        start_node_id = full_path_segments[current_idx]['source'] if full_path_segments else self.agv_goals.get(agv_id)
        start_node = self._node_to_vda5050(start_node_id, seq_id, True)
        if not start_node:
            self.log(f"Node {start_node_id} not found in graph", 'ERROR')
            return False
        nodes.append(start_node)
        seq_id += 1


        for i in range(base_size):
            if current_idx + i >= len(full_path_segments):
                break
            edge_info = full_path_segments[current_idx + i]
            edges.append(self._path_edge_to_vda5050(edge_info, seq_id, True))
            seq_id += 1
            target_node = self._node_to_vda5050(edge_info['target'], seq_id, True)
            if not target_node:
                self.log(f"Target node {edge_info['target']} not found in graph", 'ERROR')
                return False
            nodes.append(target_node)
            seq_id += 1

        last_base_seq_id = seq_id - 1


        for i in range(horizon_size):
            if current_idx + base_size + i >= len(full_path_segments):
                break
            edge_info = full_path_segments[current_idx + base_size + i]
            edges.append(self._path_edge_to_vda5050(edge_info, seq_id, False))
            seq_id += 1
            target_node = self._node_to_vda5050(edge_info['target'], seq_id, False)
            if not target_node:
                self.log(f"Target node {edge_info['target']} not found in graph", 'ERROR')
                return False
            nodes.append(target_node)
            seq_id += 1

        # Number of released edges
        actual_base_size = len([e for e in edges if e.get('released')])

        # Update state
        issued_info['issued_count'] += actual_base_size
        issued_info['last_base_sequence_id'] = last_base_seq_id

        order_update_id = issued_info.get('order_update_id', -1) + 1
        issued_info['order_update_id'] = order_update_id

        if first_issue:
            order_id = f"order_{time.time()}_{agv.name or agv.id}"
            issued_info['order_id'] = order_id
        else:
            order_id = issued_info.get('order_id')

        if not order_id:
            self.log(f"AGV {agv.name or agv.id} has no order_id", 'ERROR')
            return False

        self.log(f"AGV {agv.name or agv.id} path issued: {order_id} {order_update_id}; released: {issued_info['issued_count']}; length: {len(full_path_segments)}")

        order_data = {
            'orderId': order_id,
            'orderUpdateId': order_update_id,
            'nodes': nodes,
            'edges': edges
        }

        with self.commands_lock:
            self.generated_commands.append({
                'type': 'SEND_ORDER',
                'agv_id': agv_id,
                'order': order_data
            })

        return True

    def _check_arrival(self, agv_id, agv):
        """Check whether the AGV reached its goal"""
        issued_info = self.issued_state.get(agv_id)
        if not issued_info:
            return False

        full_path_segments = issued_info.get('full_path_segments', [])
        issued_count = issued_info.get('issued_count', 0)

        # 1. All path segments must be issued
        if issued_count < len(full_path_segments):
            return False

        # 2. Ensure the AGV accepted an order
        if not agv.orderId:
            return False


        path_order_id = issued_info.get('order_id')
        if path_order_id and agv.orderId != path_order_id:
            return False


        if not agv.newBaseRequest:
            return False


        released_edges = [e for e in agv.edgeStates if e.get('released')]
        if len(released_edges) > 0:
            return False

        # 6. Check the AGV position against the goal
        goal = self.agv_goals.get(agv_id)
        if not goal:
            return False

        nearest_node = self._find_nearest_node(agv.position)
        if nearest_node == goal:
            return True

        # Otherwise calculate distance to the goal
        target_node_data = self.graph.get_node(goal)
        if target_node_data:
            pos = agv.position
            dist = ((pos['x'] - target_node_data['x'])**2 +
                    (pos['y'] - target_node_data['y'])**2)**0.5
            if dist < 0.2:  # 0.2 m tolerance
                return True

        return False

    def _path_edge_to_vda5050(self, edge, seq_id, released):
        """Convert path edges to VDA5050"""
        return {
            'edgeId': edge.get('id', '') or f"edge_{edge.get('source')}_{edge.get('target')}",
            'sequenceId': seq_id,
            'description': f"Edge to {edge.get('target')}",
            'released': released,
            'startNodeId': edge.get('source'),
            'endNodeId': edge.get('target'),
            'maxSpeed': edge.get('max_speed', 1.0),
            'distance': edge.get('length', 1.0)
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
            'actions': []
        }
