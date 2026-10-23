"""
Enhanced multi-agent planner for AGV fleets.

Small fleets (<=8 active): rolling MapfPathPlanner loop, C++ ECBS, and a
12/12 release horizon.
Large fleets (>8 active): FastSpaceTime A* with reservations, adaptive
windows, request debounce, path extension, and collision recovery.
"""

import copy
import heapq
import queue
import time

try:
    import ecbs_standalone
    ECBS_STANDALONE_AVAILABLE = True
except ImportError:
    ECBS_STANDALONE_AVAILABLE = False
    ecbs_standalone = None

from .mapf_planner import Constraint, ECBS, MapfPathPlanner

OBSTACLE_PREFIX = "__obs__"
REPLAN_DEBOUNCE_S = 0.1
EXTENSION_DEBOUNCE_S = 0.02
GOAL_RESERVE_STEPS = 96
HORIZON_BASE = 12
HORIZON_HORIZON = 12
HORIZON_LARGE = 18
LARGE_FLEET_THRESHOLD = 8
BATCH_SIZE = 8
WINDOW_STEPS_MIN = 96
WINDOW_STEPS_MAX = 512
GOAL_RESERVE_LARGE = 32
STATIC_PATH_RESERVE = 14


class FastSpaceTimePlanner:
    def __init__(self, graph):
        self.graph = graph
        self._heuristics = {}

    def clear_cache(self):
        self._heuristics.clear()

    def _goal_h(self, goal):
        cached = self._heuristics.get(goal)
        if cached is not None:
            return cached
        h = {}
        for node_id in self.graph.nodes.keys():
            cost = self.graph.get_cost(node_id, goal)
            if cost is not None:
                h[node_id] = float(cost)
        self._heuristics[goal] = h
        return h

    @staticmethod
    def build_reservation(paths, goal_reserve=GOAL_RESERVE_STEPS):
        vertex, edge = {}, set()
        for aid, path in paths.items():
            if not path:
                continue
            for t, node in enumerate(path):
                vertex[(t, node)] = aid
                if t > 0:
                    edge.add((t, path[t - 1], node))
            end = path[-1]
            reserve = goal_reserve
            if len(path) == 1:
                reserve = min(goal_reserve, STATIC_PATH_RESERVE)
            for t in range(len(path), len(path) + reserve):
                vertex[(t, end)] = aid
        return vertex, edge

    def plan(self, start, goal, vertex_res, edge_res, agent_id=None,
             time_limit=2.0, window=WINDOW_STEPS_MIN, soft_goal=False):
        if start is None or goal is None:
            return None
        if start == goal:
            return [start]
        hmap = self._goal_h(goal)
        t0 = time.time()

        def blocked(u, v, t_arrive):
            owner = vertex_res.get((t_arrive, v))
            if owner is not None and owner != agent_id:
                return True
            return (t_arrive, v, u) in edge_res

        def reconstruct(came_from, state):
            path, cur = [], state
            while cur is not None:
                path.append(cur[0])
                cur = came_from.get(cur)
            path.reverse()
            return path

        open_heap = [(hmap.get(start, 0.0), 0, 0, start)]
        best_g = {(start, 0): 0}
        came_from = {(start, 0): None}
        best_partial = None
        while open_heap:
            if time.time() - t0 > time_limit:
                break
            f, g, t, u = heapq.heappop(open_heap)
            state = (u, t)
            if g > best_g.get(state, float("inf")):
                continue
            prog = -hmap.get(u, 1e9)
            cand = (prog, -t, state)
            if best_partial is None or cand > best_partial:
                best_partial = cand
            if u == goal:
                return reconstruct(came_from, state)
            if t >= window:
                continue
            t2 = t + 1
            if not blocked(u, u, t2):
                ng = g + 1
                nxt = (u, t2)
                if ng < best_g.get(nxt, float("inf")):
                    best_g[nxt] = ng
                    came_from[nxt] = state
                    heapq.heappush(open_heap, (ng + hmap.get(u, 0.0), ng, t2, u))
            for edge in self.graph.get_neighbors(u):
                v = edge["to"]
                if blocked(u, v, t2):
                    continue
                ng = g + 1
                nxt = (v, t2)
                if ng >= best_g.get(nxt, float("inf")):
                    continue
                best_g[nxt] = ng
                came_from[nxt] = state
                heapq.heappush(open_heap, (ng + hmap.get(v, 0.0), ng, t2, v))
        if soft_goal and best_partial is not None:
            path = reconstruct(came_from, best_partial[2])
            if len(path) >= 2:
                return path
        return None


