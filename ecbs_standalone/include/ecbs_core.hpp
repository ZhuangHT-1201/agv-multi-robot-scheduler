#pragma once

#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <queue>
#include <memory>
#include <string>
#include <functional>
#include <chrono>

namespace ecbs_standalone {


using NodeId = std::string;
using AgentId = int;
using Timestep = int;


struct Node {
    NodeId id;
    double x, y;
    std::vector<NodeId> neighbors;

    Node() = default;
    Node(const NodeId& _id, double _x, double _y) : id(_id), x(_x), y(_y) {}
};


class Graph {
public:
    std::unordered_map<NodeId, Node> nodes;
    std::unordered_map<NodeId, std::unordered_map<NodeId, double>> edges; // node -> neighbor -> cost

    void addNode(const NodeId& id, double x, double y);
    void addEdge(const NodeId& from, const NodeId& to, double cost = 1.0);
    bool hasNode(const NodeId& id) const;
    const Node* getNode(const NodeId& id) const;
    const std::vector<NodeId>& getNeighbors(const NodeId& id) const;
    double getCost(const NodeId& from, const NodeId& to) const;


    std::unordered_map<NodeId, double> computeHeuristics(const NodeId& goal) const;
};


struct Agent {
    AgentId id;
    NodeId start;
    NodeId goal;

    Agent() = default;
    Agent(AgentId _id, const NodeId& _start, const NodeId& _goal)
        : id(_id), start(_start), goal(_goal) {}
};


using Path = std::vector<NodeId>;
using Paths = std::unordered_map<AgentId, Path>;


struct Constraint {
    AgentId agent_id;
    Timestep t;
    NodeId v;
    NodeId u;
    bool is_edge_constraint;

    Constraint(AgentId aid, Timestep _t, const NodeId& _v)
        : agent_id(aid), t(_t), v(_v), u(""), is_edge_constraint(false) {}

    Constraint(AgentId aid, Timestep _t, const NodeId& _v, const NodeId& _u)
        : agent_id(aid), t(_t), v(_v), u(_u), is_edge_constraint(true) {}
};
using Constraints = std::vector<Constraint>;


struct FocalNode {
    NodeId v;
    Timestep g;
    int f1;
    int f2;
    std::shared_ptr<FocalNode> parent;

    FocalNode(const NodeId& _v, Timestep _g, int _f1, int _f2)
        : v(_v), g(_g), f1(_f1), f2(_f2), parent(nullptr) {}
};


struct HighLevelNode {
    Paths paths;
    Constraints constraints;
    int makespan;
    int soc;  // Sum of Costs
    int conflict_count;
    int lower_bound;
    std::unordered_map<AgentId, int> f_mins;
    bool valid;

    HighLevelNode()
        : makespan(0), soc(0), conflict_count(0), lower_bound(0), valid(true) {}
};
using HighLevelNodePtr = std::shared_ptr<HighLevelNode>;


class ECBS {
public:
    ECBS(const Graph& graph, const std::vector<Agent>& agents,
         double sub_optimality = 1.1, double time_limit = 5.0);


    bool solve();


    const Paths& getSolution() const { return solution_; }
    int getMakespan() const { return makespan_; }
    int getSOC() const { return soc_; }
    double getComputationTime() const { return computation_time_; }
    bool succeeded() const { return solved_; }


    int getExpandedNodes() const { return expanded_nodes_; }
    int getGeneratedNodes() const { return generated_nodes_; }

private:

    const Graph& graph_;
    std::vector<Agent> agents_;


    double sub_optimality_;
    double time_limit_;


    Paths solution_;
    int makespan_;
    int soc_;
    bool solved_;
    double computation_time_;


    int expanded_nodes_;
    int generated_nodes_;


    std::chrono::steady_clock::time_point start_time_;
    bool overTimeLimit() const;


    std::unordered_map<AgentId, std::unordered_map<NodeId, double>> heuristics_;
    void precomputeHeuristics();


    void setInitialHighLevelNode(HighLevelNodePtr node);
    Path getInitialPath(AgentId agent_id, const Paths& existing_paths);
    void invoke(HighLevelNodePtr node, AgentId agent_id);


    std::pair<Path, int> getFocalPath(const HighLevelNodePtr& node, AgentId agent_id);
    std::pair<Path, int> getTimedPathByFocalSearch(
        const NodeId& start, const NodeId& goal,
        double w,  // sub-optimality
        const std::function<int(const std::shared_ptr<FocalNode>&)>& f1_value,
        const std::function<int(const std::shared_ptr<FocalNode>&)>& f2_value,
        const Constraints& agent_constraints,
        Timestep max_constraint_time);

    Path reconstructPath(const std::shared_ptr<FocalNode>& node);


    bool isConstrained(const NodeId& u, const NodeId& v, Timestep t,
                      const Constraints& constraints) const;


    std::vector<Constraint> getFirstConflict(const Paths& paths);
    int countConflicts(const Paths& paths);
    int countPathConflicts(AgentId agent_id, const Path& path, const Paths& all_paths);


    int getMakespan(const Paths& paths) const;
    int getSOC(const Paths& paths) const;
    double getHeuristic(AgentId agent_id, const NodeId& node) const;


    std::unordered_map<Timestep, std::unordered_map<NodeId, AgentId>> path_table_;
    void updatePathTable(const Paths& paths, AgentId exclude_agent = -1);
};


struct ECBSResult {
    bool success;
    Paths paths;
    int makespan;
    int soc;
    double computation_time;
    std::string error_message;

    ECBSResult() : success(false), makespan(0), soc(0), computation_time(0.0) {}
};

} // namespace ecbs_standalone
