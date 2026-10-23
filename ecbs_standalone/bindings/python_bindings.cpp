#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>
#include "../include/ecbs_core.hpp"

namespace py = pybind11;
using namespace ecbs_standalone;

PYBIND11_MODULE(ecbs_standalone, m) {
    m.doc() = "ECBS (Enhanced Conflict-Based Search) C++ implementation with Python bindings";

    // Node class
    py::class_<Node>(m, "Node")
        .def(py::init<>())
        .def(py::init<const NodeId&, double, double>())
        .def_readwrite("id", &Node::id)
        .def_readwrite("x", &Node::x)
        .def_readwrite("y", &Node::y)
        .def_readwrite("neighbors", &Node::neighbors);

    // Graph class
    py::class_<Graph>(m, "Graph")
        .def(py::init<>())
        .def("add_node", &Graph::addNode,
             "Add a node to the graph",
             py::arg("id"), py::arg("x"), py::arg("y"))
        .def("add_edge", &Graph::addEdge,
             "Add an edge to the graph",
             py::arg("from"), py::arg("to"), py::arg("cost") = 1.0)
        .def("has_node", &Graph::hasNode,
             "Check if a node exists",
             py::arg("id"))
        .def("get_node", &Graph::getNode,
             "Get a node by ID",
             py::arg("id"),
             py::return_value_policy::reference)
        .def("get_neighbors", &Graph::getNeighbors,
             "Get neighbors of a node",
             py::arg("id"),
             py::return_value_policy::reference)
        .def("get_cost", &Graph::getCost,
             "Get edge cost",
             py::arg("from"), py::arg("to"))
        .def("compute_heuristics", &Graph::computeHeuristics,
             "Compute heuristics from all nodes to a goal",
             py::arg("goal"),
             py::call_guard<py::gil_scoped_release>())
        .def_readonly("nodes", &Graph::nodes)
        .def_readonly("edges", &Graph::edges);

    // Agent class
    py::class_<Agent>(m, "Agent")
        .def(py::init<>())
        .def(py::init<AgentId, const NodeId&, const NodeId&>())
        .def_readwrite("id", &Agent::id)
        .def_readwrite("start", &Agent::start)
        .def_readwrite("goal", &Agent::goal);

    // Constraint class
    py::class_<Constraint>(m, "Constraint")
        .def(py::init<AgentId, Timestep, const NodeId&>(),
             "Create a vertex constraint")
        .def(py::init<AgentId, Timestep, const NodeId&, const NodeId&>(),
             "Create an edge constraint")
        .def_readwrite("agent_id", &Constraint::agent_id)
        .def_readwrite("t", &Constraint::t)
        .def_readwrite("v", &Constraint::v)
        .def_readwrite("u", &Constraint::u)
        .def_readwrite("is_edge_constraint", &Constraint::is_edge_constraint);

    // ECBS class
    py::class_<ECBS>(m, "ECBS")
        .def(py::init<const Graph&, const std::vector<Agent>&, double, double>(),
             "Initialize ECBS solver",
             py::arg("graph"),
             py::arg("agents"),
             py::arg("sub_optimality") = 1.1,
             py::arg("time_limit") = 5.0)
        .def("solve", &ECBS::solve,
             "Run the ECBS algorithm",
             py::call_guard<py::gil_scoped_release>())
        .def("get_solution", &ECBS::getSolution,
             "Get the solution paths",
             py::return_value_policy::reference)
        .def("get_makespan", [](const ECBS& self) { return self.getMakespan(); },
             "Get the makespan of the solution")
        .def("get_soc", [](const ECBS& self) { return self.getSOC(); },
             "Get the sum of costs")
        .def("get_computation_time", [](const ECBS& self) { return self.getComputationTime(); },
             "Get the computation time in seconds")
        .def("succeeded", [](const ECBS& self) { return self.succeeded(); },
             "Check if the solver found a solution")
        .def("get_expanded_nodes", [](const ECBS& self) { return self.getExpandedNodes(); },
             "Get the number of expanded nodes")
        .def("get_generated_nodes", [](const ECBS& self) { return self.getGeneratedNodes(); },
             "Get the number of generated nodes");

    // ECBSResult class
    py::class_<ECBSResult>(m, "ECBSResult")
        .def(py::init<>())
        .def_readwrite("success", &ECBSResult::success)
        .def_readwrite("paths", &ECBSResult::paths)
        .def_readwrite("makespan", &ECBSResult::makespan)
        .def_readwrite("soc", &ECBSResult::soc)
        .def_readwrite("computation_time", &ECBSResult::computation_time)
        .def_readwrite("error_message", &ECBSResult::error_message);

    // Build a C++ graph from Python data
    m.def("create_graph_from_dict", [](const py::dict& graph_dict) {
        Graph graph;

        // Add nodes
        if (graph_dict.contains("nodes")) {
            py::dict nodes = graph_dict["nodes"];
            for (auto item : nodes) {
                std::string node_id = py::str(item.first);
                py::dict node_data = py::cast<py::dict>(item.second);

                double x = py::cast<double>(node_data["x"]);
                double y = py::cast<double>(node_data["y"]);

                graph.addNode(node_id, x, y);
            }
        }

        // Add edges
        if (graph_dict.contains("edges")) {
            py::list edges = graph_dict["edges"];
            for (auto edge_item : edges) {
                py::dict edge = py::cast<py::dict>(edge_item);

                std::string from = py::cast<std::string>(edge["from"]);
                std::string to = py::cast<std::string>(edge["to"]);
                double cost = edge.contains("cost") ?
                             py::cast<double>(edge["cost"]) : 1.0;

                graph.addEdge(from, to, cost);
            }
        }

        return graph;
    }, "Create Graph from Python dictionary",
       py::arg("graph_dict"));

    // Convenience ECBS solver
    m.def("solve_ecbs", [](const Graph& graph,
                          const std::vector<Agent>& agents,
                          double sub_optimality,
                          double time_limit) {
        ECBSResult result;

        try {
            ECBS solver(graph, agents, sub_optimality, time_limit);
            // Release the GIL while C++ code runs
            {
                py::gil_scoped_release release;
                bool success = solver.solve();
                result.success = success;
            }

            if (result.success) {
                result.paths = solver.getSolution();
                result.makespan = solver.getMakespan();
                result.soc = solver.getSOC();
            } else {
                result.error_message = "ECBS failed to find a solution within time limit";
            }
            result.computation_time = solver.getComputationTime();

        } catch (const std::exception& e) {
            result.success = false;
            result.error_message = std::string("Exception: ") + e.what();
        }

        return result;
    }, "Solve ECBS problem",
       py::arg("graph"),
       py::arg("agents"),
       py::arg("sub_optimality") = 1.1,
       py::arg("time_limit") = 5.0);

    // Version information
    m.attr("__version__") = "1.0.0";
}
