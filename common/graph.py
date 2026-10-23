import heapq
import math
import numpy as np

class Graph:
    def __init__(self):
        self.nodes = {} # id -> {x, y, z, ...}
        self.edges = {} # from_id -> [ {to_id, cost, length, ...} ]
        self.adjacency_matrix = None
        self.node_id_to_index = None

    def add_vertex(self, v):
        self.nodes[v['id']] = v

    def add_edge(self, e):
        # e: {id, from, to, direction, length, cost, ...}
        f, t = e['from'], e['to']
        cost = e.get('cost') or e.get('length') or 1.0

        if f not in self.edges: self.edges[f] = []
        self.edges[f].append({
            'to': t,
            'cost': cost,
            'length': e.get('length', cost),
            'max_speed': e.get('max_speed', 1.0),
            'id': e['id']
        })

        if e.get('direction') == 'bidirectional':
            if t not in self.edges: self.edges[t] = []
            self.edges[t].append({
                'to': f,
                'cost': cost,
                'length': e.get('length', cost),
                'max_speed': e.get('max_speed', 1.0),
                'id': e['id']
            })

    def get_neighbors(self, node_id):
        return self.edges.get(node_id, [])

    def heuristic(self, u_id, v_id):
        if u_id not in self.nodes or v_id not in self.nodes:
            return 0
        return self.get_cost(u_id, v_id)

    def get_node(self, node_id):
        return self.nodes.get(node_id)

    def compute_adjacency_matrix(self):
        """
        Compute the all-pairs shortest-path matrix
        Use Floyd-Warshall to compute shortest paths
        Store results in adjacency_matrix and node_id_to_index
        """
        node_ids = sorted(self.nodes.keys())
        n = len(node_ids)
        self.node_id_to_index = {node_id: idx for idx, node_id in enumerate(node_ids)}


        self.adjacency_matrix = [[float('inf')] * n for _ in range(n)]


        for i in range(n):
            self.adjacency_matrix[i][i] = 0.0


        for from_id, edges_list in self.edges.items():
            if from_id not in self.node_id_to_index:
                continue
            from_idx = self.node_id_to_index[from_id]
            for edge in edges_list:
                to_id = edge['to']
                if to_id in self.node_id_to_index:
                    to_idx = self.node_id_to_index[to_id]
                    cost = edge['cost']

                    self.adjacency_matrix[from_idx][to_idx] = min(
                        self.adjacency_matrix[from_idx][to_idx], cost
                    )


        for k in range(n):
            for i in range(n):
                for j in range(n):

                    if self.adjacency_matrix[i][k] != float('inf') and \
                       self.adjacency_matrix[k][j] != float('inf'):
                        self.adjacency_matrix[i][j] = min(
                            self.adjacency_matrix[i][j],
                            self.adjacency_matrix[i][k] + self.adjacency_matrix[k][j]
                        )

        return self.adjacency_matrix, self.node_id_to_index

    def get_cost(self, from_id, to_id):
        """
        Get the shortest-path cost between two nodes
        Read the cached adjacency matrix.

        Parameters:
            from_id: source node ID
            to_id: target node ID

        Returns:
            Return the path cost when reachable
            Return None when unreachable
        """

        if self.adjacency_matrix is None or self.node_id_to_index is None:
            self.compute_adjacency_matrix()

        if from_id not in self.node_id_to_index or to_id not in self.node_id_to_index:
            return None

        from_idx = self.node_id_to_index[from_id]
        to_idx = self.node_id_to_index[to_id]
        cost = self.adjacency_matrix[from_idx][to_idx]


        if cost == float('inf'):
            return None

        return cost

def a_star_search(graph, start_id, goal_id):
    if start_id not in graph.nodes or goal_id not in graph.nodes:
        return None

    frontier = []
    heapq.heappush(frontier, (0, start_id))
    came_from = {start_id: None}
    cost_so_far = {start_id: 0}

    while frontier:
        _, current = heapq.heappop(frontier)

        if current == goal_id:
            break

        for edge in graph.get_neighbors(current):
            next_node = edge['to']
            new_cost = cost_so_far[current] + edge['cost']

            if next_node not in cost_so_far or new_cost < cost_so_far[next_node]:
                cost_so_far[next_node] = new_cost
                priority = new_cost + graph.heuristic(next_node, goal_id)
                heapq.heappush(frontier, (priority, next_node))
                came_from[next_node] = (current, edge['id']) # Store parent and edge used

    if goal_id not in came_from:
        return None

    # Reconstruct path
    path = []
    current = goal_id
    while current != start_id:
        parent_info = came_from[current]
        if parent_info is None: # Should not happen if path exists
            return None
        parent, edge_id = parent_info
        # Store edge with direction context
        path.append({'id': edge_id, 'source': parent, 'target': current})
        current = parent

    path.reverse()
    return path
