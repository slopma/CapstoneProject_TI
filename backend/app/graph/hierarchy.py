from typing import List, Dict, Any, Optional
import networkx as nx


def get_breadcrumbs(graph: nx.DiGraph, node_id: str) -> List[Dict[str, Any]]:
    if node_id not in graph:
        return []

    breadcrumbs = []
    curr = node_id
    visited = set()

    while curr and curr in graph and curr not in visited:
        visited.add(curr)
        node_data = graph.nodes[curr]
        breadcrumbs.append({
            "id": curr,
            "name": node_data.get("name", curr),
            "type": node_data.get("type", "unknown"),
            "level": node_data.get("level", 0),
        })
        curr = node_data.get("parent_id")

    return list(reversed(breadcrumbs))


def get_children(graph: nx.DiGraph, parent_id: str) -> List[Dict[str, Any]]:
    if parent_id not in graph:
        return []

    children = []
    for node_id, data in graph.nodes(data=True):
        if data.get("parent_id") == parent_id:
            children.append({"id": node_id, **data})
    return children


def get_descendants(graph: nx.DiGraph, parent_id: str) -> set:
    if parent_id not in graph:
        return set()

    descendants = set()
    queue = [parent_id]
    while queue:
        curr = queue.pop(0)
        for node_id, data in graph.nodes(data=True):
            if data.get("parent_id") == curr and node_id not in descendants:
                descendants.add(node_id)
                queue.append(node_id)
    return descendants


def filter_graph_view(
    graph: nx.DiGraph,
    parent_id: Optional[str] = None,
    level: Optional[int] = None,
    focus_node_id: Optional[str] = None,
    provider_filter: Optional[str] = None,
) -> Dict[str, Any]:
    nodes_out = []
    visible_node_ids = set()

    if focus_node_id and focus_node_id in graph:
        # Focus mode: Show focus node, its parent, children, direct dependencies and dependents
        visible_node_ids.add(focus_node_id)
        # Parent
        parent = graph.nodes[focus_node_id].get("parent_id")
        if parent:
            visible_node_ids.add(parent)
        # Children
        for child_id in get_descendants(graph, focus_node_id):
            visible_node_ids.add(child_id)
        # Dependencies (out-edges) & Dependents (in-edges)
        for _, target in graph.out_edges(focus_node_id):
            visible_node_ids.add(target)
        for source, _ in graph.in_edges(focus_node_id):
            visible_node_ids.add(source)
    elif parent_id:
        # Drill-down mode: Show current parent and its immediate children
        visible_node_ids.add(parent_id)
        for child_id in get_descendants(graph, parent_id):
            visible_node_ids.add(child_id)
    elif level is not None:
        # Level filter mode
        for n_id, data in graph.nodes(data=True):
            if data.get("level") == level:
                visible_node_ids.add(n_id)
    else:
        # Default mode: Return top-level nodes or all nodes
        visible_node_ids = set(graph.nodes)

    if provider_filter:
        visible_node_ids = {
            n_id for n_id in visible_node_ids
            if graph.nodes[n_id].get("provider") == provider_filter
        }

    for n_id in visible_node_ids:
        data = graph.nodes[n_id]
        nodes_out.append({"id": n_id, **data})

    edges_out = []
    for u, v, data in graph.edges(data=True):
        if u in visible_node_ids and v in visible_node_ids:
            edges_out.append({
                "source": u,
                "target": v,
                "type": data.get("type", "depends_on"),
                "is_hierarchy": data.get("is_hierarchy", False),
                "metadata": data.get("metadata", {}),
            })

    return {
        "nodes": nodes_out,
        "edges": edges_out,
        "total_nodes": len(graph.nodes),
        "visible_count": len(nodes_out),
    }
