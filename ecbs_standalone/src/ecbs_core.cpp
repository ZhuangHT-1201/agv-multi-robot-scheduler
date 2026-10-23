#include "../include/ecbs_core.hpp"
#include <algorithm>
#include <limits>
#include <cmath>
#include <queue>
#include <set>
#include <unordered_set>
#include <functional>

namespace ecbs_standalone {

// ============================================================================

// ============================================================================

void Graph::addNode(const NodeId& id, double x, double y) {
    nodes[id] = Node(id, x, y);
}

void Graph::addEdge(const NodeId& from, const NodeId& to, double cost) {
    if (!hasNode(from) || !hasNode(to)) return;

    nodes[from].neighbors.push_back(to);
    edges[from][to] = cost;
}

bool Graph::hasNode(const NodeId& id) const {
    return nodes.find(id) != nodes.end();
}

const Node* Graph::getNode(const NodeId& id) const {
    auto it = nodes.find(id);
    return (it != nodes.end()) ? &(it->second) : nullptr;
}

const std::vector<NodeId>& Graph::getNeighbors(const NodeId& id) const {
    static const std::vector<NodeId> empty;
    auto it = nodes.find(id);
    return (it != nodes.end()) ? it->second.neighbors : empty;
}

double Graph::getCost(const NodeId& from, const NodeId& to) const {
    auto it1 = edges.find(from);
    if (it1 == edges.end()) return std::numeric_limits<double>::infinity();

    auto it2 = it1->second.find(to);
    if (it2 == it1->second.end()) return std::numeric_limits<double>::infinity();

    return it2->second;
}

std::unordered_map<NodeId, double> Graph::computeHeuristics(const NodeId& goal) const {
    std::unordered_map<NodeId, double> distances;


    std::queue<NodeId> q;
    distances[goal] = 0.0;
    q.push(goal);

    while (!q.empty()) {
        NodeId current = q.front();
        q.pop();

        double current_dist = distances[current];


        for (const auto& [node_id, node] : nodes) {
            if (distances.find(node_id) != distances.end()) continue;


            auto it = edges.find(node_id);
            if (it != edges.end() && it->second.find(current) != it->second.end()) {
                double edge_cost = it->second.at(current);
                distances[node_id] = current_dist + edge_cost;
                q.push(node_id);
            }
        }
    }

    return distances;
}

// ============================================================================

// ============================================================================

ECBS::ECBS(const Graph& graph, const std::vector<Agent>& agents,
           double sub_optimality, double time_limit)
    : graph_(graph), agents_(agents),
      sub_optimality_(sub_optimality), time_limit_(time_limit),
      makespan_(0), soc_(0), solved_(false), computation_time_(0.0),
      expanded_nodes_(0), generated_nodes_(0) {

    precomputeHeuristics();
}

void ECBS::precomputeHeuristics() {
    for (const auto& agent : agents_) {
        heuristics_[agent.id] = graph_.computeHeuristics(agent.goal);
    }
}

double ECBS::getHeuristic(AgentId agent_id, const NodeId& node) const {
    auto it1 = heuristics_.find(agent_id);
    if (it1 == heuristics_.end()) return 0.0;

    auto it2 = it1->second.find(node);
    if (it2 == it1->second.end()) return std::numeric_limits<double>::infinity();

    return it2->second;
}

bool ECBS::overTimeLimit() const {
    auto current = std::chrono::steady_clock::now();
    double elapsed = std::chrono::duration<double>(current - start_time_).count();
    return elapsed > time_limit_;
}

bool ECBS::solve() {
    start_time_ = std::chrono::steady_clock::now();
    solved_ = false;


    std::function<bool(const HighLevelNodePtr&, const HighLevelNodePtr&)> compareOPEN =
        [](const HighLevelNodePtr& a, const HighLevelNodePtr& b) {
            return a->lower_bound > b->lower_bound;
        };

    std::function<bool(const HighLevelNodePtr&, const HighLevelNodePtr&)> compareFOCAL =
        [](const HighLevelNodePtr& a, const HighLevelNodePtr& b) {
            if (a->conflict_count != b->conflict_count)
                return a->conflict_count > b->conflict_count;
            return a->soc > b->soc;
        };

    std::priority_queue<HighLevelNodePtr, std::vector<HighLevelNodePtr>,
                       decltype(compareOPEN)> OPEN(compareOPEN);
    std::priority_queue<HighLevelNodePtr, std::vector<HighLevelNodePtr>,
                       decltype(compareFOCAL)> FOCAL(compareFOCAL);


    HighLevelNodePtr initial = std::make_shared<HighLevelNode>();
    setInitialHighLevelNode(initial);

    if (!initial->valid) {
        computation_time_ = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - start_time_).count();
        return false;
    }

