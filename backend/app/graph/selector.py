import networkx as nx
from app.graph.hierarchy import get_descendants


def select_subgraph(graph: nx.DiGraph, selected_resources: list[str]) -> nx.DiGraph:
    nodes = set()

    for resource in selected_resources:
        if resource not in graph:
            continue
        nodes.add(resource)

        # Include descendants if container/parent node selected
        descendants = get_descendants(graph, resource)
        nodes.update(descendants)

        # Include dependency descendants (out-edges)
        try:
            deps = nx.descendants(graph, resource)
            nodes.update(deps)
        except Exception:
            pass

    return graph.subgraph(nodes).copy()