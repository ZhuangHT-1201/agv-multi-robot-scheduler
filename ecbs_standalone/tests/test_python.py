#!/usr/bin/env python3
"""
Test the ECBS Python bindings
"""

import time
import sys


def test_basic_ecbs():
    """Basic ECBS test"""
    print("=" * 70)
    print("Test 1: basic ECBS")
    print("=" * 70)

    try:
        import ecbs_standalone as ecbs

        # Graph created
        graph = ecbs.Graph()


        for y in range(4):
            for x in range(4):
                node_id = f"n_{x}_{y}"
                graph.add_node(node_id, float(x), float(y))


        for y in range(4):
            for x in range(4):
                node_id = f"n_{x}_{y}"


                if x < 3:
                    graph.add_edge(node_id, f"n_{x+1}_{y}", 1.0)

                if y < 3:
                    graph.add_edge(node_id, f"n_{x}_{y+1}", 1.0)

                if x > 0:
                    graph.add_edge(node_id, f"n_{x-1}_{y}", 1.0)

                if y > 0:
                    graph.add_edge(node_id, f"n_{x}_{y-1}", 1.0)

        print(f"OK Graph created: {len(graph.nodes)}  nodes")

        # Agents created
        agents = [
            ecbs.Agent(0, "n_0_0", "n_3_3"),  # Agent 0: (0,0) -> (3,3)
            ecbs.Agent(1, "n_3_0", "n_0_3"),  # Agent 1: (3,0) -> (0,3)
            ecbs.Agent(2, "n_0_3", "n_3_0"),  # Agent 2: (0,3) -> (3,0)
        ]

        print(f"OK Agents created: {len(agents)}")


        solver = ecbs.ECBS(graph, agents, sub_optimality=1.1, time_limit=5.0)
        print("OK ECBS solver created")


        start_time = time.time()
        success = solver.solve()
        elapsed = time.time() - start_time

        if success:
            print(f"OK Solve succeeded!")
            print(f"  Computation time: {solver.get_computation_time()*1000:.2f} ms")
            print(f"  Makespan: {solver.get_makespan()}")
            print(f"  Sum of Costs: {solver.get_soc()}")
            print(f"  Expanded nodes: {solver.get_expanded_nodes()}")
            print(f"  Generated nodes: {solver.get_generated_nodes()}")


            solution = solver.get_solution()
            print("\nPaths:")
            for agent_id, path in solution.items():
                print(f"  Agent {agent_id}: {' -> '.join(path[:5])}{'...' if len(path) > 5 else ''} (length: {len(path)})")

            return True
        else:
            print("FAIL Solve failed")
            return False

    except ImportError as e:
        print(f"FAIL Cannot import ecbs_standalone: {e}")
        print("  Build and install first: python setup.py install")
        return False
    except Exception as e:
        print(f"FAIL Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_convenience_function():
    """Test helper function"""
    print("\n" + "=" * 70)
    print("Test 2: solve_ecbs helper")
    print("=" * 70)

    try:
        import ecbs_standalone as ecbs


        graph = ecbs.Graph()


        for i in range(6):
            graph.add_node(f"n{i}", float(i), 0.0)

        for i in range(4):
            graph.add_edge(f"n{i}", f"n{i+1}", 1.0)
            graph.add_edge(f"n{i+1}", f"n{i}", 1.0)
        graph.add_edge(f"n{2}", f"n{5}", 1.0)
        graph.add_edge(f"n{5}", f"n{2}", 1.0)


        agents = [
            ecbs.Agent(0, "n0", "n4"),
            ecbs.Agent(1, "n4", "n0"),
        ]


        result = ecbs.solve_ecbs(graph, agents, sub_optimality=1.1, time_limit=5.0)

        if result.success:
            print(f"OK Solve succeeded!")
            print(f"  Computation time: {result.computation_time*1000:.2f} ms")
            print(f"  Makespan: {result.makespan}")
            print(f"  Sum of Costs: {result.soc}")

            print("\nPaths:")
            for agent_id, path in result.paths.items():
                print(f"  Agent {agent_id}: {' -> '.join(path)}")

            return True
        else:
            print(f"FAIL Solve failed: {result.error_message}")
            return False

    except Exception as e:
        print(f"FAIL Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_performance_comparison():
    """Performance comparison"""
    print("\n" + "=" * 70)
    print("Test 3: performance comparison")
    print("=" * 70)

    try:
        import ecbs_standalone as ecbs


        graph = ecbs.Graph()

        for y in range(10):
            for x in range(10):
                node_id = f"n_{x}_{y}"
                graph.add_node(node_id, float(x), float(y))

        for y in range(10):
            for x in range(10):
                node_id = f"n_{x}_{y}"

                if x < 9:
                    graph.add_edge(node_id, f"n_{x+1}_{y}", 1.0)
                if y < 9:
                    graph.add_edge(node_id, f"n_{x}_{y+1}", 1.0)
                if x > 0:
                    graph.add_edge(node_id, f"n_{x-1}_{y}", 1.0)
                if y > 0:
                    graph.add_edge(node_id, f"n_{x}_{y-1}", 1.0)


        agents = [
            ecbs.Agent(0, "n_0_0", "n_9_9"),
            ecbs.Agent(1, "n_9_0", "n_0_9"),
            ecbs.Agent(2, "n_0_9", "n_9_0"),
            ecbs.Agent(3, "n_9_9", "n_0_0"),
            ecbs.Agent(4, "n_4_4", "n_5_5"),
        ]

        print(f"Graph size: 10x10 = 100 nodes")
        print(f"Agents: {len(agents)}")

        # C++ version
        start = time.time()
        result_cpp = ecbs.solve_ecbs(graph, agents, sub_optimality=1.1, time_limit=10.0)
        time_cpp = time.time() - start

        if result_cpp.success:
            print(f"\nOK C++ version:")
            print(f"  Solve time: {result_cpp.computation_time*1000:.2f} ms")
            print(f"  Makespan: {result_cpp.makespan}")
            print(f"  Sum of Costs: {result_cpp.soc}")
        else:
            print(f"FAIL C++ versionSolve failed")
            return False


        try:
            from algorithms.mapf_planner import ECBS as PythonECBS
            from common.graph import Graph as PythonGraph



            print("\n(Python comparison requires graph adaptation and is omitted)")

        except ImportError:
            print("\n(Python implementation not installed; comparison skipped)")

        return True

    except Exception as e:
        print(f"FAIL Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("ECBS Standalone Python Bindings - test suite")
    print("=" * 70 + "\n")

    results = []


    results.append(("Basic ECBS solve", test_basic_ecbs()))


    results.append(("helper function", test_convenience_function()))


    results.append(("Performance comparison", test_performance_comparison()))


    print("\n" + "=" * 70)
    print("Test summary")
    print("=" * 70)

    for name, success in results:
        status = "OK PASS" if success else "FAIL FAIL"
        print(f"{status}: {name}")

    passed = sum(1 for _, s in results if s)
    total = len(results)

    print(f"\nPassed: {passed}/{total}")

    return all(s for _, s in results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