    OPEN.push(initial);
    FOCAL.push(initial);
    int LB_min = initial->lower_bound;


    while (!OPEN.empty()) {
        if (overTimeLimit()) break;


        while (!OPEN.empty() && !OPEN.top()->valid) {
            OPEN.pop();
        }
        if (OPEN.empty()) break;


        if (LB_min != OPEN.top()->lower_bound) {
            LB_min = OPEN.top()->lower_bound;
            double LB_bound = LB_min * sub_optimality_;


            std::priority_queue<HighLevelNodePtr, std::vector<HighLevelNodePtr>,
                               decltype(compareFOCAL)> new_FOCAL(compareFOCAL);

            std::vector<HighLevelNodePtr> tmp;
            while (!OPEN.empty()) {
                auto top = OPEN.top();
                OPEN.pop();
                if (!top->valid) continue;
                tmp.push_back(top);

                if (static_cast<double>(top->lower_bound) > LB_bound) break;

                new_FOCAL.push(top);
            }


            for (const auto& node : tmp) {
                OPEN.push(node);
            }

            FOCAL.swap(new_FOCAL);
        }

        if (FOCAL.empty()) {

            double LB_bound = LB_min * sub_optimality_;
            std::priority_queue<HighLevelNodePtr, std::vector<HighLevelNodePtr>,
                               decltype(compareFOCAL)> new_FOCAL(compareFOCAL);
            std::vector<HighLevelNodePtr> tmp;

            while (!OPEN.empty()) {
                auto top = OPEN.top();
                OPEN.pop();
                if (!top->valid) continue;
                tmp.push_back(top);
                if (static_cast<double>(top->lower_bound) <= LB_bound) {
                    new_FOCAL.push(top);
                }
            }

            for (const auto& node : tmp) {
                OPEN.push(node);
            }

            FOCAL.swap(new_FOCAL);

            if (FOCAL.empty()) break;
        }


        HighLevelNodePtr current = FOCAL.top();
        FOCAL.pop();
        current->valid = false;
        expanded_nodes_++;


        auto conflicts = getFirstConflict(current->paths);
        if (conflicts.empty()) {

            solved_ = true;
            solution_ = current->paths;
            makespan_ = current->makespan;
            soc_ = current->soc;
            break;
        }


        for (const auto& constraint : conflicts) {
            Constraints new_constraints = current->constraints;
            new_constraints.push_back(constraint);

            HighLevelNodePtr child = std::make_shared<HighLevelNode>();
            child->paths = current->paths;
            child->constraints = new_constraints;
            child->makespan = current->makespan;
            child->soc = current->soc;
            child->conflict_count = current->conflict_count;
            child->lower_bound = current->lower_bound;
            child->f_mins = current->f_mins;
            child->valid = true;

            invoke(child, constraint.agent_id);

            if (!child->valid) continue;

            generated_nodes_++;
            OPEN.push(child);
            if (child->lower_bound <= LB_min * sub_optimality_) {
                FOCAL.push(child);
            }
        }
    }

    computation_time_ = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start_time_).count();

    return solved_;
}

void ECBS::setInitialHighLevelNode(HighLevelNodePtr node) {
    Paths paths;
    std::unordered_map<AgentId, int> f_mins;


    for (const auto& agent : agents_) {
        Path path = getInitialPath(agent.id, paths);
        if (path.empty()) {
            node->valid = false;
            return;
        }


        paths[agent.id] = path;


        f_mins[agent.id] = static_cast<int>(path.size()) - 1;
    }


    node->paths = paths;
    node->constraints.clear();
    node->makespan = getMakespan(paths);
    node->soc = getSOC(paths);
    node->conflict_count = countConflicts(paths);
    node->f_mins = f_mins;
    node->lower_bound = node->soc;
    node->valid = true;
}

