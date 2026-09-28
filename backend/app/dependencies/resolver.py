from typing import List, Dict, Any, Set
import networkx as nx
from app.graph.hierarchy import get_descendants


def resolve_dependencies(
    graph: nx.DiGraph,
    selected_resources: List[str]
) -> Dict[str, Any]:
    selected_set: Set[str] = set()

    # Expand selected resources to include children if a parent container is selected
    for res_id in selected_resources:
        if res_id in graph:
            selected_set.add(res_id)
            selected_set.update(get_descendants(graph, res_id))

    required_direct: Set[str] = set()
    required_transitive: Set[str] = set()
    shared_dependencies: Set[str] = set()
    optional_dependencies: Set[str] = set()
    unresolved_dependencies: Set[str] = set()

    # Resolve direct dependencies (1st level out-edges with type != 'contains')
    for res_id in selected_set:
        if res_id not in graph:
            continue

        for _, target, edge_data in graph.out_edges(res_id, data=True):
            if edge_data.get("is_hierarchy"):
                continue

            if target not in selected_set:
                edge_type = edge_data.get("type", "depends_on")
                if edge_type in ("optional_depends_on", "recommends"):
                    optional_dependencies.add(target)
                else:
                    required_direct.add(target)

    # Resolve transitive dependencies recursively
    to_visit = list(required_direct)
    visited = set(selected_set).union(required_direct)

    while to_visit:
        curr = to_visit.pop(0)
        if curr not in graph:
            unresolved_dependencies.add(curr)
            continue

        for _, target, edge_data in graph.out_edges(curr, data=True):
            if edge_data.get("is_hierarchy"):
                continue
            if target not in visited:
                visited.add(target)
                required_transitive.add(target)
                to_visit.append(target)

    all_resolved = selected_set.union(required_direct).union(required_transitive).union(optional_dependencies)

    # Detect shared dependencies
    for dep_id in required_direct.union(required_transitive):
        if dep_id not in graph:
            continue

        node_data = graph.nodes[dep_id]
        if node_data.get("is_shared"):
            shared_dependencies.add(dep_id)
        else:
            # Check if any node outside all_resolved has an in-edge to this dep_id
            for source, _ in graph.in_edges(dep_id):
                if source not in all_resolved:
                    shared_dependencies.add(dep_id)
                    break

    all_deps_list = sorted(list(required_direct.union(required_transitive).union(optional_dependencies)))

    return {
        "selected": sorted(list(selected_set)),
        "required_direct": sorted(list(required_direct)),
        "required_transitive": sorted(list(required_transitive)),
        "shared_dependencies": sorted(list(shared_dependencies)),
        "optional_dependencies": sorted(list(optional_dependencies)),
        "unresolved_dependencies": sorted(list(unresolved_dependencies)),
        "dependencies": all_deps_list,  # For backward compatibility
        "all_included": sorted(list(all_resolved)),
    }