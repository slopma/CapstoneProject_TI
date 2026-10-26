from typing import List, Dict, Any, Set, Optional
import networkx as nx
from app.graph.hierarchy import get_descendants


def resolve_dependencies(
    graph: nx.DiGraph,
    selected_resources: List[str],
    validated_shared_resources: Optional[List[str]] = None,
    include_inferred: bool = False,
) -> Dict[str, Any]:
    selected_set: Set[str] = set()
    validated_shared_set: Set[str] = set(validated_shared_resources or [])

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
    confirmed_dependencies: Set[str] = set()
    inferred_dependencies: Set[str] = set()
    unknown_dependencies: Set[str] = set()
    inferred_dependency_details: List[Dict[str, Any]] = []

    # Resolve direct dependencies (1st level out-edges with is_hierarchy != True)
    for res_id in selected_set:
        if res_id not in graph:
            continue

        for _, target, edge_data in graph.out_edges(res_id, data=True):
            if edge_data.get("is_hierarchy"):
                continue

            if target not in selected_set:
                edge_type = edge_data.get("type", "depends_on")
                epistemic_state = edge_data.get("epistemic_state", "observed")
                confidence = edge_data.get("confidence", 1.0)
                target_node = graph.nodes.get(target, {})
                target_epistemic = target_node.get("epistemic_state", "observed")

                if target not in graph:
                    unresolved_dependencies.add(target)
                    unknown_dependencies.add(target)
                    continue

                if target_epistemic == "unknown" or epistemic_state == "unknown":
                    unknown_dependencies.add(target)

                if epistemic_state == "inferred" or edge_type == "inferred_relation":
                    inferred_dependencies.add(target)
                    inferred_dependency_details.append({
                        "source": res_id,
                        "target": target,
                        "type": edge_type,
                        "epistemic_state": "inferred",
                        "confidence": confidence,
                        "confirmed": False,
                        "reason": edge_data.get("metadata", {}).get("reason", "Heurística o conexión observada no confirmada"),
                    })
                    if not include_inferred:
                        continue

                if edge_type in ("optional_depends_on", "recommends"):
                    optional_dependencies.add(target)
                else:
                    required_direct.add(target)
                    if epistemic_state in ("observed", "derived"):
                        confirmed_dependencies.add(target)

    # Resolve transitive dependencies recursively
    to_visit = list(required_direct)
    visited = set(selected_set).union(required_direct)

    while to_visit:
        curr = to_visit.pop(0)
        if curr not in graph:
            unresolved_dependencies.add(curr)
            unknown_dependencies.add(curr)
            continue

        for _, target, edge_data in graph.out_edges(curr, data=True):
            if edge_data.get("is_hierarchy"):
                continue
            edge_type = edge_data.get("type", "depends_on")
            epistemic_state = edge_data.get("epistemic_state", "observed")
            if (epistemic_state == "inferred" or edge_type == "inferred_relation") and not include_inferred:
                if target not in selected_set:
                    inferred_dependencies.add(target)
                continue
            if target not in visited:
                visited.add(target)
                required_transitive.add(target)
                if epistemic_state in ("observed", "derived"):
                    confirmed_dependencies.add(target)
                to_visit.append(target)

    all_resolved = selected_set.union(required_direct).union(required_transitive).union(optional_dependencies)

    shared_dependency_policies: Dict[str, Dict[str, Any]] = {}
    # Detect shared dependencies
    for dep_id in required_direct.union(required_transitive):
        if dep_id not in graph:
            continue

        node_data = graph.nodes[dep_id]
        outside_consumers: List[str] = []
        for source, _, edge_data in graph.in_edges(dep_id, data=True):
            if edge_data.get("is_hierarchy"):
                continue
            if source not in all_resolved and source not in selected_set:
                outside_consumers.append(source)

        if node_data.get("is_shared") or outside_consumers:
            shared_dependencies.add(dep_id)
            is_validated = dep_id in validated_shared_set or dep_id in selected_set
            shared_dependency_policies[dep_id] = {
                "resource_id": dep_id,
                "name": node_data.get("name", dep_id),
                "type": node_data.get("type", "unknown"),
                "auto_migrate": is_validated,
                "requires_validation": not is_validated,
                "consumers_outside_selection": sorted(outside_consumers),
                "recommended_action": (
                    "validated_for_migration"
                    if is_validated
                    else "retain_shared_or_confirm_migration"
                ),
            }

    all_deps_list = sorted(list(required_direct.union(required_transitive).union(optional_dependencies)))
    unvalidated_shared = {
        dep_id for dep_id, policy in shared_dependency_policies.items()
        if not policy["auto_migrate"]
    }
    auto_migratable = sorted(list(all_resolved - unvalidated_shared))

    return {
        "selected": sorted(list(selected_set)),
        "required_direct": sorted(list(required_direct)),
        "required_transitive": sorted(list(required_transitive)),
        "confirmed_dependencies": sorted(list(confirmed_dependencies)),
        "inferred_dependencies": sorted(list(inferred_dependencies)),
        "inferred_dependency_details": inferred_dependency_details,
        "unknown_dependencies": sorted(list(unknown_dependencies)),
        "shared_dependencies": sorted(list(shared_dependencies)),
        "shared_dependency_policies": shared_dependency_policies,
        "optional_dependencies": sorted(list(optional_dependencies)),
        "unresolved_dependencies": sorted(list(unresolved_dependencies)),
        "dependencies": all_deps_list,  # For backward compatibility
        "all_included": sorted(list(all_resolved)),
        "auto_migratable_resources": auto_migratable,
    }