Path ECBS::getInitialPath(AgentId agent_id, const Paths& existing_paths) {
    if (agent_id < 0 || agent_id >= static_cast<int>(agents_.size())) {
        return Path();
    }

    const Agent& agent = agents_[agent_id];
    const NodeId& start = agent.start;
    const NodeId& goal = agent.goal;


    if (start == goal) {
        return {start};
    }


    std::unordered_set<NodeId> all_goals;
    all_goals.reserve(agents_.size());
    for (const auto& a : agents_) {
        all_goals.insert(a.goal);
    }

    Path path;
    path.reserve(100);
    path.push_back(start);

    NodeId current = start;
    Timestep t = 1;
    int makespan = getMakespan(existing_paths);
    int num_agents = static_cast<int>(agents_.size());


    while (current != goal) {
        const std::vector<NodeId>& neighbors = graph_.getNeighbors(current);
        if (neighbors.empty()) {
            return Path();
        }


        NodeId best_neighbor = *std::min_element(
            neighbors.begin(), neighbors.end(),
            [&](const NodeId& a, const NodeId& b) -> bool {

                double dist_a = getHeuristic(agent_id, a);
                double dist_b = getHeuristic(agent_id, b);
                if (dist_a != dist_b) {
                    return dist_a < dist_b;
                }


                if (t <= makespan) {
                    for (int i = 0; i < num_agents; ++i) {
                        if (i == agent_id) continue;

                        auto it = existing_paths.find(i);
                        if (it == existing_paths.end() || it->second.empty()) continue;

                        const Path& other_path = it->second;
                        NodeId v;
                        if (t < static_cast<int>(other_path.size())) {
                            v = other_path[t];
                        } else {
                            v = other_path.back();
                        }

                        if (v == a) return false;
                        if (v == b) return true;
                    }
                }


                if (a != goal && all_goals.count(a) > 0) return false;
                if (b != goal && all_goals.count(b) > 0) return true;

                return false;
            });

        path.push_back(best_neighbor);
        current = best_neighbor;
        t++;


        if (t > 100000) {
            return Path();
        }
    }

    return path;
}

void ECBS::invoke(HighLevelNodePtr node, AgentId agent_id) {
    auto [path, f_min] = getFocalPath(node, agent_id);


    if (path.empty()) {
        node->valid = false;
        return;
    }



    int old_conflicts = 0;
    auto it = node->paths.find(agent_id);
    if (it != node->paths.end() && !it->second.empty()) {
        old_conflicts = countPathConflicts(agent_id, it->second, node->paths);
    }



    Paths temp_paths = node->paths;
    temp_paths[agent_id] = path;



    int new_conflicts = countPathConflicts(agent_id, path, temp_paths);



    node->conflict_count = node->conflict_count - old_conflicts + new_conflicts;

    // Update a path
    node->paths = temp_paths;


    node->makespan = getMakespan(node->paths);
    node->soc = getSOC(node->paths);



    int old_f_min = node->f_mins[agent_id];
    node->lower_bound = node->lower_bound - old_f_min + f_min;
    node->f_mins[agent_id] = f_min;
}