class EnhancedMapfPlanner(MapfPathPlanner):
    def __init__(
        self,
        move_request_queue,
        agv_travel_status,
        log_cb=None,
        base_size=3,
        horizon_size=3,
        debug=False,
    ):
        super().__init__(
            move_request_queue,
            agv_travel_status,
            log_cb,
            base_size=base_size,
            horizon_size=horizon_size,
            debug=debug,
        )
        self._ecbs_graph = None
        self._graph_node_count = 0
        self._pending_replan = False
        self._pending_extension = False
        self._dirty_agents = set()
        self._collision_triggered = False
        self._fast_planner = None

    def reset(self):
        super().reset()
        self._ecbs_graph = None
        self._graph_node_count = 0
        self._pending_replan = False
        self._pending_extension = False
        self._dirty_agents = set()
        self._collision_triggered = False
        if getattr(self, "_fast_planner", None):
            self._fast_planner.clear_cache()

    def _handle_request(self, req):
        agv_id = req.get("agv_id")
        if agv_id:
            self._dirty_agents.add(agv_id)
        super()._handle_request(req)

    def update_data(self, agvs, graph):
        super().update_data(agvs, graph)
        if graph and len(graph.nodes) != self._graph_node_count:
            self._ecbs_graph = None
            self._graph_node_count = len(graph.nodes)
            self._fast_planner = FastSpaceTimePlanner(graph)
        elif graph and getattr(self, "_fast_planner", None) is None:
            self._fast_planner = FastSpaceTimePlanner(graph)

    def run(self):
        last_replan = 0.0
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

                large = len(self.agv_goals) > LARGE_FLEET_THRESHOLD

                got_request = False
                while not self.move_request_queue.empty():
                    try:
                        req = self.move_request_queue.get_nowait()
                        self._handle_request(req)
                        got_request = True
                    except queue.Empty:
                        break

                if not large:
                    if got_request:
                        self._replan_all()
                        last_replan = time.time()
                    self._issue_commands()
                    time.sleep(0.1)
                    continue

                if got_request:
                    self._pending_replan = True
                else:
                    if self._any_needs_extension():
                        self._pending_extension = True
                    for agv_id, agv in self.latest_agvs.items():
                        if (
                            agv_id in self.agv_goals
                            and getattr(agv, "collision_detected", False)
                            and getattr(agv, "current_speed", 0.0) < 0.05
                        ):
                            self._dirty_agents.add(agv_id)
                            self._pending_replan = True
                            self._collision_triggered = True
                            self.issued_state.pop(agv_id, None)
                            self.agv_plans.pop(agv_id, None)

                now = time.time()
                if self._pending_replan and self.move_request_queue.empty():
                    if now - last_replan >= REPLAN_DEBOUNCE_S:
                        self._replan_all()
                        last_replan = now
                        self._pending_replan = False
                        self._collision_triggered = False
                        if self._any_needs_extension():
                            self._pending_extension = True
                elif self._pending_extension and self.move_request_queue.empty():
                    if now - last_replan >= EXTENSION_DEBOUNCE_S:
                        self._replan_extension()
                        last_replan = now
                        self._pending_extension = False

                self._issue_commands()
            except Exception as e:
                self.log(f"Error: {e}", "ERROR")
                import traceback

                traceback.print_exc()
            time.sleep(0.04 if len(self.agv_goals) > LARGE_FLEET_THRESHOLD else 0.1)

    def _get_agv_node(self, agv):
        if agv.last_node_id and self.graph.get_node(agv.last_node_id):
            return agv.last_node_id
        return self._find_nearest_node(agv.position)

    def _agent_start_node(self, agv_id):
        agv = self.latest_agvs.get(agv_id)
        if not agv:
            for candidate in self.latest_agvs.values():
                if candidate.id == agv_id:
                    agv = candidate
                    break
        if not agv:
            return None
        issued_info = self.issued_state.get(agv_id)
        if issued_info and issued_info.get("issued_count", 0) > 0:
            segments = issued_info.get("full_path_segments", [])
            issued_count = issued_info.get("issued_count", 0)
            if issued_count < len(segments):
                return segments[issued_count]["source"]
        return self._get_agv_node(agv)

    def _remaining_segments(self, agv_id):
        info = self.issued_state.get(agv_id)
        if not info:
            return 999
        segments = info.get("full_path_segments") or []
        if not segments:
            return 999
        return len(segments) - info.get("issued_count", 0)

    def _remaining_node_path(self, agv_id):
        info = self.issued_state.get(agv_id)
        if not info:
            return None
        segments = info.get("full_path_segments", [])
        issued = info.get("issued_count", 0)
        if issued >= len(segments):
            return None
        nodes = [segments[issued]["source"]]
        for seg in segments[issued:]:
            nodes.append(seg["target"])
        return nodes if len(nodes) >= 2 else None

    def _path_fully_issued(self, agv_id):
        info = self.issued_state.get(agv_id)
        if not info:
            return False
        segments = info.get("full_path_segments") or []
        if not segments:
            return False
        return info.get("issued_count", 0) >= len(segments)

    def _any_needs_extension(self):
        if len(self.agv_goals) <= LARGE_FLEET_THRESHOLD:
            return False
        return any(self._path_fully_issued(aid) for aid in self.agv_goals)

    def _extension_agents(self):
        return [aid for aid in self.agv_goals if self._path_fully_issued(aid)]

    def _get_ecbs_params(self, num_active):
        if num_active <= 8:
            return 1.15, 30.0
        if num_active <= 12:
            return 1.12, 10.0
        if num_active <= 20:
            return 1.2, 8.0
        return 1.25, 6.0

    def _get_cached_ecbs_graph(self):
        if self._ecbs_graph is not None:
            return self._ecbs_graph
        self._ecbs_graph = super()._convert_graph_to_ecbs_standalone(self.graph)
        return self._ecbs_graph

    def _convert_graph_to_ecbs_standalone(self, graph):
        return self._get_cached_ecbs_graph()

    def _build_agents_config(self, agent_ids=None, include_idle=False):
        if agent_ids is None:
            goals = self.agv_goals.items()
        else:
            goals = ((aid, self.agv_goals[aid]) for aid in agent_ids if aid in self.agv_goals)
        agents_config = []
        active_ids = set()
        for agv_id, goal in goals:
            start = self._agent_start_node(agv_id)
            if start:
                agents_config.append({"id": agv_id, "start": start, "goal": goal})
                active_ids.add(agv_id)
        if include_idle:
            for agv_id, agv in self.latest_agvs.items():
                if agv_id in active_ids or agv_id in self.agv_goals:
                    continue
                node = self._get_agv_node(agv)
                if node:
                    agents_config.append(
                        {
                            "id": f"{OBSTACLE_PREFIX}{agv_id}",
                            "start": node,
                            "goal": node,
                        }
                    )
        return agents_config

    def _convoy_rank(self, agent):
        start = self.graph.get_node(agent["start"])
        goal = self.graph.get_node(agent["goal"])
        dist = self.graph.get_cost(agent["start"], agent["goal"]) or 0.0
        if start and goal:
            dy = float(goal.get("y", 0)) - float(start.get("y", 0))
            return (1 if dy < -0.1 else 0, -dist)
        return (0, -dist)

    def _large_fleet_plan_rank(self, agent):
        dist = self.graph.get_cost(agent["start"], agent["goal"]) or 1e9
        return (dist, self._convoy_rank(agent))

    def _agent_plan_window(self, start, goal):
        if not start or not goal or not self.graph:
            return WINDOW_STEPS_MAX
        dist = self.graph.get_cost(start, goal)
        if dist is None:
            return WINDOW_STEPS_MAX
        # Discrete steps ~ travel cost / typical edge length, with margin for waits.
        span = int(float(dist) * 2.8) + 48
        return min(WINDOW_STEPS_MAX, max(WINDOW_STEPS_MIN, span))

    def _paths_to_constraints(self, paths, goal_reserve=GOAL_RESERVE_STEPS):
        constraints = []
        for other_id, other_path in paths.items():
            for t, node in enumerate(other_path):
                constraints.append(Constraint(other_id, t, node))
            goal_node = other_path[-1]
            for t in range(len(other_path), len(other_path) + goal_reserve):
                constraints.append(Constraint(other_id, t, goal_node))
        return constraints

    def _prioritized_plan_fast(self, agents_config, reserved_paths=None, soft_goal=False):
        if not agents_config:
            return None
        if self._fast_planner is None:
            self._fast_planner = FastSpaceTimePlanner(self.graph)
        reserved_paths = reserved_paths or {}
        active = [
            a for a in agents_config if not str(a["id"]).startswith(OBSTACLE_PREFIX)
        ]
        active = sorted(
            active,
            key=self._large_fleet_plan_rank
            if len(self.agv_goals) > LARGE_FLEET_THRESHOLD
            else self._convoy_rank,
        )
        paths = dict(reserved_paths)
        reserve = GOAL_RESERVE_LARGE
        vertex_res, edge_res = FastSpaceTimePlanner.build_reservation(
            paths, goal_reserve=reserve
        )
        per_limit = min(2.5, max(0.6, 22.0 / max(1, len(active))))
        for agent in active:
            aid = agent["id"]
            if aid in paths:
                continue
            window = self._agent_plan_window(agent["start"], agent["goal"])
            path = self._fast_planner.plan(
                agent["start"],
                agent["goal"],
                vertex_res,
                edge_res,
                agent_id=aid,
                time_limit=per_limit,
                window=window,
                soft_goal=soft_goal,
            )
            if not path:
                continue
            paths[aid] = path
            for tt, node in enumerate(path):
                vertex_res[(tt, node)] = aid
                if tt > 0:
                    edge_res.add((tt, path[tt - 1], node))
            end = path[-1]
            if end == agent["goal"]:
                for tt in range(len(path), len(path) + reserve):
                    vertex_res[(tt, end)] = aid
            else:
                # Partial path: light occupancy so others can pass, but keep corridor.
                for tt in range(len(path), min(len(path) + 8, len(path) + reserve)):
                    vertex_res[(tt, end)] = aid
        planned_ids = {a["id"] for a in active}
        if not any(aid in paths for aid in planned_ids):
            return None
        return {aid: paths[aid] for aid in planned_ids if aid in paths}

    def _prioritized_plan(self, agents_config, reserved_paths=None):
        if len(self.agv_goals) > LARGE_FLEET_THRESHOLD:
            return self._prioritized_plan_fast(agents_config, reserved_paths)
        active = [
            a for a in agents_config if not str(a["id"]).startswith(OBSTACLE_PREFIX)
        ]
        if not active:
            return None
        reserved_paths = reserved_paths or {}
        active = sorted(active, key=self._convoy_rank)
        per_limit = min(6.0, max(2.5, 50.0 / len(active)))
        paths = dict(reserved_paths)
        for agent in active:
            if agent["id"] in paths:
                continue
            planner = ECBS(
                self.graph, [agent], sub_optimality=1.35, time_limit=per_limit
            )
            constraints = self._paths_to_constraints(paths)
            path, _ = planner.get_timed_path(agent["id"], constraints)
            if not path:
                continue
            paths[agent["id"]] = path
        planned_ids = {a["id"] for a in active}
        if not any(aid in paths for aid in planned_ids):
            return None
        return {aid: paths[aid] for aid in planned_ids if aid in paths}

    def _solve_paths_batched(self, agents_config, batch_size=BATCH_SIZE, reserved_paths=None):
        reserved_paths = reserved_paths or {}
        active = [
            a for a in agents_config if not str(a["id"]).startswith(OBSTACLE_PREFIX)
        ]
        active = sorted(active, key=self._convoy_rank)
        paths = dict(reserved_paths)
        for i in range(0, len(active), batch_size):
            batch = active[i : i + batch_size]
            batch_paths = self._prioritized_plan_fast(
                batch, reserved_paths=paths, soft_goal=True
            )
            if not batch_paths:
                continue
            for agent in batch:
                aid = agent["id"]
                if aid in batch_paths:
                    paths[aid] = batch_paths[aid]
        planned = {a["id"]: paths[a["id"]] for a in active if a["id"] in paths}
        return planned if planned else None

    def _solve_joint_cpp(self, agents_config, sub_opt, time_limit):
        ecbs_graph = self._get_cached_ecbs_graph()
        index_to_id = {}
        ecbs_agents = []
        for idx, cfg in enumerate(agents_config):
            index_to_id[idx] = cfg["id"]
            ecbs_agents.append(
                ecbs_standalone.Agent(idx, cfg["start"], cfg["goal"])
            )
        solver = ecbs_standalone.ECBS(
            ecbs_graph, ecbs_agents, sub_optimality=sub_opt, time_limit=time_limit
        )
        if not solver.solve():
            return None
        solution = solver.get_solution()
        return {
            index_to_id[i]: path
            for i, path in solution.items()
            if not str(index_to_id[i]).startswith(OBSTACLE_PREFIX)
        }

    def _merge_large_fleet_paths(self, active, paths, reserved_paths):
        paths = dict(paths or {})
        reserved_paths = reserved_paths or {}
        missing = [a for a in active if a["id"] not in paths]
        if missing:
            extra = self._fallback_per_agent(missing, {**reserved_paths, **paths})
            if extra:
                paths.update(extra)
        return paths if paths else None

    def _solve_paths(self, agents_config, reserved_paths=None):
        active = [
            a for a in agents_config if not str(a["id"]).startswith(OBSTACLE_PREFIX)
        ]
        num_active = len(active)
        if num_active == 0:
            return None
        reserved_paths = reserved_paths or {}
        sub_opt, time_limit = self._get_ecbs_params(num_active)
        cpp_ok = ECBS_STANDALONE_AVAILABLE and hasattr(ecbs_standalone, "Graph")

        if num_active > LARGE_FLEET_THRESHOLD:
            paths = self._prioritized_plan_fast(
                agents_config, reserved_paths, soft_goal=True
            )
            if paths and len(paths) >= num_active:
                return paths
            if paths and len(paths) >= max(1, num_active // 2):
                merged = self._merge_large_fleet_paths(active, paths, reserved_paths)
                if merged:
                    return merged
            paths = self._solve_paths_batched(
                agents_config, reserved_paths=reserved_paths
            )
            if paths:
                return self._merge_large_fleet_paths(active, paths, reserved_paths)
            return self._fallback_per_agent(agents_config, reserved_paths)

        if cpp_ok:
            try:
                paths = self._solve_joint_cpp(agents_config, sub_opt, time_limit)
                if paths:
                    return paths
                paths = self._solve_joint_cpp(
                    agents_config, max(sub_opt, 1.35), min(30.0, time_limit + 8.0)
                )
                if paths:
                    return paths
            except Exception as e:
                self.log(f"C++ ECBS failed: {e}", "WARN")

        if num_active <= 8:
            seq = self._prioritized_plan(agents_config, reserved_paths)
            if seq and len(seq) >= num_active:
                return seq

        py_limit = time_limit if num_active <= 8 else min(2.5, time_limit)
        ecbs = ECBS(
            self.graph,
            agents_config,
            sub_optimality=max(sub_opt, 1.25),
            time_limit=py_limit,
        )
        paths = ecbs.run()
        if paths:
            return {
                aid: path
                for aid, path in paths.items()
                if not str(aid).startswith(OBSTACLE_PREFIX)
            }
        return self._prioritized_plan(agents_config, reserved_paths)

    def _collect_keep_paths(self, exclude_ids=None):
        exclude_ids = exclude_ids or set()
        keep_paths = {}
        for agv_id in self.agv_goals:
            if agv_id in exclude_ids:
                continue
            path = self._remaining_node_path(agv_id)
            if path:
                keep_paths[agv_id] = path
        for agv_id, agv in self.latest_agvs.items():
            if agv_id in exclude_ids or agv_id in keep_paths or agv_id in self.agv_goals:
                continue
            node = self._get_agv_node(agv)
            if node:
                keep_paths[agv_id] = [node]
        return keep_paths

    def _fallback_per_agent(self, agents_config, reserved_paths=None):
        reserved_paths = reserved_paths or {}
        paths = dict(reserved_paths)
        planned = {}
        active = [
            a for a in agents_config if not str(a["id"]).startswith(OBSTACLE_PREFIX)
        ]
        for agent in sorted(active, key=self._convoy_rank):
            aid = agent["id"]
            one = self._prioritized_plan_fast(
                [agent], reserved_paths=paths, soft_goal=True
            )
            if one and aid in one:
                paths[aid] = one[aid]
                planned[aid] = one[aid]
        return planned if planned else None

    def _apply_planned_paths(self, paths):
        if len(paths) <= 12:
            self.log(f"ECBS planned for {len(paths)} agents")
        for agv_id, node_path in paths.items():
            if agv_id not in self.agv_goals:
                continue
            if str(agv_id).startswith(OBSTACLE_PREFIX):
                continue

            segments = []
            for i in range(len(node_path) - 1):
                u, v = node_path[i], node_path[i + 1]
                if u == v:
                    continue
                edge_id = None
                for edge in self.graph.get_neighbors(u):
                    if edge["to"] == v:
                        edge_id = edge.get("id", f"{u}_{v}")
                        break
                dependencies = []
                for other_id, other_path in paths.items():
                    if other_id == agv_id:
                        continue
                    if i < len(other_path) and other_path[i] == v:
                        dependencies.append({"agv": other_id, "node": v})
                        break
                    if i + 1 < len(other_path) and other_path[i + 1] == v:
                        dependencies.append({"agv": other_id, "node": v})
                        break
                segments.append(
                    {
                        "source": u,
                        "target": v,
                        "id": edge_id,
                        "dependencies": dependencies,
                    }
                )

            issued_info = self.issued_state.get(agv_id)
            if issued_info and issued_info.get("issued_count", 0) > 0:
                issued_count = issued_info["issued_count"]
                old_segments = issued_info.get("full_path_segments", [])
                base_segments = (
                    old_segments[:issued_count]
                    if issued_count <= len(old_segments)
                    else old_segments
                )
                full_segments = base_segments + segments
                self.issued_state[agv_id] = {
                    "issued_count": issued_count,
                    "full_path_segments": full_segments,
                    "last_base_sequence_id": issued_info.get("last_base_sequence_id", 0),
                    "order_id": issued_info.get("order_id"),
                    "order_update_id": issued_info.get("order_update_id", -1),
                }
                self.agv_plans[agv_id] = segments
            else:
                self.issued_state[agv_id] = {
                    "issued_count": 0,
                    "full_path_segments": segments,
                    "last_base_sequence_id": 0,
                    "order_id": None,
                    "order_update_id": -1,
                }
                self.agv_plans[agv_id] = segments
            self.agv_travel_status[agv_id] = {
                "status": "moving",
                "target_node": self.agv_goals[agv_id],
            }

    def _replan_all(self):
        all_ids = set(self.agv_goals.keys())
        large = len(all_ids) > LARGE_FLEET_THRESHOLD
        if large:
            self.base_size = HORIZON_LARGE
            self.horizon_size = HORIZON_LARGE
        else:
            self.base_size = HORIZON_BASE
            self.horizon_size = HORIZON_HORIZON
            if len(all_ids) > 3:
                self.base_size = 32
                self.horizon_size = 32

        dirty = self._dirty_agents & all_ids
        self._dirty_agents -= dirty
        extension_ids = set(self._extension_agents()) if large else set()

        if large and dirty and (self._collision_triggered or dirty < all_ids):
            need_ids = list(dirty | extension_ids)
            keep_paths = self._collect_keep_paths(exclude_ids=set(need_ids))
            agents_config = self._build_agents_config(agent_ids=need_ids)
            if not agents_config:
                return
            paths = self._solve_paths(agents_config, reserved_paths=keep_paths)
            if not paths:
                paths = self._prioritized_plan_fast(agents_config, keep_paths)
        else:
            if large:
                agents_config = self._build_agents_config()
                keep_paths = self._collect_keep_paths(exclude_ids=all_ids)
            else:
                # Small-fleet mode considers active agents only.
                agents_config = self._build_agents_config(include_idle=False)
                keep_paths = {}
            if not agents_config:
                return
            paths = self._solve_paths(agents_config, reserved_paths=keep_paths)
            if not paths and large:
                paths = self._solve_paths_batched(
                    agents_config, reserved_paths=keep_paths
                )
            if not paths:
                paths = self._prioritized_plan(agents_config, keep_paths)

        if not paths:
            self.log("ECBS failed to find solution", "WARN")
            if large:
                fallback = self._fallback_per_agent(agents_config, keep_paths)
                if fallback:
                    self._apply_planned_paths(fallback)
            return

        missing = [a for a in agents_config if a["id"] not in paths]
        if missing and large:
            extra = self._fallback_per_agent(missing, {**keep_paths, **paths})
            if extra:
                paths.update(extra)

        self._apply_planned_paths(paths)

    def _replan_extension(self):
        need_ids = self._extension_agents()
        if not need_ids:
            return
        large = len(self.agv_goals) > LARGE_FLEET_THRESHOLD
        if large:
            self.base_size = HORIZON_LARGE
            self.horizon_size = HORIZON_LARGE
        else:
            self.base_size = HORIZON_BASE
            self.horizon_size = HORIZON_HORIZON
        keep_paths = self._collect_keep_paths(exclude_ids=set(need_ids))
        agents_config = self._build_agents_config(agent_ids=need_ids)
        paths = self._solve_paths(agents_config, reserved_paths=keep_paths)
        if paths:
            self._apply_planned_paths(paths)
            return
        for agv_id in need_ids:
            single = self._build_agents_config(agent_ids=[agv_id])
            if not single:
                continue
            one = self._prioritized_plan_fast(
                single, reserved_paths=keep_paths, soft_goal=True
            )
            if one and agv_id in one:
                self._apply_planned_paths({agv_id: one[agv_id]})
                keep_paths[agv_id] = one[agv_id]