std::pair<Path, int> ECBS::getFocalPath(const HighLevelNodePtr& node, AgentId agent_id) {

    Constraints agent_constraints;
    for (const auto& c : node->constraints) {
        if (c.agent_id == agent_id) {
            agent_constraints.push_back(c);
        }
    }


    const Agent* agent = nullptr;
    for (const auto& a : agents_) {
        if (a.id == agent_id) {
            agent = &a;
            break;
        }
    }
    if (!agent) return {Path(), 0};


    Timestep max_constraint_time = -1;
    for (const auto& c : agent_constraints) {
        if (c.v == agent->goal && !c.is_edge_constraint) {
            max_constraint_time = std::max(max_constraint_time, c.t);
        }
    }


    updatePathTable(node->paths, agent_id);


    double path_dist = getHeuristic(agent_id, agent->start);

    auto f1_value = [this, agent_id, agent, path_dist, max_constraint_time](
        const std::shared_ptr<FocalNode>& n) -> int {

        double h = getHeuristic(agent_id, n->v);

        // if (pathDist(id) > max_constraint_time) {
        //   f1Value = [&](FocalNode* n) { return n->g + pathDist(id, n->v); };
        // } else {
        //   f1Value = [&](FocalNode* n) {
        //     return std::max(max_constraint_time + 1, n->g + pathDist(id, n->v));
        //   };
        // }
        if (path_dist > max_constraint_time) {
            return static_cast<int>(n->g + h);
        } else {
            return std::max(max_constraint_time + 1, static_cast<int>(n->g + h));
        }
    };

    auto f2_value = [this, &node](const std::shared_ptr<FocalNode>& n) -> int {
        if (n->g == 0) return 0;


        int parent_f2 = (n->parent) ? n->parent->f2 : 0;
        int makespan = node->makespan;


        if (n->g > makespan) {


            auto makespan_it = path_table_.find(makespan);
            if (makespan_it != path_table_.end()) {
                // PATH_TABLE[makespan][n->v->id] != Solver::NIL
                if (makespan_it->second.find(n->v) != makespan_it->second.end()) {
                    return parent_f2 + 1;
                }
            }
        } else {

            auto t_it = path_table_.find(n->g);
            if (t_it != path_table_.end()) {
                if (t_it->second.find(n->v) != t_it->second.end()) {
                    return parent_f2 + 1;
                }
            }


            //          PATH_TABLE[n->g - 1][n->v->id] == PATH_TABLE[n->g][n->p->v->id]
            if (n->parent && n->g > 0) {
                auto curr_it = path_table_.find(n->g);
                auto prev_it = path_table_.find(n->g - 1);

                if (curr_it != path_table_.end() && prev_it != path_table_.end()) {

                    auto parent_at_curr = curr_it->second.find(n->parent->v);
                    if (parent_at_curr != curr_it->second.end()) {
                        AgentId other_agent = parent_at_curr->second;


                        auto curr_at_prev = prev_it->second.find(n->v);
                        if (curr_at_prev != prev_it->second.end() &&
                            curr_at_prev->second == other_agent) {
                            return parent_f2 + 1;
                        }
                    }
                }
            }
        }

        return parent_f2;
    };


    auto result = getTimedPathByFocalSearch(agent->start, agent->goal, sub_optimality_,
                                            f1_value, f2_value, agent_constraints,
                                            max_constraint_time);



    return result;
}

std::pair<Path, int> ECBS::getTimedPathByFocalSearch(
    const NodeId& start, const NodeId& goal, double w,
    const std::function<int(const std::shared_ptr<FocalNode>&)>& f1_value,
    const std::function<int(const std::shared_ptr<FocalNode>&)>& f2_value,
    const Constraints& agent_constraints,
    Timestep max_constraint_time) {




    struct PairHash {
        std::size_t operator()(const std::pair<NodeId, Timestep>& p) const {
            std::hash<NodeId> h1;
            std::hash<Timestep> h2;
            return h1(p.first) ^ (h2(p.second) << 1);
        }
    };


    std::function<bool(const std::shared_ptr<FocalNode>&, const std::shared_ptr<FocalNode>&)> compareOPEN =
        [](const std::shared_ptr<FocalNode>& a, const std::shared_ptr<FocalNode>& b) {
            if (a->f1 != b->f1) return a->f1 > b->f1;
            return false;
        };

    std::function<bool(const std::shared_ptr<FocalNode>&, const std::shared_ptr<FocalNode>&)> compareFOCAL =
        [](const std::shared_ptr<FocalNode>& a, const std::shared_ptr<FocalNode>& b) {
            if (a->f2 != b->f2) return a->f2 > b->f2;
            if (a->f1 != b->f1) return a->f1 > b->f1;
            if (a->g != b->g) return a->g < b->g;
            return false;
        };

    // OPEN, FOCAL, CLOSED
    std::priority_queue<std::shared_ptr<FocalNode>,
                       std::vector<std::shared_ptr<FocalNode>>,
                       decltype(compareOPEN)> OPEN(compareOPEN);
    std::priority_queue<std::shared_ptr<FocalNode>,
                       std::vector<std::shared_ptr<FocalNode>>,
                       decltype(compareFOCAL)> FOCAL(compareFOCAL);


    std::unordered_set<std::pair<NodeId, Timestep>, PairHash> CLOSED;


    auto start_node = std::make_shared<FocalNode>(start, 0, 0, 0);
    start_node->f1 = f1_value(start_node);
    start_node->f2 = f2_value(start_node);

    OPEN.push(start_node);
    FOCAL.push(start_node);
    int f1_min = start_node->f1;

    std::shared_ptr<FocalNode> best_node = nullptr;


    while (!OPEN.empty()) {
        if (overTimeLimit()) break;


        while (!OPEN.empty() &&
               CLOSED.count({OPEN.top()->v, OPEN.top()->g}) > 0) {
            OPEN.pop();
        }
        if (OPEN.empty()) break;


        if (OPEN.top()->f1 != f1_min) {
            f1_min = OPEN.top()->f1;
            double f1_bound = f1_min * w;


            std::priority_queue<std::shared_ptr<FocalNode>,
                               std::vector<std::shared_ptr<FocalNode>>,
                               decltype(compareFOCAL)> new_FOCAL(compareFOCAL);

            std::vector<std::shared_ptr<FocalNode>> tmp;
            while (!OPEN.empty()) {
                auto top = OPEN.top();
                OPEN.pop();
                if (CLOSED.count({top->v, top->g}) > 0) continue;
                tmp.push_back(top);
                if (static_cast<double>(top->f1) > f1_bound) break;
                new_FOCAL.push(top);
            }


            for (const auto& node : tmp) {
                OPEN.push(node);
            }
            FOCAL.swap(new_FOCAL);
        }


        auto current = FOCAL.top();
        FOCAL.pop();


        auto node_key = std::make_pair(current->v, current->g);
        if (CLOSED.count(node_key) > 0) continue;
        CLOSED.insert(node_key);


        if (current->v == goal && current->g > max_constraint_time) {
            best_node = current;
            break;
        }


        std::vector<NodeId> candidates = graph_.getNeighbors(current->v);
        candidates.push_back(current->v);

        for (const auto& next_v : candidates) {
            Timestep next_g = current->g + 1;


            if (CLOSED.count({next_v, next_g}) > 0) continue;


            if (isConstrained(current->v, next_v, next_g, agent_constraints)) continue;


            auto succ = std::make_shared<FocalNode>(next_v, next_g, 0, 0);
            succ->parent = current;


            succ->f1 = f1_value(succ);
            succ->f2 = f2_value(succ);


            OPEN.push(succ);
            if (static_cast<double>(succ->f1) <= f1_min * w) {
                FOCAL.push(succ);
            }
        }
    }

    if (best_node) {
        return {reconstructPath(best_node), f1_min};
    }

    return {Path(), 0};
}

Path ECBS::reconstructPath(const std::shared_ptr<FocalNode>& node) {
    Path path;
    auto current = node;
    while (current) {
        path.push_back(current->v);
        current = current->parent;
    }
    std::reverse(path.begin(), path.end());
    return path;
}

bool ECBS::isConstrained(const NodeId& u, const NodeId& v, Timestep t,
                        const Constraints& constraints) const {
    for (const auto& c : constraints) {
        if (c.t == t && c.v == v) {
            if (!c.is_edge_constraint || c.u == u) {
                return true;
            }
        }
    }
    return false;
}

std::vector<Constraint> ECBS::getFirstConflict(const Paths& paths) {
    int num_agents = agents_.size();
    int makespan = getMakespan(paths);


    for (Timestep t = 1; t <= makespan; ++t) {
        for (int i = 0; i < num_agents; ++i) {
            auto it_i = paths.find(i);
            if (it_i == paths.end() || it_i->second.empty()) continue;

            for (int j = i + 1; j < num_agents; ++j) {
                auto it_j = paths.find(j);
                if (it_j == paths.end() || it_j->second.empty()) continue;

                const Path& path_i = it_i->second;
                const Path& path_j = it_j->second;


                NodeId v_i, v_j;
                if (t < static_cast<int>(path_i.size())) {
                    v_i = path_i[t];
                } else {
                    v_i = path_i.back();
                }

                if (t < static_cast<int>(path_j.size())) {
                    v_j = path_j[t];
                } else {
                    v_j = path_j.back();
                }


                if (v_i == v_j) {
                    return {
                        Constraint(i, t, v_i),
                        Constraint(j, t, v_j)
                    };
                }


                // paths.get(i, t) == paths.get(j, t - 1) && paths.get(j, t) == paths.get(i, t - 1)
                if (t > 0 && t < static_cast<int>(path_i.size()) && t < static_cast<int>(path_j.size())) {
                    NodeId u_i = path_i[t - 1];
                    NodeId u_j = path_j[t - 1];

                    if (v_i == u_j && v_j == u_i) {
                        return {
                            Constraint(i, t, v_i, u_i),
                            Constraint(j, t, v_j, u_j)
                        };
                    }
                }
            }
        }
    }

    return {};
}

int ECBS::countConflicts(const Paths& paths) {
    int count = 0;
    int num_agents = agents_.size();
    int makespan = getMakespan(paths);


    for (int i = 0; i < num_agents; ++i) {
        auto it_i = paths.find(i);
        if (it_i == paths.end() || it_i->second.empty()) continue;

        for (int j = i + 1; j < num_agents; ++j) {
            auto it_j = paths.find(j);
            if (it_j == paths.end() || it_j->second.empty()) continue;

            const Path& path_i = it_i->second;
            const Path& path_j = it_j->second;


            for (int t = 1; t <= makespan; ++t) {

                NodeId v_i, v_j;
                if (t < static_cast<int>(path_i.size())) {
                    v_i = path_i[t];
                } else {
                    v_i = path_i.back();
                }

                if (t < static_cast<int>(path_j.size())) {
                    v_j = path_j[t];
                } else {
                    v_j = path_j.back();
                }


                if (v_i == v_j) {
                    count++;
                    continue;
                }


                // paths.get(i, t) == paths.get(j, t - 1) && paths.get(j, t) == paths.get(i, t - 1)
                if (t < static_cast<int>(path_i.size()) && t < static_cast<int>(path_j.size())) {
                    NodeId u_i = path_i[t - 1];
                    NodeId u_j = path_j[t - 1];

                    if (v_i == u_j && v_j == u_i) {
                        count++;
                    }
                }
            }
        }
    }

    return count;
}

int ECBS::countPathConflicts(AgentId agent_id, const Path& path,
                             const Paths& all_paths) {
    int count = 0;
    int makespan = getMakespan(all_paths);
    int num_agents = agents_.size();
    int path_size = static_cast<int>(path.size());


    for (int i = 0; i < num_agents; ++i) {
        if (i == agent_id) continue;

        auto it = all_paths.find(i);
        if (it == all_paths.end() || it->second.empty()) continue;

        const Path& other_path = it->second;


        for (int t = 1; t < path_size; ++t) {
            if (t > makespan) {

                if (path[t] == other_path.back()) {
                    count++;
                    break;
                }
                continue;
            }


            NodeId other_pos_t;
            if (t < static_cast<int>(other_path.size())) {
                other_pos_t = other_path[t];
            } else {
                other_pos_t = other_path.back();
            }


            if (path[t] == other_pos_t) {
                count++;
                continue;
            }


            if (t > 0) {
                NodeId other_pos_t_minus_1;
                if (t - 1 < static_cast<int>(other_path.size())) {
                    other_pos_t_minus_1 = other_path[t - 1];
                } else {
                    other_pos_t_minus_1 = other_path.back();
                }


                if (path[t] == other_pos_t_minus_1 && path[t - 1] == other_pos_t) {
                    count++;
                }
            }
        }
    }

    return count;
}

void ECBS::updatePathTable(const Paths& paths, AgentId exclude_agent) {

    path_table_.clear();

    int makespan = getMakespan(paths);
    if (makespan == 0) return;


    for (const auto& [aid, path] : paths) {
        if (aid == exclude_agent) continue;
        if (path.empty()) continue;


        for (Timestep t = 0; t <= makespan; ++t) {
            NodeId v;
            if (t < static_cast<int>(path.size())) {
                v = path[t];
            } else {
                v = path.back();
            }



            if (path_table_[t].find(v) == path_table_[t].end()) {
                path_table_[t][v] = aid;
            }
        }
    }
}

int ECBS::getMakespan(const Paths& paths) const {
    int max_len = 0;
    for (const auto& [aid, path] : paths) {
        max_len = std::max(max_len, static_cast<int>(path.size()) - 1);
    }
    return max_len;
}

int ECBS::getSOC(const Paths& paths) const {

    int soc = 0;
    for (const auto& [aid, path] : paths) {
        if (path.empty()) continue;


        for (size_t t = 1; t < path.size(); ++t) {
            if (path[t] != path[t-1]) {

                soc += 1;
            }
        }
    }
    return soc;
}

} // namespace ecbs_standalone
